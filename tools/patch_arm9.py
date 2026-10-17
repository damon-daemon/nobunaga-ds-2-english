"""ARM9 patches: half-width ASCII font and variable-width text.

Same Koei text engine as Sangokushi DS 3 (see that project's patch_arm9.py), but
an older build: the glyph lookup is byte-identical, while text is handled by just
two routines (SGS has three):

  layout/wrap 0x02083318  splits a string into lines (80-byte line buffer),
                          aligns each line (0x02083680) and hands it to the drawer
  drawer      0x020836CC  draws glyphs, wraps when the next char won't fit

The stock half-width glyph lookup (0x02083980) linearly searches an 18-entry
list ("0123456789-+/(),.:") and falls back to a blank glyph, so ASCII letters
render as nothing. We replace it with a direct lookup into a 96-glyph table
(ASCII 0x20-0x7F, 6x12 1bpp, 9 bytes each) stored over the full-width digit and
Latin letter glyphs, which the build converts to ASCII everywhere in the script.
"""
import os, struct, sys
from keystone import Ks, KS_ARCH_ARM, KS_MODE_ARM

sys.path.insert(0, os.path.dirname(__file__))
import font6x12, name_entry

HW_LIST = 0x02173500      # 18 half-width chars
HW_GLYPHS = 0x02178DC0    # 18 x 9-byte glyphs
FW_GLYPHS = 0x02178E64    # full-width glyphs, 18 bytes each
FW_INDEX = 0x02173514     # u16 index table for SJIS 0x8140..0x9FFF
HOOK = 0x02083980         # inside glyph-pointer lookup (0x02083970), half-width branch
HOOK_END = 0x020839CC     # stock "b FALLBACK" after the list search loop
FALLBACK = 0x020839F0     # stock "use blank glyph" path

# Variable-width font. The stock 18-glyph table (HW_GLYPHS, 162 bytes) is dead
# after HOOK and holds the width table + shared width routine; the hooks go in
# the space left after the ASCII glyph table (see apply()).
WIDTHS = HW_GLYPHS                    # 96 bytes, advance per char 0x20-0x7F
WIDTH_FN = WIDTHS + 96                # r0 = char -> r0 = advance; preserves all other regs
LAYOUT_ADVANCE = 0x020834E8           # layout: add r5, r5, #6   (char in r1)
LAYOUT_LOOKAHEAD = 0x020834F0         # layout: add r0, r1, #6   (pen r1, next char [sp, #0x18])
DRAW_ADVANCE = 0x02083820             # drawer: add r5, r5, #6   (char at [sb])
DRAW_LOOKAHEAD = 0x02083828           # drawer: add r1, r5, #6   (pen r5, next char r4; r0 live)
# Look-aheads ("does the next char fit?") assumed 6px; they now use the next
# char's real width minus its blank gap column.

# Many screens centre or right-align a label themselves from strlen(s) * 6 (or
# strlen * 12 / 2) before drawing it. Those strlen calls (STRLEN_WIDTH_SITES, all
# followed by a multiply by 6 or 12) are redirected to vwf_len(), which returns the
# real pixel width / 6 (rounded), counting SJIS as 12px like the stock maths.
STRLEN = 0x0206A758
WRAP_BREAK = 0x02083534               # layout: sub r2, sb, r4 (copy the line up to the overflow)
STRLEN_WIDTH_SITES = [
    0x02071E0C, 0x020BC964, 0x020BCA74, 0x020BCB5C, 0x020BCC8C, 0x020BCD74, 0x020BCE88,
    0x020BCF70, 0x020BD068, 0x020BD160, 0x020BD240, 0x021251F4, 0x0212526C, 0x02125428,
    0x021254A0, 0x02125690, 0x02125A74, 0x0213B838, 0x0213B95C, 0x0213BB14, 0x02150160,
    0x02150200, 0x02150278, 0x021502FC, 0x02150360, 0x021503C4, 0x02150428, 0x0215048C,
]

# Name getters (see tools/names.py): English officer names live in the reading
# fields (+0x16 surname, +0x27 given), the full name gets a space, the full
# reading is emptied; other names run on through their reading field, whose
# getter now points at the field's last byte (always NUL).
NAME_SITES = {
    0x02073E0C: ('add r3, r0, #0xd', 'add r3, r0, #0x27'),   # full name: given
    0x02073E10: ('add ip, r0, #4', 'add ip, r0, #0x16'),     # full name: surname
    0x02073E6C: ('add r2, r0, #4', 'add r2, r0, #0x16'),     # surname
    0x02073EBC: ('add r2, r0, #0xd', 'add r2, r0, #0x27'),   # given name
    0x0207E9B8: ('add r0, r0, #5', 'add r0, r0, #0xf'),      # province reading
    0x020761C4: ('add r0, r0, #0xd', 'add r0, r0, #0x29'),   # tea ware reading
}
NAME_FORMATS = {0x02191654: (b'%s%s\0', b'%s %s\0'),       # officer full name
                0x0219165C: (b'%s%s\0', b'\0'),            # officer full reading
                0x02191634: (b'%s%s\0', b'%s %s\0'),       # player-made officer full name
                0x02191644: (b'%s%s\0', b'%s %s\0')}       #   and reading (typed in English)

# Officer full names in UI lists/panels go through a wrapper around GetFullName
# (which sprintfs "surname given" into the caller's buffer). Japanese full names are
# at most ~12 bytes and several callers' buffers are sized for that, while English
# names reach 33 bytes; the overflow corrupted neighbouring locals (e.g. the Clash of
# Warlords unit formation rows' x positions). The wrapper builds the name in a
# scratch buffer, shortens it to "Surname G." when it is wider than SHORT_NAME_PX
# (list column) or longer than the site's byte limit, and copies at most that many
# bytes + NUL. Message variables ({02}..d, expanded at 0x020948E0) keep the full name.
GET_FULL_NAME = 0x02073DC8
SHORT_NAME_PX = 74
NAME_SCRATCH = 36                     # bytes: surname[16] + space + given[16] + NUL
# site -> max name bytes (excluding NUL): the caller's buffer size - 1
FULL_NAME_UI_SITES = {s: 31 for s in [
    0x0208F450, 0x0208FE44, 0x0209011C, 0x020905F0, 0x020912F0, 0x020916EC, 0x02091C48,
    0x02093170, 0x020A013C, 0x020A12F4, 0x020A181C, 0x020A80D8, 0x020ADD98, 0x020B2828,
    0x020B93E0, 0x020BF680, 0x020D0F90, 0x0212522C, 0x02125460, 0x02126014, 0x02135524,
    0x02138F40, 0x0213AC44, 0x0214B768, 0x02150158, 0x02151944]}
FULL_NAME_UI_SITES.update({
    0x02081C9C: 12,                   # 13-byte name field in a 0x30-byte record
    0x02075B38: 15,                   # caller's buffer (generic name getter), size unknown
    0x020C7A24: 15, 0x0212563C: 15,   # 16-byte stack buffers
    0x02138868: 15,                   # Clash of Warlords unit formation rows
})

# LoadMsgFile (0x02094650) refuses message files >= 26; English needs the
# overflow files msgsec26-39 (tools/msgspill.py), whose paths are in the table.
MSG_FILE_LIMIT = 0x02094654           # cmp r1, #0x1a

# Alignment (0x02083680): centred x = left + ((right - left - width) lsr 1).
# A line wider than its cell made this wrap to a huge x and the string vanished;
# clamp the slack at 0 (same fix as SGS).
ALIGN_DEFAULT_BRANCH = 0x02083698     # b 0x020836c4  (mode >= 3: return left)
ALIGN_CENTRE = 0x020836B8             # sub r0, r0, r2 / add r0, r3, r0, lsr #1 / bx lr / mov r0, r3


# Glyph space that English text never uses, handed to arm9str for relocated UI
# strings: the NEC special characters (SJIS 0x8740-0x879E: circled numbers, Roman
# numerals, unit symbols), which no message, name or UI string uses, and the
# leftover hook area after the ASCII table. Filled in by apply().
FREE = []
NEC_FIRST, NEC_LAST = 0x8740, 0x879C


class Arm9:
    def __init__(self, code):
        self.code = code
    def _sec(self, addr, n):
        for s in self.code.sections:
            if s.ramAddress <= addr and addr + n <= s.ramAddress + len(s.data):
                return s
        raise KeyError(hex(addr))
    def read(self, addr, n):
        s = self._sec(addr, n); o = addr - s.ramAddress
        return bytes(s.data[o:o + n])
    def write(self, addr, data):
        s = self._sec(addr, len(data)); o = addr - s.ramAddress
        if not isinstance(s.data, bytearray): s.data = bytearray(s.data)
        s.data[o:o + len(data)] = data


def fw_index(a, code):
    return struct.unpack('<H', a.read(FW_INDEX + (code - 0x8140) * 2, 2))[0]


def ascii_table_addr(a):
    """Start of the full-width ０ glyph; the ASCII table is written from there."""
    codes = list(range(0x824F, 0x8259)) + list(range(0x8260, 0x827A)) + list(range(0x8281, 0x829B))
    idx = [fw_index(a, c) for c in codes]
    assert idx == list(range(idx[0], idx[0] + len(idx))), 'full-width digit/Latin glyphs not contiguous'
    return FW_GLYPHS + idx[0] * 18, FW_GLYPHS + (idx[-1] + 1) * 18


def apply(code):
    a = Arm9(code)
    assert a.read(HW_LIST, 18) == font6x12.GAME_GLYPHS.encode(), 'unexpected arm9 (half-width list)'
    table_addr, area_end = ascii_table_addr(a)

    game = {ch: a.read(HW_GLYPHS + i * 9, 9) for i, ch in enumerate(font6x12.GAME_GLYPHS)}
    glyphs, widths = font6x12.table(game)
    a.write(table_addr, glyphs)

    ks = Ks(KS_ARCH_ARM, KS_MODE_ARM)
    asm = lambda src, addr: bytes(ks.asm(src, addr)[0])
    sites = {LAYOUT_ADVANCE: 'add r5, r5, #6', LAYOUT_LOOKAHEAD: 'add r0, r1, #6',
             DRAW_ADVANCE: 'add r5, r5, #6', DRAW_LOOKAHEAD: 'add r1, r5, #6',
             ALIGN_DEFAULT_BRANCH: 'b 0x020836c4', HOOK_END: 'b %#x' % FALLBACK}
    for addr, src in sites.items():
        assert a.read(addr, 4) == asm(src, addr), hex(addr)

    # width(c) = WIDTHS[c - 0x20] for c in 0x20..0x7F, else the stock 6px
    width_fn = asm('''
        str    r1, [sp, #-4]!
        sub    r0, r0, #0x20
        cmp    r0, #0x60
        movhs  r0, #6
        sublo  r1, pc, #%d
        ldrblo r0, [r1, r0]
        ldr    r1, [sp], #4
        bx     lr
    ''' % (WIDTH_FN + 0x18 - WIDTHS), WIDTH_FN)     # pc = WIDTH_FN+0x10+8
    assert len(width_fn) == 32 and WIDTH_FN + 32 <= HW_GLYPHS + 18 * 9
    a.write(WIDTHS, widths)
    a.write(WIDTH_FN, width_fn)

    hook = lambda body, addr, save: asm('push {%slr}\n%s\npop {%spc}' % (save, body, save), addr)
    w = 'bl %#x' % WIDTH_FN
    hooks = [
        # (site, body, extra saved regs); 'push {lr}' moves the caller's sp by 4
        (LAYOUT_ADVANCE, 'mov r0, r1\n%s\nadd r5, r5, r0' % w, ''),
        (LAYOUT_LOOKAHEAD, 'ldr r0, [sp, #0x1c]\n%s\nadd r0, r0, r1\nsub r0, r0, #1' % w, ''),
        (DRAW_ADVANCE, 'ldrb r0, [sb]\n%s\nadd r5, r5, r0' % w, ''),
        (DRAW_LOOKAHEAD, 'mov r0, r4\n%s\nadd r1, r5, r0\nsub r1, r1, #1' % w, 'r0, '),
    ]
    t = (table_addr + len(glyphs) + 3) & ~3
    for site, body, save in hooks:
        b = hook(body, t, save)
        assert t + len(b) <= area_end, 'out of hook space'
        a.write(t, b)
        a.write(site, asm('bl %#x' % t, site))
        t += len(b)

    # Extra code goes at the start of the NEC glyph block (see FREE)
    nec = sorted(i for i in (fw_index(a, c) for c in range(NEC_FIRST, NEC_LAST + 1)) if i != 0xFFFF)
    assert nec == list(range(nec[0], nec[0] + len(nec))), 'NEC glyphs not contiguous'
    nec_lo, nec_hi = FW_GLYPHS + nec[0] * 18, FW_GLYPHS + (nec[-1] + 1) * 18
    c = (nec_lo + 3) & ~3

    # vwf_px(r0 = string) -> r0 = pixel width (SJIS 12px, half-width kana 6px,
    # ASCII from WIDTHS); clobbers r1-r3, ip like strlen
    vwf_px = asm('''
        mov   r2, #0
        ldr   ip, widths
    next:
        ldrb  r1, [r0], #1
        cmp   r1, #0
        beq   done
        cmp   r1, #0x80
        blo   ascii
        cmp   r1, #0xa0
        blo   sjis
        cmp   r1, #0xe0
        addlo r2, r2, #6
        blo   next
    sjis:
        ldrb  r1, [r0], #1
        cmp   r1, #0
        beq   done
        add   r2, r2, #12
        b     next
    ascii:
        subs  r1, r1, #0x20
        ldrbhs r1, [ip, r1]
        addhs r2, r2, r1
        b     next
    done:
        mov   r0, r2
        bx    lr
    widths:
        .word %#x
    ''' % WIDTHS, c)
    vwf_px_addr = c; c += len(vwf_px)
    # vwf_len(r0 = string) -> r0 = round(pixel width / 6)
    vwf_len = asm('''
        push  {lr}
        bl    %#x
        add   r0, r0, #3
        ldr   r1, recip
        mul   r2, r0, r1
        lsr   r0, r2, #18
        pop   {pc}
    recip:
        .word 0xaaab
    ''' % vwf_px_addr, c)
    vwf_len_addr = c; c += len(vwf_len)
    # each site multiplies strlen by 6 (mov r1, #6) or by 12 then halves (mov r1, #0xc):
    # use the exact pixel width instead (the clear-rest-of-field rects start right at the
    # text's end, so a rounded width left slivers of the previous, longer text)
    for site in STRLEN_WIDTH_SITES:
        assert a.read(site, 4) == asm('bl %#x' % STRLEN, site), hex(site)
        for k in (4, 8):
            for imm, new in ((6, 1), (0xc, 2)):
                if a.read(site + k, 4) == asm('mov r1, #%d' % imm, site + k):
                    a.write(site + k, asm('mov r1, #%d' % new, site + k))
                    break
            else:
                continue
            break
        else:
            raise AssertionError('no strlen scale after %#x' % site)
        a.write(site, asm('bl %#x' % vwf_px_addr, site))
    # short_full_name(state, id, buf), entered through a per-limit stub that sets
    # r3 = max bytes: GetFullName into the scratch buffer, "Surname G." if wider than
    # SHORT_NAME_PX or longer than r3 (historical officers only: their names have a
    # space), then copy at most r3 bytes + NUL to buf. Returns strlen(buf).
    scratch = c; c += NAME_SCRATCH
    short_name = asm('''
        push  {r4, r5, r6, r7, lr}
        mov   r4, r2
        mov   r6, r1
        mov   r7, r3
        cmp   r4, #0
        beq   plain
        ldr   r5, scratch
        mov   r2, r5
        bl    %#x
        cmp   r6, #0x2bc
        bhs   copy
        mov   r0, r5
        bl    %#x
        cmp   r0, #%d
        bgt   short
        mov   r0, r5
        bl    %#x
        cmp   r0, r7
        ble   copy
    short:
        mov   r0, r5
    find:
        ldrb  r1, [r0], #1
        cmp   r1, #0
        beq   copy
        cmp   r1, #0x20
        bne   find
        ldrb  r1, [r0]
        cmp   r1, #0
        beq   copy
        mov   r1, #0x2e
        strb  r1, [r0, #1]
        mov   r1, #0
        strb  r1, [r0, #2]
    copy:
        mov   r0, r4
    cp:
        cmp   r7, #0
        beq   term
        ldrb  r1, [r5], #1
        strb  r1, [r0], #1
        cmp   r1, #0
        beq   done
        sub   r7, r7, #1
        b     cp
    term:
        mov   r1, #0
        strb  r1, [r0]
    done:
        mov   r0, r4
        bl    %#x
        pop   {r4, r5, r6, r7, pc}
    plain:
        bl    %#x
        pop   {r4, r5, r6, r7, pc}
    scratch:
        .word %#x
    ''' % (GET_FULL_NAME, vwf_px_addr, SHORT_NAME_PX, STRLEN, STRLEN, GET_FULL_NAME, scratch), c)
    short_addr = c; c += len(short_name)
    stubs = {}
    for limit in sorted(set(FULL_NAME_UI_SITES.values())):
        stubs[limit] = c
        stub = asm('mov r3, #%d\nb %#x' % (limit, short_addr), c)
        a.write(c, stub)              # (the block is cleared below; rewritten after)
        c += len(stub)
    for site, limit in FULL_NAME_UI_SITES.items():
        assert a.read(site, 4) == asm('bl %#x' % GET_FULL_NAME, site), hex(site)
        a.write(site, asm('bl %#x' % stubs[limit], site))
    a.write(nec_lo, bytes(c - nec_lo))
    a.write(vwf_px_addr, vwf_px); a.write(vwf_len_addr, vwf_len); a.write(short_addr, short_name)
    for limit, addr in stubs.items():
        a.write(addr, asm('mov r3, #%d\nb %#x' % (limit, short_addr), addr))

    assert a.read(MSG_FILE_LIMIT, 4) == asm('cmp r1, #0x1a', MSG_FILE_LIMIT)
    a.write(MSG_FILE_LIMIT, asm('cmp r1, #0x28', MSG_FILE_LIMIT))
    for site, (old, new) in NAME_SITES.items():
        assert a.read(site, 4) == asm(old, site), hex(site)
        a.write(site, asm(new, site))
    for addr, (old, new) in NAME_FORMATS.items():
        assert a.read(addr, len(old)) == old and a.read(addr + len(old), 8 - len(old)) == bytes(8 - len(old)), hex(addr)
        a.write(addr, new + bytes(8 - len(new)))

    c = name_entry.apply(a, asm, c)          # English name entry
    # word wrap: the layout routine (0x02083318) breaks a line at the character that
    # overflows the box, mid-word. When the break falls inside a word, move it back to
    # the line's last space (sb = current char, r4 = line start); keep it if the line
    # has no space. Shift-JIS trail bytes are >= 0x40, so a 0x20 byte is always a space.
    assert a.read(WRAP_BREAK, 4) == asm('sub r2, sb, r4', WRAP_BREAK)
    wrap = asm('''
        push  {r0, r1}
        ldrb  r0, [sb, #1]
        cmp   r0, #0x20
        bls   done
        ldrb  r0, [sb]
        cmp   r0, #0x20
        beq   done
        mov   r1, sb
    back:
        sub   r1, r1, #1
        cmp   r1, r4
        bls   done
        ldrb  r0, [r1]
        cmp   r0, #0x20
        bne   back
        mov   sb, r1
    done:
        pop   {r0, r1}
        sub   r2, sb, r4
        bx    lr
    ''', c)
    a.write(c, wrap)
    a.write(WRAP_BREAK, asm('bl %#x' % c, WRAP_BREAK))
    c += len(wrap)
    # battle unit panel: the name field's clear rect stopped at x=138, but English unit
    # names run to the field edge (142), leaving the tail of the previous name
    for site in (0x021256B8, 0x02125870):
        assert a.read(site, 4) == asm('mov r3, #0x8a', site), hex(site)
        a.write(site, asm('mov r3, #0x8e', site))
    # word wrap in the drawer (0x020836CC, used by message windows): it draws as it goes
    # and starts a new line only when the next character would cross the right edge
    # ([sp, #0x38]), i.e. mid-word. After drawing a space, measure the following word;
    # if it would cross the edge, set r7 (the drawer's 'line break' flag, as for \n).
    # Replaces the DRAW_ADVANCE hook (same advance, plus the check).
    draw_wrap = asm('''
        push  {r0, r1, r2, r3, lr}
        ldrb  r0, [sb]
        bl    %#x
        add   r5, r5, r0
        ldrb  r0, [sb]
        cmp   r0, #0x20
        bne   out
        add   r1, sb, #1
        mov   r2, r5
    word:
        ldrb  r0, [r1], #1
        cmp   r0, #0x20
        bls   check
        cmp   r0, #0x5c
        beq   check
        cmp   r0, #0x80
        blo   ascii
        cmp   r0, #0xa0
        blo   dbl
        cmp   r0, #0xe0
        addlo r2, r2, #6
        blo   word
    dbl:
        add   r1, r1, #1
        add   r2, r2, #12
        b     word
    ascii:
        bl    %#x
        add   r2, r2, r0
        b     word
    check:
        ldr   r3, [sp, #0x4c]
        cmp   r2, r3
        movhi r7, #1
    out:
        pop   {r0, r1, r2, r3, pc}
    ''' % (WIDTH_FN, WIDTH_FN), c)
    a.write(c, draw_wrap)
    a.write(DRAW_ADVANCE, asm('bl %#x' % c, DRAW_ADVANCE))
    c += len(draw_wrap)
    assert c <= nec_hi, "out of NEC glyph space"
    FREE[:] = [(t, area_end), (c, nec_hi)]

    stock = asm('sub r0, r0, r2\nadd r0, r3, r0, lsr #1\nbx lr\nmov r0, r3', ALIGN_CENTRE)
    assert a.read(ALIGN_CENTRE, 16) == stock
    a.write(ALIGN_DEFAULT_BRANCH, asm('b 0x0208369c', ALIGN_DEFAULT_BRANCH))   # same: mov r0, r3; bx lr
    a.write(ALIGN_CENTRE, asm('subs r0, r0, r2\nmovmi r0, #0\nadd r0, r3, r0, lsr #1\nbx lr', ALIGN_CENTRE))

    src = f'''
        and   r1, r1, #0xff
        sub   r0, r1, #0x20
        cmp   r0, #0x60
        bhs   {FALLBACK:#x}
        ldr   r1, [pc, #8]
        add   r0, r0, r0, lsl #3
        add   r0, r1, r0
        pop   {{r4, pc}}
    '''
    code_bytes = asm(src, HOOK) + struct.pack('<I', table_addr)
    assert HOOK + len(code_bytes) <= HOOK_END
    a.write(HOOK, code_bytes)
    return table_addr
