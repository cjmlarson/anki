"""Sync vocab.py cards to AnkiWeb."""

import getpass
import json
import os

from anki.collection import Collection
from anki.sync_pb2 import SyncAuth, SyncCollectionResponse

from vocab import CARDS

COLLECTION_PATH = os.path.expanduser("~/.local/share/anki-decks/collection.anki2")
AUTH_PATH = os.path.expanduser("~/.local/share/anki-decks/auth.json")
DECK_NAME = "German Vocab"
MODEL_NAME = "German Vocab"

MODEL_CSS = """\
.card { font-family: arial; font-size: 20px; text-align: center; color: black; background-color: white; }
.word { font-size: 1.2em; font-weight: bold; }
.example { margin-top: 0.8em; font-size: 0.85em; color: #555; font-style: italic; }
.grammar { margin-top: 0.5em; font-size: 0.8em; color: #888; }
"""


def load_auth() -> SyncAuth | None:
    """Load cached auth token, or return None if not cached."""
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
    """Persist auth token and endpoint to disk."""
    os.makedirs(os.path.dirname(AUTH_PATH), exist_ok=True)
    with open(AUTH_PATH, "w") as f:
        json.dump({
            "hkey": auth.hkey,
            "endpoint": auth.endpoint or None,
        }, f)


def get_auth(col: Collection) -> SyncAuth:
    """Get SyncAuth, prompting for credentials on first run."""
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


def build_field(word: str, example: str | None, grammar: str | None) -> str:
    """Build a field value: word + optional example + optional grammar."""
    html = f'<div class="word">{word}</div>'
    if example:
        html += f'<div class="example">{example}</div>'
    if grammar:
        html += f'<div class="grammar">{grammar}</div>'
    return html


def get_or_create_model(col: Collection):
    """Get existing 'German Vocab' model, or create it. Recreates if field count changed."""
    model = col.models.by_name(MODEL_NAME)
    if model:
        field_names = [f["name"] for f in model["flds"]]
        if field_names == ["Deutsche", "English"]:
            return model
        # Model exists with wrong fields — remove all its notes and the model itself
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
    """Remove all notes using old models in our deck."""
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
    """Add/update/remove cards to match vocab.py."""
    deck_id = col.decks.add_normal_deck_with_name(DECK_NAME).id
    model = get_or_create_model(col)

    # Remove old-model notes on first migration
    removed_old = remove_old_model_notes(col)
    if removed_old:
        print(f"Removed {removed_old} old 'Basic (and reversed card)' notes.")

    # Fetch all existing notes in the deck (keyed on raw word from Deutsche field)
    existing_by_word: dict[str, int] = {}
    for nid in col.find_notes(f'"deck:{DECK_NAME}"'):
        note = col.get_note(nid)
        existing_by_word[note["Deutsche"]] = nid

    vocab_de_fields = set()
    added = 0
    updated = 0
    for card in CARDS:
        ex = card.get("example")
        grammar = card.get("grammar")
        de_field = build_field(card["front"], ex["de"] if ex else None, grammar)
        en_field = build_field(card["back"], ex["en"] if ex else None, None)
        tags = card.get("tags", [])
        vocab_de_fields.add(de_field)

        if de_field in existing_by_word:
            note = col.get_note(existing_by_word[de_field])
            changed = False
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

    # Remove cards no longer in vocab.py
    nids_to_remove = [
        nid for de, nid in existing_by_word.items()
        if de not in vocab_de_fields
    ]
    if nids_to_remove:
        col.remove_notes(nids_to_remove)

    removed = len(nids_to_remove)
    print(f"Cards: {added} added, {updated} updated, {removed} removed, {len(CARDS)} total in vocab.py")


def do_sync(col: Collection, auth: SyncAuth) -> None:
    """Sync collection with AnkiWeb."""
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
        # FULL_SYNC on a fresh collection defaults to upload
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
        sync_cards(col)
        do_sync(col, auth)
    finally:
        try:
            col.close()
        except Exception:
            pass  # may already be closed after full_upload_or_download


if __name__ == "__main__":
    main()
