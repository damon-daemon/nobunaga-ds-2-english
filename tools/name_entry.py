"""English name entry (arm9 patch, called from patch_arm9.apply).

The stock name entry (NameEntry::Run 0x021406D8: this, dest, max chars, mode) has five
modes: 0/1 officer surname/given (kanji: pick a kana, then a kanji from 0x0219D058),
2/3 their readings (kana typed straight from the scrolling grid table 0x0219CF71,
11 cells of 2 bytes per row), 4 Clash army name (kanji, own screen BG 82). The
buffer (+0xAC, 15 bytes) holds 2-byte characters, +0x80 = count, +0xA0 = cursor.

English: every mode types straight from the grid (reading-screen layout, BG 16),
whose cells now hold letters ("A " = letter + pad byte), and the buffer holds one
byte per letter: insert/delete/draw/commit index by bytes, slots are drawn 7px
apart, and the limits double (names 8 letters, 12 for surname + given; readings
14 / 24; army name 8). The 9- and 15-byte destination buffers are unchanged.
The kanji tables and the mode-0/1/4 layouts are left unused.
"""
import struct

STRLEN = 0x0206A758
GRID = 0x0219CF71                 # 10 rows x (11 cells x 2 bytes + NUL)
GRID_ROW = 0x17
BLANK = '　'                  # empty cell (the code skips cells equal to it)

ROWS = ['ABCDE', 'abcde', 'FGHIJ', 'fghij', 'KLMNO', 'klmno', 'PQRST', 'pqrst', 'UVWXY', 'uvwxy',
        "Z-'.&", 'z!?12', '34567', '890  ']


def grid_bytes():
    """7 rows of 5 + gap + 5 cells (the grid shows 4 rows and scrolls), 3 blank rows."""
    rows = [ROWS[i] + ' ' + ROWS[i + 1] for i in range(0, len(ROWS), 2)]
    out = b''
    for r in rows + [''] * (10 - len(rows)):
        r = r.ljust(11)
        cells = [BLANK.encode('cp932') if c == ' ' else (c + ' ').encode('ascii') for c in r]
        out += b''.join(cells) + b'\0'
    assert len(out) == 10 * GRID_ROW
    return out, len(rows)


# (address, stock instruction, new instruction)
EDITS = [
    # all modes type straight from the grid: IsDirect() (0x021419F4) always true
    (0x02141A04, 'movne r0, #0', 'mov r0, r0'),
    (0x02141600, 'movne r5, #0x52', 'movne r5, #0x10'),         # army name: reading screen BG 16, not BG 82
    # one byte per letter
    (0x02141234, 'lsl r2, r2, #1', 'mov r2, r2'),               # commit: copy count bytes
    (0x02142730, 'add r1, r4, r1, lsl #1', 'add r1, r4, r1'),   # insert: buf[cursor] = letter
    (0x02142760, 'strb r2, [r0, #0xad]', 'mov r0, r0'),         #   (no second byte)
    (0x0214282C, 'add r0, r4, r0, lsl #1', 'add r0, r4, r0'),   # delete
    (0x02142840, 'strb r2, [r1, #0xad]', 'mov r0, r0'),
    (0x02142900, 'add r3, sl, r8, lsl #1', 'add r3, sl, r8'),   # draw slot i: [buf[i], 0]
    (0x02142914, 'ldrsb ip, [r3, #0xad]', 'mov ip, #0'),
    (0x02142944, 'add sb, sb, #0x13', 'add sb, sb, #7'),        #   7px apart
    (0x02142EDC, 'add r2, ip, #0xe', 'add r2, ip, #0x11'),      # grid letters nearer the cell centre
    # field labels: mode 1/3 "Given" (cell 0x1A, moved to the reading screen's spot), mode 4 "Army" (0x1B)
    (0x02141684, 'cmp r0, #1', 'tst r0, #1'),
    (0x02141688, 'bne 0x21416bc', 'beq 0x21416bc'),
    (0x021416B0, 'mov r2, #0x4d', 'mov r2, #0x31'),
    (0x021416C0, 'cmp r0, #3', 'cmp r0, #4'),
    # limits (callers of Run)
    (0x021459C0, 'mov r2, #4', 'mov r2, #8'),                   # surname
    (0x02145AEC, 'mov r2, #7', 'mov r2, #14'),                  # surname reading
    (0x02145B20, 'lsr r0, r0, #1', 'mov r0, r0'),               # given reading: min(14, 24 - len)
    (0x02145B24, 'rsb r1, r0, #0xc', 'rsb r1, r0, #24'),
    (0x02145B28, 'mov r0, #7', 'mov r0, #14'),
    (0x0213337C, 'mov r2, #4', 'mov r2, #8'),                   # army name (mode was r3 = r2)
    (0x02133388, 'mov r3, r2', 'mov r3, #4'),
]
GIVEN_STRLEN = 0x021459F0        # given name: max = min(8, 12 - strlen(surname)) via a helper
GIVEN_EDITS = [(0x021459F4, 'lsr r0, r0, #1', 'mov r2, r0'), (0x021459F8, 'rsb r2, r0, #6', 'mov r0, r0')]

# mode switches (addls pc, pc, rX, lsl #2): modes 0, 1, 4 take the mode-2/3 case
SWITCHES = [0x02140718, 0x02142AA4, 0x02142B4C, 0x02142BF4, 0x02142CA8, 0x02142D94, 0x02142E80, 0x02142F1C]

# slot rects of the reading layout, 19px -> 7px apart
SLOT_TOUCH = 0x02142B8C          # tap area of slot r2
SLOT_TOUCH_STOCK = '''mov r1, #0x13
mul r1, r2, r1
add r1, r1, #0x49
str r1, [r0]
mov r1, #0x12
str r1, [r0, #4]
str r1, [r0, #8]
str r1, [r0, #0xc]
bx lr'''
SLOT_TOUCH_NEW = '''rsb r1, r2, r2, lsl #3
add r1, r1, #0x4b
str r1, [r0]
mov r1, #0x12
str r1, [r0, #4]
str r1, [r0, #0xc]
mov r1, #7
str r1, [r0, #8]
bx lr'''
CURSOR = 0x02142C38              # cursor brackets (22px) round slot r2
CURSOR_STOCK = 'mov r1, #0x13\nmul r1, r2, r1\nadd r1, r1, #0x47'
CURSOR_NEW = 'rsb r1, r2, r2, lsl #3\nadd r1, r1, #0x44\nmov r0, r0'


def apply(a, asm, c):
    """Patch arm9 (patch_arm9.Arm9 a); extra code at c. Returns the new end of used space."""
    def edit(addr, old, new):
        assert a.read(addr, len(asm(old, addr))) == asm(old, addr), hex(addr)
        a.write(addr, asm(new, addr))
    for addr, old, new in EDITS + GIVEN_EDITS:
        edit(addr, old, new)
    edit(SLOT_TOUCH, SLOT_TOUCH_STOCK, SLOT_TOUCH_NEW)
    edit(CURSOR, CURSOR_STOCK, CURSOR_NEW)
    for sw in SWITCHES:
        ent = lambda m: sw + 8 + 4 * m
        target = lambda m: ent(m) + 8 + (((struct.unpack('<i', a.read(ent(m), 4))[0] & 0xFFFFFF) ^ 0x800000) - 0x800000) * 4
        assert target(2) == target(3), hex(sw)
        for m in (0, 1, 4):
            a.write(ent(m), asm('b %#x' % target(2), ent(m)))
    rows_total = 0x02140754          # reading layout: 10 rows -> as many as the grid has
    grid, n = grid_bytes()
    edit(rows_total, 'mov r0, #0xa', 'mov r0, #%d' % n)
    a.write(GRID, grid)

    helper = asm('''
        push  {lr}
        bl    %#x
        rsb   r0, r0, #12
        cmp   r0, #8
        movgt r0, #8
        pop   {pc}
    ''' % STRLEN, c)
    a.write(c, helper)
    edit(GIVEN_STRLEN, 'bl %#x' % STRLEN, 'bl %#x' % c)
    return c + len(helper)
