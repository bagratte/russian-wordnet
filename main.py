#!/usr/bin/env python3

import sys
from collections import defaultdict

import ruwordnet
import wn
from sqlalchemy import select
from wn import lmf


def progress(current, total, label):
    pct = current / total * 100
    bar = '#' * (current * 30 // total)
    sys.stdout.write(f'\r  {label}: [{bar:<30}] {current}/{total} ({pct:.0f}%)')
    sys.stdout.flush()
    if current == total:
        sys.stdout.write('\n')

POS_MAP = {
    'N': 'n',
    'V': 'v',
    'Adj': 'a',
    'Adv': 'r',
}

SYNSET_RELATIONS = [
    ('hypernyms',       'hypernym'),
    ('hyponyms',        'hyponym'),
    ('holonyms',        'holo_member'),
    ('meronyms',        'mero_member'),
    # domains: I am the domain_item → point at the domain
    ('domains',         'domain_topic'),
    # domain_items: I am the domain → point at my items
    ('domain_items',    'has_domain_topic'),
    ('instances',       'instance_hyponym'),
    ('classes',         'instance_hypernym'),
    ('causes',          'causes'),
    ('effects',         'is_caused_by'),
    ('premises',        'entails'),
    ('conclusions',     'is_entailed_by'),
    # symmetric — only one direction stored per synset
    ('pos_synonyms',    'similar'),
    ('antonyms',        'antonym'),
    ('related',         'also'),
]


TITLE_LEXFILES = {'noun.person', 'noun.location', 'noun.object'}

def build_ili_map():
    prefix = 'omw-en-'
    ili_map = {}
    wn_proper = {}  # wn_id -> 'title' | 'capitalize'
    for s in wn.synsets(lexicon='omw-en:1.4'):
        wn_id = s.id[len(prefix):]
        if s.ili:
            ili_map[wn_id] = s.ili
        lf = s.lexfile()
        if lf and lf.startswith('noun.') and any(l[0].isupper() for l in s.lemmas()):
            wn_proper[wn_id] = 'title' if lf in TITLE_LEXFILES else 'capitalize'
    return ili_map, wn_proper


def load_synset_bulk_data(session):
    """Bulk-load every relation table in one query each, avoiding N+1 lazy loads."""
    from ruwordnet.models import (
        hypernymy_table, domains_table, meronymy_table, instances_table,
        entailment_table, cause_table, pos_synonymy_table, antonymy_table,
        related_table, ili_table,
    )

    # (attr_name, from_col, to_col) — matches SYNSET_RELATIONS attribute names
    SPECS = [
        ('hypernyms',    hypernymy_table.c.hyponym_id,     hypernymy_table.c.hypernym_id),
        ('hyponyms',     hypernymy_table.c.hypernym_id,    hypernymy_table.c.hyponym_id),
        ('holonyms',     meronymy_table.c.meronym_id,      meronymy_table.c.holonym_id),
        ('meronyms',     meronymy_table.c.holonym_id,      meronymy_table.c.meronym_id),
        ('domains',      domains_table.c.domain_item_id,   domains_table.c.domain_id),
        ('domain_items', domains_table.c.domain_id,        domains_table.c.domain_item_id),
        ('instances',    instances_table.c.class_id,       instances_table.c.instance_id),
        ('classes',      instances_table.c.instance_id,    instances_table.c.class_id),
        ('causes',       cause_table.c.effect_id,          cause_table.c.cause_id),
        ('effects',      cause_table.c.cause_id,           cause_table.c.effect_id),
        ('premises',     entailment_table.c.conclusion_id, entailment_table.c.premise_id),
        ('conclusions',  entailment_table.c.premise_id,    entailment_table.c.conclusion_id),
        ('pos_synonyms', pos_synonymy_table.c.right_id,    pos_synonymy_table.c.left_id),
        ('antonyms',     antonymy_table.c.right_id,        antonymy_table.c.left_id),
        ('related',      related_table.c.right_id,         related_table.c.left_id),
    ]

    rel_dicts = {}
    for attr, from_col, to_col in SPECS:
        d = defaultdict(list)
        for from_id, to_id in session.execute(select(from_col, to_col)):
            d[from_id].append(to_id)
        rel_dicts[attr] = d

    # ILI: ruwn synset_id -> first linked wn_synset id
    ili_d = {}
    for ruwn_id, wn_id in session.execute(select(ili_table.c.ruwn_id, ili_table.c.wn_id)):
        if ruwn_id not in ili_d:
            ili_d[ruwn_id] = wn_id

    return rel_dicts, ili_d


def resolve_ili(synset_id, ili_d, ili_map):
    wn_id = ili_d.get(synset_id)
    if not wn_id:
        return 'in'
    # wn_id is a bare offset like "02084071-n"; strip the "omw-en-" prefix already done in ili_map
    return ili_map.get(wn_id, 'in')


def build_synset_relations(synset_id, rel_dicts):
    seen = set()
    rels = []
    for attr, rel_type in SYNSET_RELATIONS:
        for target_id in rel_dicts[attr].get(synset_id, ()):
            if target_id == synset_id:
                continue
            key = (target_id, rel_type)
            if key not in seen:
                seen.add(key)
                rels.append({'target': target_id, 'relType': rel_type})
    return rels


def written_form(lemma, casing):
    if casing == 'title':
        return lemma.title()
    if casing == 'capitalize':
        return lemma[0].upper() + lemma[1:]
    return lemma


def build_lmf(ruwn, ili_map, wn_proper):
    all_senses = ruwn.senses
    print(f'Building entries from {len(all_senses)} senses...')
    lemma_to_senses = defaultdict(list)
    for i, sense in enumerate(all_senses, 1):
        if sense.name and sense.synset_id:
            lemma_to_senses[sense.name.lower()].append(sense)
        progress(i, len(all_senses), 'senses')

    all_synsets = ruwn.synsets
    synset_pos = {s.id: POS_MAP.get(s.part_of_speech, 'n') for s in all_synsets}

    print('Bulk-loading synset relations...')
    rel_dicts, ili_d = load_synset_bulk_data(ruwn.session)

    # Senses with a proper-noun ILI get a cased writtenForm; others stay lowercase.
    # If a lemma has both kinds, emit separate LexicalEntry elements (one per form).
    entries = []
    entry_idx = 0
    lemma_items = list(lemma_to_senses.items())
    print(f'Building lexical entries from {len(lemma_items)} lemmas...')
    for i, (lemma, senses) in enumerate(lemma_items, 1):
        form_senses = defaultdict(list)
        for s in senses:
            wn_id = ili_d.get(s.synset_id)
            casing = wn_proper.get(wn_id) if wn_id else None
            form_senses[written_form(lemma, casing)].append(s)

        for form, group in form_senses.items():
            entry_idx += 1
            seen_synsets = set()
            deduped = []
            for s in group:
                if s.synset_id not in seen_synsets:
                    seen_synsets.add(s.synset_id)
                    deduped.append(s)
            pos = next(
                (synset_pos[s.synset_id] for s in deduped if s.synset_id in synset_pos),
                'n',
            )
            entries.append({
                'id': f'ruwn-le-{entry_idx}',
                'lemma': {'writtenForm': form, 'partOfSpeech': pos},
                'senses': [{'id': s.id, 'synset': s.synset_id} for s in deduped],
            })
        progress(i, len(lemma_items), 'entries')

    print(f'Building {len(all_synsets)} synsets...')
    synsets = []
    for i, synset in enumerate(all_synsets, 1):
        ili = resolve_ili(synset.id, ili_d, ili_map)
        entry = {
            'id': synset.id,
            'ili': ili,
            'partOfSpeech': POS_MAP.get(synset.part_of_speech, 'n'),
            'relations': build_synset_relations(synset.id, rel_dicts),
        }
        if synset.definition:
            entry['definitions'] = [{'text': synset.definition}]
        synsets.append(entry)
        progress(i, len(all_synsets), 'synsets')

    return {
        'lmf_version': '1.1',
        'lexicons': [{
            'id': 'ruwn',
            'label': 'RuWordNet',
            'language': 'ru',
            'email': 'bagrat@stokhastik.net',
            'url': 'https://github.com/bagratte/russian-wordnet',
            'license': 'https://creativecommons.org/licenses/by/4.0/',
            'version': '1.0',
            'entries': entries,
            'synsets': synsets,
        }],
    }


print('Loading RuWordNet...')
ruwn = ruwordnet.RuWordNet()
print('Building ILI map from omw-en:1.4...')
ili_map, wn_proper = build_ili_map()
resource = build_lmf(ruwn, ili_map, wn_proper)

print('Writing russian-wordnet-1.0.xml...')
lmf.dump(resource, 'russian-wordnet-1.0.xml')
print('Done.')
