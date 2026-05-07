# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project does

Converts [RuWordNet](https://ruwordnet.ru) (Russian WordNet) into a [WN-LMF](https://globalwordnet.github.io/schemas/) 1.1 XML file (`russian-wordnet-2021.xml`) that can be loaded by the [`wn`](https://wn.readthedocs.io) Python library.

## Commands

```bash
# Generate the XML (takes a few minutes — ruwordnet attribute access is slow)
python3 main.py

# Run all tests (XML must exist first)
python3 -m unittest test.py -v

# Run a single test
python3 -m unittest test.TestRuWordNetLMF.test_no_validation_errors
```

## Architecture

The project is two files:

**`main.py`** — the converter. Three sequential phases:
1. Load all senses from ruwordnet and group by lowercased lemma (`lemma_to_senses`) — source data is all-caps (e.g. `"МОСКВА"`)
2. Emit `LexicalEntry` elements per lemma, with senses deduplicated by `synset_id` (the source data has ~80 duplicate `(lemma, synset_id)` pairs with different sense IDs). If a lemma's senses split across proper-noun and common-noun synsets, emit one entry per distinct `writtenForm`.
3. Emit one synset per ruwordnet synset, resolving ILI via `build_ili_map()` and filtering self-loop relations via the `target.id == synset.id` guard in `build_synset_relations()`

**Proper-noun casing**: `build_ili_map()` also returns `wn_proper` — a dict from PWN offset → `'title'`|`'capitalize'`. Proper-noun status is detected from omw-en:1.4 synsets whose lemmas have an uppercase initial letter, restricted to `noun.*` lexfiles (adj/verb forms stay lowercase in Russian). `noun.person`, `noun.location`, and `noun.object` use `str.title()` (all words); all other noun lexfiles use first-letter-only capitalize. Synsets with no ILI link, or whose ILI points to a common noun, keep the lowercased form.

**ILI resolution**: RuWordNet stores ILI as bare PWN 3.0 offset strings (e.g. `"02084071-n"`). These are **not** valid CILI IDs. `build_ili_map()` loads `omw-en:1.4` and builds a dict from that offset format → actual CILI ID (`iliXXXXXX`). Synsets without a mapping get `ili='in'` (no ILI).

**`test.py`** — loads the generated XML into a temporary `wn` data directory and validates:
- Lexicon/language metadata
- Synset and sense counts (matched against live ruwordnet data, accounting for deduplication)
- ILI count parity
- No `wn.validate` errors (E-codes only; W-codes are checked but only failures are asserted)

## Known validation warnings (expected, unfixable)

Running `wn.validate` on the output produces three categories of warnings that are **not** bugs:

| Code | Count | Reason |
|------|-------|--------|
| W302 | ~3,217 | Multiple synsets share a CILI ID — granularity mismatch between Russian and English concepts |
| W303 | ~38,481 | Synsets with `ili='in'` and no definition — source data has no definitions for these |
| W307 | ~16,236 | Duplicate definition text — inherited/auto-generated definitions in ruwordnet |
