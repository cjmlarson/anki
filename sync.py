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
.example { margin-top: 1em; font-size: 0.85em; color: #555; font-style: italic; }
.grammar { margin-top: 0.5em; font-size: 0.8em; color: #888; }
"""

CARD1_QFMT = "{{German}}"
CARD1_AFMT = """\
{{FrontSide}}
<hr id=answer>
{{English}}
{{#ExampleDE}}<div class="example">\u201e{{ExampleDE}}\u201c<br>{{ExampleEN}}</div>{{/ExampleDE}}
{{#Grammar}}<div class="grammar">{{Grammar}}</div>{{/Grammar}}"""

CARD2_QFMT = "{{English}}"
CARD2_AFMT = """\
{{FrontSide}}
<hr id=answer>
{{German}}
{{#ExampleDE}}<div class="example">\u201e{{ExampleDE}}\u201c<br>{{ExampleEN}}</div>{{/ExampleDE}}
{{#Grammar}}<div class="grammar">{{Grammar}}</div>{{/Grammar}}"""


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


def get_or_create_model(col: Collection):
    """Get existing 'German Vocab' model, or create it."""
    model = col.models.by_name(MODEL_NAME)
    if model:
        return model

    m = col.models.new(MODEL_NAME)
    m["css"] = MODEL_CSS
    for name in ["German", "English", "ExampleDE", "ExampleEN", "Grammar"]:
        col.models.add_field(m, col.models.new_field(name))

    t1 = col.models.new_template("Card 1")
    t1["qfmt"] = CARD1_QFMT
    t1["afmt"] = CARD1_AFMT
    col.models.add_template(m, t1)

    t2 = col.models.new_template("Card 2")
    t2["qfmt"] = CARD2_QFMT
    t2["afmt"] = CARD2_AFMT
    col.models.add_template(m, t2)

    col.models.add(m)
    print(f"Created note model '{MODEL_NAME}' with 5 fields and 2 templates.")
    return col.models.by_name(MODEL_NAME)


def remove_old_model_notes(col: Collection) -> int:
    """Remove all notes using the old 'Basic (and reversed card)' model in our deck."""
    old_model = col.models.by_name("Basic (and reversed card)")
    if not old_model:
        return 0
    nids = col.find_notes(f'"deck:{DECK_NAME}" "note:Basic (and reversed card)"')
    if nids:
        col.remove_notes(nids)
    return len(nids)


def sync_cards(col: Collection) -> None:
    """Add/update/remove cards to match vocab.py."""
    deck_id = col.decks.add_normal_deck_with_name(DECK_NAME).id
    model = get_or_create_model(col)

    # Remove old-model notes on first migration
    removed_old = remove_old_model_notes(col)
    if removed_old:
        print(f"Removed {removed_old} old 'Basic (and reversed card)' notes.")

    # Fetch all existing notes in the deck (keyed on German field)
    existing_by_german: dict[str, int] = {}
    for nid in col.find_notes(f'"deck:{DECK_NAME}"'):
        note = col.get_note(nid)
        existing_by_german[note["German"]] = nid

    vocab_germans = set()
    added = 0
    updated = 0
    for card in CARDS:
        german = card["front"]
        english = card["back"]
        ex = card.get("example", {})
        example_de = ex.get("de", "")
        example_en = ex.get("en", "")
        grammar = card.get("grammar", "")
        tags = card.get("tags", [])
        vocab_germans.add(german)

        fields = {
            "German": german,
            "English": english,
            "ExampleDE": example_de,
            "ExampleEN": example_en,
            "Grammar": grammar,
        }

        if german in existing_by_german:
            note = col.get_note(existing_by_german[german])
            changed = False
            for key, val in fields.items():
                if note[key] != val:
                    note[key] = val
                    changed = True
            if set(note.tags) != set(tags):
                note.tags = tags
                changed = True
            if changed:
                col.update_note(note)
                updated += 1
        else:
            note = col.new_note(model)
            for key, val in fields.items():
                note[key] = val
            note.tags = tags
            col.add_note(note, deck_id)
            added += 1

    # Remove cards no longer in vocab.py
    nids_to_remove = [
        nid for german, nid in existing_by_german.items()
        if german not in vocab_germans
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
