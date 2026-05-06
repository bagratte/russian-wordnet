#!/usr/bin/env python3

import sys
from collections import defaultdict

import ruwordnet
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


def build_synset_relations(synset):
    seen = set()
    rels = []
    for attr, rel_type in SYNSET_RELATIONS:
        for target in getattr(synset, attr):
            key = (target.id, rel_type)
            if key not in seen:
                seen.add(key)
                rels.append({'target': target.id, 'relType': rel_type})
    return rels


def build_lmf(ruwn):
    # One LexicalEntry per unique lemma; each Sense within it points at a synset
    all_senses = ruwn.senses
    print(f'Building entries from {len(all_senses)} senses...')
    lemma_to_senses = defaultdict(list)
    for i, sense in enumerate(all_senses, 1):
        if sense.lemma and sense.synset_id:
            lemma_to_senses[sense.lemma].append(sense)
        progress(i, len(all_senses), 'senses')

    entries = []
    lemma_items = list(lemma_to_senses.items())
    print(f'Building {len(lemma_items)} lexical entries...')
    for i, (lemma, senses) in enumerate(lemma_items, 1):
        pos = 'n'
        for s in senses:
            if s.synset and s.synset.part_of_speech in POS_MAP:
                pos = POS_MAP[s.synset.part_of_speech]
                break
        entries.append({
            'id': f'ruwn-le-{i}',
            'lemma': {'writtenForm': lemma, 'partOfSpeech': pos},
            'senses': [{'id': s.id, 'synset': s.synset_id} for s in senses],
        })
        progress(i, len(lemma_items), 'entries')

    all_synsets = ruwn.synsets
    print(f'Building {len(all_synsets)} synsets...')
    synsets = []
    for i, synset in enumerate(all_synsets, 1):
        # Use PWN synset ID as ILI when available, otherwise mark as not-yet-assigned
        ili = synset.ili[0].id if synset.ili else 'in'
        entry = {
            'id': synset.id,
            'ili': ili,
            'partOfSpeech': POS_MAP.get(synset.part_of_speech, 'n'),
            'relations': build_synset_relations(synset),
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
            'version': '2021',
            'entries': entries,
            'synsets': synsets,
        }],
    }


print('Loading RuWordNet...')
ruwn = ruwordnet.RuWordNet()
resource = build_lmf(ruwn)

print('Writing russian-wordnet-2021.xml...')
lmf.dump(resource, 'russian-wordnet-2021.xml')
print('Done.')
