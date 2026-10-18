"""Translation helper: validate, auto-wrap and apply English lines.

Batch file format (one block per entry, blank lines ignored):

    @<id>
    English text, possibly over several physical lines (joined with spaces).
    \\_ is a literal space (for centring padding that line stripping would eat).
    {uXXXX} stands for a private-use character (icons, odd jump args) as `show` prints it.
    Use \\n for a forced line break and || for an explicit break that must be kept.
    A block containing just '=' copies the Japanese verbatim (entries with no text).

usage:
    tl.py apply  msgsecNN batch.txt   # validate + wrap + write 'en' into script/msgsecNN.json
    tl.py show   msgsecNN [from] [to] # print jp entries (codes visible) for translating
    tl.py stats                       # progress per file
    tl.py autofill msgsecNN           # copy entries with no visible text verbatim

Rules checked for every entry (see font-and-text-engine memory):
  * structural codes (anything {XX} except inline ones) appear in the same order
  * inline variables {02}{xx}ﾈ: same multiset per variant; speech inserts {01}C..{00}: a subset
  * same number of variants ({05}{05}{05} separators)
  * text encodes to cp932 and uses no full-width Latin/digits
  * wrapped lines fit the widest original line of that variant
"""
import collections, json, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(__file__))
import font6x12, patch_arm9, script

# {02}<var>[attr]<field>: inserted name (01-0D: clan, officer, province, item...;
# attr '#'/'(' follows a link, e.g. {02}{09}#d = the province owner's clan name),
# {02}{11}-{14}: numbers, {02}": the player's clan
VAR = r'\{02\}(?:\{0[1-9A-F]\}[#(]?[!-z|~]|\{1[1-4]\}|")'      # field: d name, e, f, & loyalty...
SPEECH = r'\{01\}C(?:\{[0-9A-F]{2}\}|[^{])\{00\}'   # inserts msgsec00 entry (speaker's pronoun/ending)
INLINE = re.compile(r'%s|%s|\{1B\}C\d|\{1B\}[KH]' % (VAR, SPEECH))
CODE = re.compile(r'\{[0-9A-F]{2}\}')
GAIJI = re.compile(r'\{F[A-C]\}(?:\{[0-9A-F]{2}\}|[^{])')   # custom kanji: text, not a code
END = '{05}{05}{05}'
NAME_PX = 44                      # assumed width of an inserted name/variable
OFFICER_PX = 70                   # ...of an officer's full name ({02}{05}d..{02}{08}d)
OFFICER_VAR = r'\{02\}\{0[5-8]\}d'
SINGLE_LINE_PX = 200              # allowed width for one-line prompts
FLOW_PX = 600                     # wider jp lines are engine-wrapped paragraphs

def load_widths():
    path = os.path.join(ROOT, 'build', 'arm9_stock.bin')
    if not os.path.exists(path):
        import ndspy.rom
        rom = ndspy.rom.NintendoDSRom.fromFile(os.path.join(ROOT, 'nobunaga_ds_2.nds'))
        data = bytes(rom.loadArm9().sections[0].data)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, 'wb').write(data)
    a = open(path, 'rb').read()
    game = {ch: a[patch_arm9.HW_GLYPHS - 0x02000000 + i * 9:][:9] for i, ch in enumerate(font6x12.GAME_GLYPHS)}
    return font6x12.table(game)[1]

W = None

def px(text):
    """Display width of one line (codes removed, variables counted as NAME_PX)."""
    global W
    if W is None:
        W = load_widths()
    text = GAIJI.sub('漢', text)
    text = re.sub(SPEECH, '', text)          # speech inserts: mostly empty in English
    text = re.sub(OFFICER_VAR, '\1', text)               # officer full names are wide
    text = re.sub(VAR, '\0', text)
    text = text.replace('%s', '\0')                   # printf names (city/ruler) count as a name
    text = re.sub(r'\{02\}(?:\{[0-9A-F]{2}\}|[!-~])', '\0', text)   # bare variables ({02}( {02}- ...)
    text = INLINE.sub('', text)
    total = 0
    for ch in CODE.sub('', text):
        if ch == '\0':
            total += NAME_PX
        elif ch == '\1':
            total += OFFICER_PX
        elif ' ' <= ch <= '\x7f':
            total += W[ord(ch) - 0x20]
        else:
            total += 12
    return total

def codes_outside_inline(s):
    """Structural codes in order; {02} keeps its id byte (variables/args like {02}( {02}e)."""
    masked = INLINE.sub(lambda m: '#' * len(m.group()), GAIJI.sub('漢', s))
    arg = r'(?:\{[0-9A-F]{2}\}|[^{])'
    # {01}J<entry><table>: jump to another message; its args may look like kana
    return re.findall(r'\{01\}J%s%s|\{02\}%s?|\{[0-9A-F]{2}\}' % (arg, arg, arg), masked)

KANA = re.compile(r'\{1B\}[KH]')

_EMPTY = None

def EMPTY_INSERTS():
    """msgsec00 entries whose English is empty (verb endings, particles)."""
    global _EMPTY
    if _EMPTY is None:
        rows = json.load(open(os.path.join(ROOT, 'script', 'msgsec00.json'), encoding='utf-8'))
        _EMPTY = {r['id'] for r in rows
                  if not any(split_header(j, e)[2].strip()
                             for j, e in zip(r['jp'].split(END), r['en'].split(END)))}
    return _EMPTY

def split_header(jp_v, en_v):
    """(header, jp rest, en rest): a condition header copied verbatim is compared as
    a whole, so its operands ({02}{06} before English text) never look like names."""
    h = header(jp_v)
    if h and en_v.startswith(h):
        return h, jp_v[len(h):], en_v[len(h):]
    return '', jp_v, en_v

def check(jp, en):
    errs = []
    jv, ev = jp.split(END), en.split(END)
    if len(jv) != len(ev):
        errs.append('variant count %d != %d' % (len(jv), len(ev)))
    else:
        for i, (a, b) in enumerate(zip(jv, ev)):
            h, a, b = split_header(a, b)
            # half-width-kana mode toggles mean nothing in English: compare without them
            ca = [c for c in codes_outside_inline(a) if not KANA.fullmatch(c)]
            cb = [c for c in codes_outside_inline(b) if not KANA.fullmatch(c)]
            if ca != cb:
                errs.append('variant %d structural codes differ:\n   jp %s\n   en %s' % (i, ''.join(ca), ''.join(cb)))
            if sorted(re.findall(VAR, a)) != sorted(re.findall(VAR, b)):
                errs.append('variant %d inserts differ: %s vs %s' % (i, re.findall(VAR, a), re.findall(VAR, b)))
            # speech inserts may be dropped (e.g. "I" in object position written as "me"),
            # but never added
            extra = collections.Counter(re.findall(SPEECH, b)) - collections.Counter(re.findall(SPEECH, a))
            if extra:
                errs.append('variant %d speech inserts not in jp: %s' % (i, list(extra.elements())))
    for m in re.finditer(SPEECH, en):
        arg = m.group()[5:-4]
        k = int(arg[1:3], 16) if arg.startswith('{') else ord(arg)
        if k in EMPTY_INSERTS():
            errs.append('speech insert %s is empty in English (msgsec00@%d): write the words instead' % (m.group(), k))
    for tok in ('%s', '%d', '%u', 'number1', 'number2', 'number3'):
        if jp.count(tok) != en.count(tok):
            errs.append('placeholder %r count %d != %d' % (tok, jp.count(tok), en.count(tok)))
    if re.search('[０-９Ａ-Ｚａ-ｚ]', ''.join(script.JUMP.split(en)[::2])):
        errs.append('full-width Latin/digits in English')
    try:
        script.encode(en)
    except Exception as e:
        errs.append('encode: %s' % e)
    return errs

TAB_STOPS = (84, 150)               # px columns for \t (two- and three-column lists)

def expand_tab(line):
    """Replace each tab with 2px spaces up to the next TAB_STOPS column."""
    while '\t' in line:
        a, b = line.split('\t', 1)
        stop = next((t for t in TAB_STOPS if t > px(a)), px(a) + 2)
        while px(a) < stop:
            a += ' '
        line = a + b
    return line

def header(jp_v):
    """Leading command/condition run of a variant ({01}/{04}-{07} commands and their
    ASCII args) that has no visible width; '' if the variant starts with text.

    Condition operands look like display variables ({01}I{02}{11}{04}>1{02}{05}dﾗ...):
    a variable that ends the run without an operator before it is visible text."""
    h = re.match(r'(?:\{[0-9A-F]{2}\}|[ -~])*', jp_v).group()
    m = re.search(r'(%s)$' % VAR, h)
    if m and not re.search(r'\{0[346]\}(?:\{[0-9A-F]{2}\}|.)$', h[:m.start()]):
        h = h[:m.start()]
    cmds = re.sub(r'\{02\}(?:\{[0-9A-F]{2}\}|.)', '', h)
    return h if re.search(r'\{0[14-7]\}', cmds) else ''

def file_floor(rows):
    """75th percentile of multi-line jp line widths in a file: the usual box width.
    Writers often broke lines early, so one entry's own lines underestimate the box."""
    ws = []
    for r in rows:
        for v in r['jp'].split(END):
            if '\n' in v:
                ws += [px(l.rstrip('\u3000 ')) for l in v[len(header(v)):].split('\n')]
    ws.sort()
    return ws[len(ws) * 3 // 4] if ws else 0

FLOOR = 0
# Per-file cap on the wrap width (px), measured in-game; the engine re-wraps
# anything wider mid-word.
BOX_PX = {'msgsec01': 210, 'msgsec07': 210, 'msgsec08': 210, 'msgsec09': 210,
          **{'msgsec%02d' % n: 214 for n in range(10, 17)}}   # 4-line bio/item box   # top-screen description frame: text x 21..~233
CAP = None
NARRATION_PX = {f: 192 for f in ('msgsec02', 'msgsec03', 'msgsec04', 'msgsec05', 'msgsec06')}
NARROW = None
FACE_PX = 150                     # speaker box with a face portrait (measured in-game)
# Files whose speech box has a fixed size whatever the jp line breaks: every
# entry (bar indented tables) is reflowed to this width, up to 3 lines (measured in-game)
SPEECH_PX = {'msgsec17': 196, 'msgsec18': 196}
BOX = None

# Clash of Warlords battle talk: 2-line speaker boxes with a face, ~150px of text.
# BATTLE_NARRATION ids are the stage briefings shown in the 3-line narration box (192px).
BATTLE_IDS = {'msgsec19': range(36, 179), **{'msgsec%02d' % n: range(10 ** 4) for n in range(20, 25)}}
BATTLE_NARRATION = {'msgsec19': {51, 52, 80, 81, 106, 107, 132, 133, 165, 166},
                    'msgsec20': {14, 15, 44, 45, 71, 72, 98, 99, 125, 126},
                    'msgsec21': {13, 14, 16, 46, 47, 79, 80, 108, 109, 137, 138},
                    'msgsec22': {13, 14, 42, 43, 72, 73, 74, 102, 103, 104, 105, 130, 131},
                    'msgsec23': {14, 15, 46, 47, 75, 76, 105, 106, 138, 139},
                    'msgsec24': {15, 16, 47, 48, 78, 79, 105, 106, 108, 137, 138}}
BATTLE_PX, BATTLE_LINES = 150, 2
BATTLE = None
NARR_IDS = set()
CUR_ID = None

def is_table(jp_v):
    """Indented / many-line entries are tables shown in a bigger window."""
    lines = jp_v.split('\n')
    return len(lines) > 3 or any(l.startswith('\u3000') for l in lines)

def wrap_variant(jp_v, en_v):
    """Word-wrap en_v to the widest line of jp_v (at least the file's FLOOR)."""
    h = header(jp_v)
    if not en_v.startswith(h):
        h = ''
    jp_v, en_v = jp_v[len(h):], en_v[len(h):]
    jp_lines = jp_v.split('\n')
    # trailing full-width spaces only pad over old text; they are not box width
    # (a line that also starts with full-width spaces is centred: its padding is box width)
    limit = max([FLOOR] + [px(l if l.startswith('\u3000') else l.rstrip('\u3000 ')) for l in jp_lines])
    if CAP and limit <= FLOW_PX:
        limit = min(limit, CAP)
    # 3-line entries are shown in the faceless narration/system box, which is
    # wider than the 2-line speaker box the Japanese line breaks suggest
    if NARROW and len(jp_lines) >= 3 and limit < NARROW:
        limit = NARROW
    if BATTLE and CUR_ID in BATTLE and not is_table(jp_v):
        if CUR_ID not in NARR_IDS:
            limit = BATTLE_PX
            en_v = re.sub(' *\n *', ' ', en_v)
            jp_v = jp_v + '\n'
        else:
            limit = NARRATION_PX['msgsec02']
    if BOX and not is_table(jp_v):
        limit = BOX
        en_v = re.sub(' *\n *', ' ', en_v)
        jp_v = jp_v + '\n'                # (wrapped below, never 'single-line')
    if limit > FLOW_PX:                   # paragraphs far wider than any box (bios): the
        return h + en_v, 10 ** 6, 1, 1     # game flows them itself, leave them alone
    if '\n' not in jp_v:                  # single-line prompts are never wrapped;
        return h + en_v, max(limit, SINGLE_LINE_PX), 1, 1   # their bars are wider than the jp text
    # short (<= 2-line) speaker-box entries: reflow as one paragraph so the
    # wrap uses both lines fully (manual breaks often wasted a third line)
    if NARROW and len(jp_lines) <= 2 and '\u3000' not in jp_v + en_v:
        # the engine word-wraps at the real box edge (patch_arm9 draw_wrap), and these
        # entries show in boxes of different widths (narration 192px, speaker with face
        # ~150px): leave them as one paragraph; count lines at the narrowest box
        en_v = re.sub(' *\n *', ' ', en_v)
        n, line = 1, ''
        for word in en_v.split(' '):
            if line and px(line + ' ' + word) > FACE_PX:
                n += 1; line = word
            else:
                line = (line + ' ' + word).strip()
        return h + en_v, 10 ** 6, n, len(jp_lines)
    out = []
    for para in en_v.split('\n'):
        # a paragraph's leading full-width spaces (description bodies are indented
        # one) are repeated on each of its wrapped lines
        indent = para[:len(para) - len(para.lstrip('\u3000'))]
        line = ''
        for word in re.split(r'(?<= )', para):
            if line.strip('\u3000') and px(line + word.rstrip(' ')) > limit:
                out.append(line.rstrip(' ')); line = indent + word
            else:
                line += word
        out.append(line.rstrip(' '))
    out = [expand_tab(l) for l in out]
    return h + '\n'.join(out), limit, len(out), len(jp_lines)

def prepare(jp, en):
    """Apply wrapping per variant; return (text, warnings)."""
    warns = []
    jv, ev = jp.split(END), en.split(END)
    if len(jv) != len(ev):
        return en, warns
    res = []
    for i, (a, b) in enumerate(zip(jv, ev)):
        b = b.replace('{1B}K{1B}H', '')            # kana toggles: dropped in English
        b2, limit, n_en, n_jp = wrap_variant(a, b)
        h = header(a) if b2.startswith(header(a)) else ''
        widest = max(px(l) for l in b2[len(h):].split('\n'))
        if widest > limit:
            warns.append('variant %d: line %dpx > box %dpx' % (i, widest, limit))
        reflowed = BOX and not is_table(a[len(header(a)):])
        battle = BATTLE and CUR_ID in BATTLE and not is_table(a[len(header(a)):])
        if battle and n_en > (3 if CUR_ID in NARR_IDS else BATTLE_LINES):
            warns.append('variant %d: %d lines (battle box)' % (i, n_en))
        elif battle:
            pass
        elif reflowed and n_en > 3 or not reflowed and n_en > max(n_jp, 3 if n_jp > 1 and not NARROW else 1):
            warns.append('variant %d: %d lines (jp %d)' % (i, n_en, n_jp))
        res.append(b2)
    return END.join(res), warns

def parse_batch(path):
    blocks, cur, buf = {}, None, []
    for raw in open(path, encoding='utf-8'):
        line = raw.rstrip('\n')
        m = re.fullmatch(r'@(\d+)\s*', line)
        if m:
            if cur is not None:
                blocks[cur] = buf
            cur, buf = int(m.group(1)), []
        elif cur is not None and line.strip():
            buf.append(line.strip())
    if cur is not None:
        blocks[cur] = buf
    return {k: re.sub(r'\{u([0-9A-F]{4})\}', lambda m: chr(int(m.group(1), 16)),   # {uE06E}: PUA char
                      ' '.join(v)).replace(' || ', '\n').replace('||', '\n').replace('\\n ', '\n').replace('\\n', '\n').replace('\\t', '\t').replace('\\_', ' ')
            for k, v in blocks.items()}

# Entries the game strcpy's into fixed stack buffers with no length check (bytes, NUL excluded).
# 0x020B1960 passes a 32-byte buffer to 0x020B41C4/0x020B436C/0x020B44C0 (unit formation
# warnings); the other warning copiers get 64-byte buffers. Overflow smashes saved registers.
BYTE_LIMIT = {'msgsec04': {**{i: 31 for i in range(276, 290)},
                           **{i: 63 for i in (232, 233, *range(261, 276), 291, 293, 296, 297, 298)}}}

def apply(name, batch):
    path = os.path.join(ROOT, 'script', name + '.json')
    rows = json.load(open(path, encoding='utf-8'))
    global FLOOR, CAP
    FLOOR = file_floor(rows)
    CAP = BOX_PX.get(name)
    global NARROW, BOX
    NARROW = NARRATION_PX.get(name)
    BOX = SPEECH_PX.get(name)
    global BATTLE, CUR_ID
    BATTLE = BATTLE_IDS.get(name)
    global NARR_IDS
    NARR_IDS = BATTLE_NARRATION.get(name, set())
    blocks = parse_batch(batch)
    bad = 0
    for i, en in blocks.items():
        jp = rows[i]['jp']
        CUR_ID = i
        if en == '=':                            # no visible text: copy verbatim
            rows[i]['en'] = jp; continue
        # speech insert with id 0x0A ({01}C<newline>{00}) must not look like a line break
        jp = jp.replace('{01}C\n{00}', '{01}C{0A}{00}')
        jp = re.sub(r'\{01\}J\n', '{01}J{0A}', jp)    # jump to entry 0x0A
        jp = jp.replace('{02}\n', '{02}{0A}')            # variable 0x0A
        text, warns = prepare(jp, en)
        errs = check(jp, text)
        limit = BYTE_LIMIT.get(name, {}).get(i)
        if limit is not None:
            n = len(script.encode(text.split(END)[0]))
            if n > limit:
                errs.append('%d bytes > %d (copied into a fixed buffer)' % (n, limit))
        for e in errs:
            print('%s@%d ERROR %s' % (name, i, e)); bad += 1
        for w in warns:
            print('%s@%d warn  %s' % (name, i, w))
        if not errs:
            rows[i]['en'] = text
    json.dump(rows, open(path, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    # size check: offsets are 16-bit (script.pack raises past 64 KiB)
    script.build(os.path.join(ROOT, 'script'), name + '.dat')
    done = sum(1 for r in rows if r['en'])
    print('%s: applied %d, errors %d, translated %d/%d' % (name, len(blocks) - bad, bad, done, len(rows)))

def invisible(jp):
    """True if an entry has no visible text (only jumps, conditions and other codes)."""
    t = re.sub(r'\{01\}J(?:\{[0-9A-F]{2}\}|.)(?:\{[0-9A-F]{2}\}|.)', '', jp)
    t = CODE.sub('', t)
    return not re.search(r'[^\x00-\x7f]', t)

def autofill(name):
    """Copy entries with no visible text verbatim into 'en'."""
    path = os.path.join(ROOT, 'script', name + '.json')
    rows = json.load(open(path, encoding='utf-8'))
    n = 0
    for r in rows:
        if not r['en'] and invisible(r['jp']):
            r['en'] = r['jp']; n += 1
    json.dump(rows, open(path, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('%s: autofilled %d entries with no visible text' % (name, n))

def show(name, a=0, b=None):
    rows = json.load(open(os.path.join(ROOT, 'script', name + '.json'), encoding='utf-8'))
    for r in rows[a:b]:
        jp = re.sub('[\ue000-\uf8ff]', lambda m: '{u%04X}' % ord(m.group()), r['jp'])
        print('@%d%s %s' % (r['id'], ' [done]' if r['en'] else '', jp.replace('\n', '⏎')))

def stats():
    tot = done = 0
    for f in sorted(os.listdir(os.path.join(ROOT, 'script'))):
        if f.startswith('msgsec'):
            rows = json.load(open(os.path.join(ROOT, 'script', f), encoding='utf-8'))
            d = sum(1 for r in rows if r['en']); tot += len(rows); done += d
            if rows: print('%s %d/%d' % (f[:-5], d, len(rows)))
    print('total %d/%d' % (done, tot))

if __name__ == '__main__':
    cmd = sys.argv[1]
    if cmd == 'apply':
        apply(sys.argv[2], sys.argv[3])
    elif cmd == 'show':
        show(sys.argv[2], *(int(x) for x in sys.argv[3:5]))
    elif cmd == 'stats':
        stats()
    elif cmd == 'autofill':
        autofill(sys.argv[2])
