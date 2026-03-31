"""Sync vocab.py cards to AnkiWeb."""

import getpass
import json
import os
import sys

from anki.collection import Collection
from anki.sync_pb2 import SyncAuth, SyncCollectionResponse

from vocab import CARDS

COLLECTION_PATH = os.path.expanduser("~/.local/share/anki-decks/collection.anki2")
AUTH_PATH = os.path.expanduser("~/.local/share/anki-decks/auth.json")
DECK_NAME = "German Vocab"
MODEL_NAME = "Basic (and reversed card)"


def get_auth(col: Collection) -> SyncAuth:
    """Get SyncAuth, prompting for credentials on first run."""
    if os.path.exists(AUTH_PATH):
        with open(AUTH_PATH) as f:
            data = json.load(f)
        auth = SyncAuth()
        auth.hkey = data["hkey"]
        if data.get("endpoint"):
            auth.endpoint = data["endpoint"]
        return auth

    print("AnkiWeb login required (credentials are not stored, only the session token).")
    username = input("AnkiWeb username (email): ")
    password = getpass.getpass("AnkiWeb password: ")
    auth = col.sync_login(username=username, password=password, endpoint=None)
    os.makedirs(os.path.dirname(AUTH_PATH), exist_ok=True)
    with open(AUTH_PATH, "w") as f:
        json.dump({"hkey": auth.hkey, "endpoint": auth.endpoint or ""}, f)
    print("Auth token saved.")
    return auth


def build_back(card: dict) -> str:
    """Build the Back field HTML from a card definition."""
    back = card["back"]
    if "example" in card:
        ex = card["example"]
        back += f'<div class="example">„{ex["de"]}"<br>{ex["en"]}</div>'
    if "grammar" in card:
        back += f'<div class="grammar">{card["grammar"]}</div>'
    return back


def sync_cards(col: Collection, auth: SyncAuth) -> None:
    """Add/update cards from vocab.py into the collection."""
    deck = col.decks.by_name(DECK_NAME)
    if deck:
        deck_id = deck["id"]
    else:
        result = col.decks.add_normal_deck_with_name(DECK_NAME)
        deck_id = result.id

    model = col.models.by_name(MODEL_NAME)

    vocab_fronts = set()
    added = 0
    updated = 0
    for card in CARDS:
        front = card["front"]
        vocab_fronts.add(front)
        back = build_back(card)
        tags = card.get("tags", [])

        existing = col.find_notes(f'"Front:{front}"')
        if existing:
            note = col.get_note(existing[0])
            changed = False
            if note["Back"] != back:
                note["Back"] = back
                changed = True
            if sorted(note.tags) != sorted(tags):
                note.tags = tags
                changed = True
            if changed:
                col.update_note(note)
                updated += 1
        else:
            note = col.new_note(model)
            note["Front"] = front
            note["Back"] = back
            note.tags = tags
            col.add_note(note, deck_id)
            added += 1

    # Remove cards no longer in vocab.py
    removed = 0
    all_nids = col.find_notes(f'"deck:{DECK_NAME}"')
    for nid in all_nids:
        note = col.get_note(nid)
        if note["Front"] not in vocab_fronts:
            col.remove_notes([nid])
            removed += 1

    print(f"Cards: {added} added, {updated} updated, {removed} removed, {len(CARDS)} total in vocab.py")


def do_sync(col: Collection, auth: SyncAuth) -> None:
    """Sync collection with AnkiWeb."""
    print("Syncing with AnkiWeb...")
    result = col.sync_collection(auth=auth, sync_media=False)

    # AnkiWeb may redirect to a specific sync server
    if result.new_endpoint:
        auth.endpoint = result.new_endpoint

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

    # Cache the endpoint for future syncs
    if result.new_endpoint and os.path.exists(AUTH_PATH):
        with open(AUTH_PATH) as f:
            data = json.load(f)
        data["endpoint"] = result.new_endpoint
        with open(AUTH_PATH, "w") as f:
            json.dump(data, f)

    if result.server_message:
        print(f"Server message: {result.server_message}")


def main():
    os.makedirs(os.path.dirname(COLLECTION_PATH), exist_ok=True)

    col = Collection(COLLECTION_PATH)
    try:
        auth = get_auth(col)
        sync_cards(col, auth)
        do_sync(col, auth)
    finally:
        try:
            col.close()
        except Exception:
            pass  # may already be closed after full sync


if __name__ == "__main__":
    main()
