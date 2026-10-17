"""Name tables in scenario/common.snr: officers, provinces, tactics, tea ware.

Every name has a hiragana reading next to it. English names are romanized from
those readings (romaji(); Hepburn without macrons) and kept in tl/names_*.json
(English only, keyed by record id). Japanese layout of the records:

  officers   700 x 0x44 from 0x864: +4 surname[9], +0xD given[9],
             +0x16 surname reading[17], +0x27 given reading[17], stats from +0x38
  provinces   52 x 0x1C from 0xC258: name[5], reading[11], data from +0x10
  tactics     44 x 0x28 from 0x188:  name[9], reading[17], data from +0x1A
  teaware     64 x 0x2C from 0xC808: name[13], reading[29], data from +0x2A

English names don't need readings, so they take the reading space too
(tools/patch_arm9.py points the getters at the new places):
  officers: surname -> +0x16, given name -> +0x27 (16 chars each); the old
            fields keep a truncated copy; the full reading format is emptied
  others:   the name runs on through the reading field; the reading getter
            points at the field's last byte (always NUL), so no junk shows
"""
import json, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TL = os.path.join(ROOT, 'tl')
SCRIPT = os.path.join(ROOT, 'script')

# kind: (first record, count, stride, jp name fields, jp reading fields,
#        English fields, truncated copies of the English fields)
TABLES = {
    'officers': (0x864, 700, 0x44, [(4, 9), (0xD, 9)], [(0x16, 17), (0x27, 17)],
                 [(0x16, 17), (0x27, 17)], [(4, 9), (0xD, 9)]),
    'provinces': (0xC258, 52, 0x1C, [(0, 5)], [(5, 11)], [(0, 16)], []),
    'tactics': (0x188, 44, 0x28, [(0, 9)], [(9, 17)], [(0, 26)], []),
    'teaware': (0xC808, 64, 0x2C, [(0, 13)], [(13, 29)], [(0, 42)], []),
}

def _field(b):
    return b.split(b'\0')[0].decode('cp932', 'replace')

def records(data, kind):
    """[(id, [names...], [readings...])] from a clean common.snr."""
    base, n, stride, names, reads = TABLES[kind][:5]
    out = []
    for i in range(n):
        o = base + i * stride
        out.append((i, [_field(data[o + a:o + a + s]) for a, s in names],
                    [_field(data[o + a:o + a + s]) for a, s in reads]))
    return out

KANA = {
    'きゃ': 'kya', 'きゅ': 'kyu', 'きょ': 'kyo', 'しゃ': 'sha', 'しゅ': 'shu', 'しょ': 'sho',
    'ちゃ': 'cha', 'ちゅ': 'chu', 'ちょ': 'cho', 'にゃ': 'nya', 'にゅ': 'nyu', 'にょ': 'nyo',
    'ひゃ': 'hya', 'ひゅ': 'hyu', 'ひょ': 'hyo', 'みゃ': 'mya', 'みゅ': 'myu', 'みょ': 'myo',
    'りゃ': 'rya', 'りゅ': 'ryu', 'りょ': 'ryo', 'ぎゃ': 'gya', 'ぎゅ': 'gyu', 'ぎょ': 'gyo',
    'じゃ': 'ja', 'じゅ': 'ju', 'じょ': 'jo', 'ぢゃ': 'ja', 'ぢゅ': 'ju', 'ぢょ': 'jo',
    'びゃ': 'bya', 'びゅ': 'byu', 'びょ': 'byo', 'ぴゃ': 'pya', 'ぴゅ': 'pyu', 'ぴょ': 'pyo',
    'あ': 'a', 'い': 'i', 'う': 'u', 'え': 'e', 'お': 'o',
    'か': 'ka', 'き': 'ki', 'く': 'ku', 'け': 'ke', 'こ': 'ko',
    'さ': 'sa', 'し': 'shi', 'す': 'su', 'せ': 'se', 'そ': 'so',
    'た': 'ta', 'ち': 'chi', 'つ': 'tsu', 'て': 'te', 'と': 'to',
    'な': 'na', 'に': 'ni', 'ぬ': 'nu', 'ね': 'ne', 'の': 'no',
    'は': 'ha', 'ひ': 'hi', 'ふ': 'fu', 'へ': 'he', 'ほ': 'ho',
    'ま': 'ma', 'み': 'mi', 'む': 'mu', 'め': 'me', 'も': 'mo',
    'や': 'ya', 'ゆ': 'yu', 'よ': 'yo', 'ら': 'ra', 'り': 'ri', 'る': 'ru', 'れ': 're', 'ろ': 'ro',
    'わ': 'wa', 'ゐ': 'i', 'ゑ': 'e', 'を': 'o', 'ん': 'n',
    'が': 'ga', 'ぎ': 'gi', 'ぐ': 'gu', 'げ': 'ge', 'ご': 'go',
    'ざ': 'za', 'じ': 'ji', 'ず': 'zu', 'ぜ': 'ze', 'ぞ': 'zo',
    'だ': 'da', 'ぢ': 'ji', 'づ': 'zu', 'で': 'de', 'ど': 'do',
    'ば': 'ba', 'び': 'bi', 'ぶ': 'bu', 'べ': 'be', 'ぼ': 'bo',
    'ぱ': 'pa', 'ぴ': 'pi', 'ぷ': 'pu', 'ぺ': 'pe', 'ぽ': 'po',
    'ぁ': 'a', 'ぃ': 'i', 'ぅ': 'u', 'ぇ': 'e', 'ぉ': 'o', 'ー': '',
}

def romaji(kana):
    """Hepburn romanization of a hiragana reading, long vowels written short
    (ou/oo -> o, uu -> u), as in common English usage (Hojo Ujiyasu)."""
    kana = re.sub('[ァ-ヶ]', lambda m: chr(ord(m.group()) - 0x60), kana)   # katakana -> hiragana
    out, i = '', 0
    while i < len(kana):
        if kana[i] == 'っ' and i + 1 < len(kana):
            nxt = KANA.get(kana[i + 1:i + 3]) or KANA.get(kana[i + 1], '')
            out += 't' if nxt.startswith('ch') else nxt[:1]
            i += 1; continue
        two = KANA.get(kana[i:i + 2])
        if two:
            out += two; i += 2; continue
        out += KANA.get(kana[i], kana[i]); i += 1
    out = re.sub('ou(?![aiueo])|oo', 'o', out)          # but Inoue, Sakanoue
    out = re.sub('uu', 'u', out)
    out = re.sub("n(?=[aiueoy])", "n", out)
    return out.capitalize() if out else out

def load_tl(kind):
    path = os.path.join(TL, 'names_%s.json' % kind)
    return {r['id']: r for r in json.load(open(path, encoding='utf-8'))} if os.path.exists(path) else {}

def export(data):
    """script/names_<kind>.json: jp names and readings next to the English."""
    for kind in TABLES:
        tl = load_tl(kind)
        rows = []
        for i, names, reads in records(data, kind):
            r = {'id': i, 'jp': names, 'reading': reads}
            r.update({k: v for k, v in tl.get(i, {}).items() if k != 'id'})
            rows.append(r)
        json.dump(rows, open(os.path.join(SCRIPT, 'names_%s.json' % kind), 'w', encoding='utf-8'),
                  ensure_ascii=False, indent=1)

def encode(s):
    return s.encode('cp932')

def apply(data):
    """Return common.snr with English names from tl/names_*.json written in."""
    data = bytearray(data)
    for kind, (base, n, stride, names, reads, fields, copies) in TABLES.items():
        tl = load_tl(kind)
        lo = min(a for a, _ in names + reads)
        hi = max(a + size for a, size in names + reads)
        for i in range(n):
            if i not in tl:
                continue
            o = base + i * stride
            en = tl[i]['en']
            en = en if isinstance(en, list) else [en]
            data[o + lo:o + hi] = bytes(hi - lo)
            for k, (a, size) in enumerate(fields):
                b = encode(en[k])
                if len(b) >= size:
                    raise ValueError('%s %d: %r is %d bytes, room %d' % (kind, i, en[k], len(b), size - 1))
                data[o + a:o + a + len(b)] = b
            for k, (a, size) in enumerate(copies):
                b = encode(en[k])[:size - 1]
                data[o + a:o + a + len(b)] = b
    return bytes(data)
