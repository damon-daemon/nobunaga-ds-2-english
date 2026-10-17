"""Print officer bios (msgsec10-15) with the officer's English name, for translating.
usage: bios.py first_officer_id count"""
import json, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
names = {r['id']: ' '.join(r['en']) for r in json.load(open(os.path.join(ROOT, 'tl', 'names_officers.json')))}
rows = []
for n in range(10, 16):
    rows += [(n, r) for r in json.load(open(os.path.join(ROOT, 'script', 'msgsec%02d.json' % n), encoding='utf-8'))]
a, k = int(sys.argv[1]), int(sys.argv[2])
for oid in range(a, min(a + k, 700)):
    n, r = rows[oid + 1]
    print('%d %s msgsec%02d@%d %s' % (oid, names[oid], n, r['id'],
          r['jp'].replace('\n', '').replace('{05}{05}{05}', '').replace('{1B}K', '').replace('{1B}H', '')))
