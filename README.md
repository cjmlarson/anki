# German Vocab

German vocabulary flashcards synced to AnkiWeb. Each word produces two cards (DE→EN and EN→DE), with optional example sentences.

## Files

- `vocab.csv` — source of truth for all vocabulary (edit this to add/change words)
- `sync.py` — syncs vocab.csv to AnkiWeb, exports review progress
- `reviews.csv` — exported review stats (interval, ease, reps, lapses)
- `deck.json` — deck metadata and card templates

## Usage

```
uv run python sync.py
```

This will:
1. Add/update/remove cards in the local Anki collection to match vocab.csv
2. Export review progress to reviews.csv
3. Sync to AnkiWeb (prompts for login on first run)

## Adding vocab

Add a row to `vocab.csv`:

```
deutsche,english,example_de,example_en,grammar,tags
```

The `grammar` column is kept for reference but not shown on cards.

### Card creation rules

When extracting vocab from German text:
- Include **function words** (adverbs, connectors like *allerdings*, *schliesslich*, *bereits*) — not just content words
- For **compound words**, also add entries for any sub-words not already in the deck (e.g. *Steinschlag* → also add *Stein* and *Schlag*)
