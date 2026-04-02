"""Sync vocab.csv cards to AnkiWeb, then export review progress."""

import csv
import getpass
import json
import os
import re

from anki.collection import Collection
from anki.sync_pb2 import SyncAuth, SyncCollectionResponse

COLLECTION_PATH = os.path.expanduser("~/.local/share/anki-decks/collection.anki2")
AUTH_PATH = os.path.expanduser("~/.local/share/anki-decks/auth.json")
DECK_NAME = "German Vocab"
MODEL_NAME = "German Vocab"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

WORD_DIV_RE = re.compile(r'<div class="word">(.*?)</div>')

MODEL_CSS = """\
.card { font-family: arial; font-size: 20px; text-align: center; color: black; background-color: white; }
.word { font-size: 1.2em; font-weight: bold; }
.example { margin-top: 0.8em; font-size: 0.85em; color: #555; font-style: italic; }
"""


def load_vocab() -> list[dict]:
    """Read vocab.csv and return list of card dicts."""
    path = os.path.join(BASE_DIR, "vocab.csv")
    cards = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            cards.append(row)
    return cards


def load_auth() -> SyncAuth | None:
    if not os.path.exists(AUTH_PATH):
        return None
    with open(AUTH_PATH) as f:
        data = json.load(f)
    auth = SyncAuth()
    auth.hkey = data["hkey"]
    if data.get("endpoint"):
        auth.endpoint = data["endpoint"]
    return auth


def save_auth(auth: SyncAuth) -> None:
    os.makedirs(os.path.dirname(AUTH_PATH), exist_ok=True)
    with open(AUTH_PATH, "w") as f:
        json.dump({
            "hkey": auth.hkey,
            "endpoint": auth.endpoint or None,
        }, f)


def get_auth(col: Collection) -> SyncAuth:
    auth = load_auth()
    if auth:
        return auth
    print("AnkiWeb login required (credentials are not stored, only the session token).")
    username = input("AnkiWeb username (email): ")
    password = getpass.getpass("AnkiWeb password: ")
    auth = col.sync_login(username=username, password=password, endpoint=None)
    save_auth(auth)
    print("Auth token saved.")
    return auth


def bold_word_in_example(word: str, example: str) -> str:
    """Bold occurrences of the base word within the example sentence."""
    base = re.sub(r'^(der|die|das)\s+', '', word).split(',')[0].strip()
    pattern = re.compile(re.escape(base), re.IGNORECASE)
    return pattern.sub(lambda m: f'<b>{m.group()}</b>', example)


def build_field(word: str, example: str | None) -> str:
    """Build a field value: word + optional example."""
    html = f'<div class="word">{word}</div>'
    if example:
        example = bold_word_in_example(word, example)
        html += f'<div class="example">{example}</div>'
    return html


def strip_html(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s).strip()


def get_or_create_model(col: Collection):
    model = col.models.by_name(MODEL_NAME)
    if model:
        field_names = [f["name"] for f in model["flds"]]
        if field_names == ["Deutsche", "English"]:
            return model
        nids = col.find_notes(f'"note:{MODEL_NAME}"')
        if nids:
            col.remove_notes(nids)
            print(f"Removed {len(nids)} notes from old '{MODEL_NAME}' model.")
        col.models.remove(model["id"])
        print(f"Removed old '{MODEL_NAME}' model (had fields: {field_names}).")

    m = col.models.new(MODEL_NAME)
    m["css"] = MODEL_CSS
    for name in ["Deutsche", "English"]:
        col.models.add_field(m, col.models.new_field(name))

    t1 = col.models.new_template("Card 1")
    t1["qfmt"] = "{{Deutsche}}"
    t1["afmt"] = "{{FrontSide}}<hr id=answer>{{English}}"
    col.models.add_template(m, t1)

    t2 = col.models.new_template("Card 2")
    t2["qfmt"] = "{{English}}"
    t2["afmt"] = "{{FrontSide}}<hr id=answer>{{Deutsche}}"
    col.models.add_template(m, t2)

    col.models.add(m)
    print(f"Created note model '{MODEL_NAME}' with 2 fields and 2 templates.")
    return col.models.by_name(MODEL_NAME)


def remove_old_model_notes(col: Collection) -> int:
    removed = 0
    for old_name in ["Basic (and reversed card)"]:
        if not col.models.by_name(old_name):
            continue
        nids = col.find_notes(f'"deck:{DECK_NAME}" "note:{old_name}"')
        if nids:
            col.remove_notes(nids)
            removed += len(nids)
    return removed


def sync_cards(col: Collection) -> None:
    """Add/update/remove cards to match vocab.csv."""
    cards = load_vocab()
    deck_id = col.decks.add_normal_deck_with_name(DECK_NAME).id
    model = get_or_create_model(col)

    removed_old = remove_old_model_notes(col)
    if removed_old:
        print(f"Removed {removed_old} old 'Basic (and reversed card)' notes.")

    existing_by_word: dict[str, int] = {}
    for nid in col.find_notes(f'"deck:{DECK_NAME}"'):
        note = col.get_note(nid)
        match = WORD_DIV_RE.search(note["Deutsche"])
        raw_word = match.group(1) if match else note["Deutsche"]
        existing_by_word[raw_word] = nid

    vocab_words = set()
    added = 0
    updated = 0
    for card in cards:
        de_ex = card["example_de"] or None
        en_ex = card["example_en"] or None
        de_field = build_field(card["deutsche"], de_ex)
        en_field = build_field(card["english"], en_ex)
        tags = card["tags"].split() if card["tags"] else []
        raw_word = card["deutsche"]
        vocab_words.add(raw_word)

        if raw_word in existing_by_word:
            note = col.get_note(existing_by_word[raw_word])
            changed = False
            if note["Deutsche"] != de_field:
                note["Deutsche"] = de_field
                changed = True
            if note["English"] != en_field:
                note["English"] = en_field
                changed = True
            if set(note.tags) != set(tags):
                note.tags = tags
                changed = True
            if changed:
                col.update_note(note)
                updated += 1
        else:
            note = col.new_note(model)
            note["Deutsche"] = de_field
            note["English"] = en_field
            note.tags = tags
            col.add_note(note, deck_id)
            added += 1

    nids_to_remove = [
        nid for word, nid in existing_by_word.items()
        if word not in vocab_words
    ]
    if nids_to_remove:
        col.remove_notes(nids_to_remove)

    removed = len(nids_to_remove)
    print(f"Cards: {added} added, {updated} updated, {removed} removed, {len(cards)} total in vocab.csv")


def export_reviews(col: Collection) -> None:
    """Export review progress from the collection to reviews.csv."""
    rows = []
    for nid in col.find_notes(f'"deck:{DECK_NAME}"'):
        note = col.get_note(nid)
        de_match = WORD_DIV_RE.search(note["Deutsche"])
        de_word = de_match.group(1) if de_match else strip_html(note["Deutsche"])
        en_match = WORD_DIV_RE.search(note["English"])
        en_word = en_match.group(1) if en_match else strip_html(note["English"])
        for card in note.cards():
            direction = "DE→EN" if card.ord == 0 else "EN→DE"
            ease = round(card.factor / 1000, 2) if card.factor else 0
            rows.append([
                de_word, en_word, direction,
                card.ivl, ease, card.due,
                card.reps, card.lapses, card.type, card.queue,
            ])

    rows.sort(key=lambda r: (r[0].lower(), r[2]))
    path = os.path.join(BASE_DIR, "reviews.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["deutsche", "english", "direction", "interval_days", "ease",
                     "due", "reviews", "lapses", "type", "queue"])
        w.writerows(rows)
    print(f"Exported {len(rows)} card reviews to reviews.csv")


def export_deck_json() -> None:
    """Write deck.json with model metadata."""
    deck = {
        "name": DECK_NAME,
        "model": MODEL_NAME,
        "fields": ["Deutsche", "English"],
        "templates": [
            {"name": "Card 1", "qfmt": "{{Deutsche}}", "afmt": "{{FrontSide}}<hr id=answer>{{English}}"},
            {"name": "Card 2", "qfmt": "{{English}}", "afmt": "{{FrontSide}}<hr id=answer>{{Deutsche}}"},
        ],
        "css": MODEL_CSS,
    }
    path = os.path.join(BASE_DIR, "deck.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(deck, f, indent=2)
    print("Exported deck.json")


def do_sync(col: Collection, auth: SyncAuth) -> None:
    print("Syncing with AnkiWeb...")
    result = col.sync_collection(auth=auth, sync_media=False)

    if result.new_endpoint:
        auth.endpoint = result.new_endpoint
        save_auth(auth)

    if result.required == SyncCollectionResponse.NO_CHANGES:
        print("Already in sync.")
    elif result.required == SyncCollectionResponse.NORMAL_SYNC:
        print("Normal sync completed.")
    elif result.required in (
        SyncCollectionResponse.FULL_SYNC,
        SyncCollectionResponse.FULL_UPLOAD,
    ):
        print("Full upload required — uploading local collection to AnkiWeb...")
        col.close_for_full_sync()
        col.full_upload_or_download(auth=auth, server_usn=None, upload=True)
        print("Full upload complete.")
    elif result.required == SyncCollectionResponse.FULL_DOWNLOAD:
        print("Full download required — downloading from AnkiWeb...")
        col.close_for_full_sync()
        col.full_upload_or_download(auth=auth, server_usn=None, upload=False)
        print("Full download complete.")

    if result.server_message:
        print(f"Server message: {result.server_message}")


def main():
    os.makedirs(os.path.dirname(COLLECTION_PATH), exist_ok=True)

    col = Collection(COLLECTION_PATH)
    try:
        auth = get_auth(col)
        print("--- Pull from AnkiWeb ---")
        do_sync(col, auth)
        sync_cards(col)
        export_reviews(col)
        export_deck_json()
        print("--- Push to AnkiWeb ---")
        do_sync(col, auth)
    finally:
        try:
            col.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
