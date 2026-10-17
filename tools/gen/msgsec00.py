"""English for msgsec00: speech-style substitution table.

Each entry is a list of variants chosen by conditions on the speaker/listener;
dialogue inserts an entry with {01}C<id>{00}. Pronouns, forms of address and
insults get English words; Japanese verb endings and particles (17-70) become
empty because the English dialogue lines carry the meaning themselves. A
variant whose word is None keeps the Japanese (jumps, bare name variables).
"""
LORD = 'Lord {02}{06}f'
EN = {
    0: ['I'], 1: ['I'],
    2: ['Mother', 'Father', 'Monkey', None],          # how a speaker refers to themself
    3: ['we'], 4: ['my'], 5: ['my'] * 12 + ['our'],
    6: ['woman', 'man'],
    # addressing family / one's lord
    7: ['Mother', 'Father', None, 'Brother', 'Sister', None, None, 'My Liege', 'Holy Master',
        'My Lady', 'My Lord', 'My Lord', 'My Lord', LORD],
    8: ['Mother', 'Father', None, 'Brother', 'Sister', None, None, LORD],
    9: [None, None, 'Monkey', 'you', None, LORD, 'Strategist', LORD],
    10: [LORD, LORD],
    11: [None] + ['you'] * 9,
    12: [None] + ['you'] * 11,
    13: ['old fool', 'little girl', 'vixen', 'brat', 'greenhorn', 'monk', 'small fry'],
    14: ['Monkey', 'Kinkan-head', 'Old Badger', 'Viper', 'Fool'],
    15: [None] * 12 + ['you mediocrity', 'you'],
    16: [None] * 12 + ['coward', 'reckless fool', 'fool'],
    **{i: [''] for i in range(17, 71)},
    71: ['everyone', 'everyone', 'all of you', 'everyone', 'everyone', 'everyone', 'men'],
    72: ['Ohoho', 'Ufufu', 'Wahaha', 'Hohoho', 'Hahaha', 'Heh', 'Ahaha', 'Fufufu', 'Hahaha'],
    73: ['Aah!', 'Ugh!', 'Waaah!', 'Gwah!'],
    74: ['Yes', 'Yes, sir', 'Yes', 'Yes', 'Yes, sir', 'Yes', 'At once'],
    75: ['Better Cultivate results', 'More food income', 'Better-trained conscripts',
         'Less typhoon damage', 'Less damage from bad harvests', 'Better Commerce results',
         'More gold (commerce) income', 'Less epidemic damage', 'Less earthquake damage',
         'More gold from mines', 'Better Fortify results', 'Better Tea Party success',
         'Better Tech results', 'Better Tribute success', 'Better Alliance results',
         'Better Spy results', 'Better Betray results', 'Better Rumor results',
         'Better Hostility results'],
}

def apply(path):
    """Write EN into script/msgsec00.json: each variant keeps its condition header
    (tl.header) and gets the English text; None keeps the Japanese variant."""
    import json, os, sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import tl
    rows = json.load(open(path, encoding='utf-8'))
    for i, words in EN.items():
        jv = rows[i]['jp'].split(tl.END)
        assert len(words) in (1, len(jv) - 1), (i, len(words), len(jv) - 1)
        out = []
        for k, v in enumerate(jv[:-1]):           # last split part is the empty tail
            w = words[k] if k < len(words) else words[-1]
            out.append(v if w is None or tl.invisible(v) else tl.header(v).replace('{1B}K', '').replace('{1B}H', '') + w)
        rows[i]['en'] = tl.END.join(out + [jv[-1]])
    for r in rows:                                # jumps and bare variables: verbatim
        if not r['en']:
            r['en'] = r['jp']
    json.dump(rows, open(path, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
