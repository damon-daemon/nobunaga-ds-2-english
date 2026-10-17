"""Graphic text edits applied at build time (English labels drawn over the ROM's art).

OBJ packs (obj/<name>.dat, see koeipack) hold NANR/NCER/NCGR/NCLR; labels live in
NCER cells. A label is redrawn inside a box in cell coordinates: the box's
background is rebuilt (per row: the row's most common value) and the text drawn
centred in the original text's fill colour, with a 1px shadow right and below.
The colours are taken from the original pixels, so one edit serves every palette
variant of a button (cells that share tiles).
"""
import os, struct, sys
from collections import Counter
sys.path.insert(0, os.path.dirname(__file__))
import koeipack, nitrogfx, gfxtext

class Obj:
    def __init__(self, rom, name):
        self.rom, self.name = rom, name
        self.parts = koeipack.split(rom.getFileByName(name + '.dat'), rom.getFileByName(name + 'Info.dat'))
        self.kind = [p[:4] for p in self.parts]
        self.C = nitrogfx.Cells(self.parts[self.kind.index(b'RECN')])
        self.T = nitrogfx.Tiles(self.parts[self.kind.index(b'RGCN')])
        self.P = nitrogfx.Palette(self.parts[self.kind.index(b'RLCN')])

    def pixels(self, cell, box=None, oams=None):
        """{(x, y): (tile, offset)} for the cell's pixels (front OAM wins), within box."""
        m = {}
        for k, o in enumerate(self.C.cells[cell]):
            if oams is not None and k not in oams:
                continue
            tw = o['w'] // 8
            for n, t in enumerate(nitrogfx.oam_tiles(self.C, self.T, o)):
                for y in range(8):
                    for x in range(8):
                        lx, ly = n % tw * 8 + x, n // tw * 8 + y
                        if o['hf']: lx = o['w'] - 1 - lx
                        if o['vf']: ly = o['h'] - 1 - ly
                        p = (o['x'] + lx, o['y'] + ly)
                        if box and not (box[0] <= p[0] < box[0] + box[2] and box[1] <= p[1] < box[1] + box[3]):
                            continue
                        m.setdefault(p, (t, y * 8 + x))
        return m

    def get(self, m):
        return {p: self.T.tile(t)[i] for p, (t, i) in m.items()}

    def put(self, m, vals):
        tiles = {}
        for p, v in vals.items():
            t, i = m[p]
            tiles.setdefault(t, self.T.tile(t))[i] = v
        for t, px in tiles.items():
            self.T.set_tile(t, px)

    def band(self, cell, x0=0, x1=999):
        """Box around the cell's 16px-high (text) OAMs whose x is in [x0, x1)."""
        os_ = [o for o in self.C.cells[cell] if o['h'] <= 16 and x0 <= o['x'] < x1]
        bx = min(o['x'] for o in os_); by = min(o['y'] for o in os_)
        return (bx, by, max(o['x'] + o['w'] for o in os_) - bx, max(o['y'] + o['h'] for o in os_) - by)

    def lead(self, cell):
        """The label's text OAMs: the leading run of OAMs at most 16 px high that tile
        beside each other (frames come after, and lie behind/overlap the text)."""
        if not hasattr(self, '_use'):
            self._use = Counter((o['tile'], o['w'], o['h']) for oams in self.C.cells for o in oams)
        hit = lambda a, b: a['x'] < b['x'] + b['w'] and b['x'] < a['x'] + a['w'] and \
            a['y'] < b['y'] + b['h'] and b['y'] < a['y'] + a['h']
        use = lambda o: self._use[(o['tile'], o['w'], o['h'])]
        out = []
        for o in self.C.cells[cell]:
            if o['h'] > 16 or any(hit(o, q) for q in out) or out and use(o) > 3 * use(out[0]):
                break
            out.append(o)
        return out

    def text_box(self, cell):
        """Default label box: the leading text OAMs, else every OAM but the biggest."""
        rest = self.lead(cell)
        rest = [o for o in rest if o['h'] <= 16] or rest
        if rest:
            x0 = min(o['x'] for o in rest); y0 = min(o['y'] for o in rest)
            return (x0, y0, max(o['x'] + o['w'] for o in rest) - x0, max(o['y'] + o['h'] for o in rest) - y0)
        oams = self.C.cells[cell]
        if len(oams) == 1:
            o = oams[0]; return (o['x'], o['y'], o['w'], o['h'])
        big = max(range(len(oams)), key=lambda k: oams[k]['w'] * oams[k]['h'])
        rest = [o for k, o in enumerate(oams) if k != big]
        x0 = min(o['x'] for o in rest); y0 = min(o['y'] for o in rest)
        return (x0, y0, max(o['x'] + o['w'] for o in rest) - x0, max(o['y'] + o['h'] for o in rest) - y0)

    UNIT = 128                      # OAM tile numbers count 128-byte blocks (1D 128K mapping)

    def bank(self, cell, k=0):
        """Palette offset of the cell's OAM k: 16-colour banks (4bpp) or 256-colour
        extended palettes (8bpp packs with more than 256 colours)."""
        pal = self.C.cells[cell][k]['pal']
        return pal * 16 if self.T.bpp == 4 else pal * 256 if len(self.P.colors) > 256 else 0

    def users(self, t):
        """[(cell, oam index)] whose OAM covers tile t."""
        return [(c, k) for c, oams in enumerate(self.C.cells) for k, o in enumerate(oams)
                if t in nitrogfx.oam_tiles(self.C, self.T, o)]

    def unshare(self, cell, tiles, box):
        """Give the cell's OAMs that cover any of tiles their own copy of the art when a
        cell outside its group also uses them. The group = cells having every OAM of this
        cell that lies in the box (the label's OAMs): its palette and pressed variants."""
        key = lambda o: (o['tile'], o['w'], o['h'])
        bx, by, bw, bh = box
        if not hasattr(self, '_use'):
            self._use = Counter(key(o) for oams in self.C.cells for o in oams)
        inside = [o for o in self.C.cells[cell]
                  if bx <= o['x'] and o['x'] + o['w'] <= bx + bw and by <= o['y'] and o['y'] + o['h'] <= by + bh]
        inside = inside or self.C.cells[cell][:1]
        least = min(self._use[key(o)] for o in inside)
        mine = {key(o) for o in inside if self._use[key(o)] == least}
        group = {c for c, oams in enumerate(self.C.cells) if mine <= {key(o) for o in oams}}
        for k, o in enumerate(self.C.cells[cell]):
            ts = nitrogfx.oam_tiles(self.C, self.T, o)
            if not tiles & set(ts):
                continue
            others = [c for t in ts for c, j in self.users(t) if c not in group]
            if not others:
                continue
            size = len(ts) * self.T.tsize
            start = len(self.T.data)
            start += -start % self.UNIT
            self.T.data += bytes(start - len(self.T.data))
            self.T.data += self.T.data[ts[0] * self.T.tsize:ts[0] * self.T.tsize + size]
            self.T.data += bytes(-len(self.T.data) % self.UNIT)
            self.T.count = len(self.T.data) // self.T.tsize
            old = (o['tile'], o['w'], o['h'])
            for c in group:
                for x in self.C.cells[c]:
                    if (x['tile'], x['w'], x['h']) == old:
                        nitrogfx.set_oam(self.C, x, tile=start // self.UNIT)

    def _oam_px(self, o):
        return [(t, i) for t in nitrogfx.oam_tiles(self.C, self.T, o) for i in range(64)]

    def alloc(self, w, h):
        """Append blank art for a w x h OAM; returns its OAM tile number."""
        start = len(self.T.data) + -len(self.T.data) % self.UNIT
        self.T.data += bytes(start - len(self.T.data) + w * h * self.T.bpp // 8)
        self.T.data += bytes(-len(self.T.data) % self.UNIT)
        self.T.count = len(self.T.data) // self.T.tsize
        return start // self.UNIT

    def widen(self, cell, k, w, dx):
        """Make the cell's OAM k w px wide (moved dx), with fresh art, in every cell using it."""
        o = self.C.cells[cell][k]
        old = (o['tile'], o['w'], o['h'], o['x'])
        art = self.get(self.pixels(cell, oams=[k]))
        tile = self.alloc(w, o['h'])
        for oams in self.C.cells:
            for x in oams:
                if (x['tile'], x['w'], x['h']) == old[:3]:
                    nitrogfx.set_oam(self.C, x, x=x['x'] + dx, w=w, tile=tile)
        m = self.pixels(cell, oams=[k])
        self.put(m, {p: art.get(p, 0) for p in m})
        n = self.C.cells[cell][k]          # OAMs now hidden behind it: clear (transparent layers)
        for j, q in enumerate(self.C.cells[cell]):
            if j != k and n['x'] <= q['x'] and q['x'] + q['w'] <= n['x'] + n['w'] and \
                    n['y'] <= q['y'] and q['y'] + q['h'] <= n['y'] + n['h']:
                mq = {}
                for (t, i) in self._oam_px(q):
                    mq[(t, i)] = 0
                for (t, i) in mq:
                    px = self.T.tile(t); px[i] = 0; self.T.set_tile(t, px)
        self._use = Counter((o['tile'], o['w'], o['h']) for oams in self.C.cells for o in oams)

    def save(self):
        parts = list(self.parts)
        f = bytearray(self.T.file[:self.T.data_off]) + self.T.data
        f[self.T.char_off - 4:self.T.char_off] = struct.pack('<I', len(f) - self.T.char_off + 8)
        f[self.T.char_off + 16:self.T.char_off + 20] = struct.pack('<I', len(self.T.data))
        f[8:12] = struct.pack('<I', len(f))
        parts[self.kind.index(b'RGCN')] = bytes(f)
        parts[self.kind.index(b'RECN')] = bytes(self.C.file)
        data, info = koeipack.join(parts, align=0x10)
        self.rom.files[self.rom.filenames.idOf(self.name + '.dat')] = data
        self.rom.files[self.rom.filenames.idOf(self.name + 'Info.dat')] = info

def lines_mask(text, step=11):
    """render_plain for text with \\n: lines centred, step px apart."""
    ms = [gfxtext.render_plain(t) for t in text.split('\n')]
    w = max(len(m[0]) for m in ms)
    h = step * (len(ms) - 1) + len(ms[-1])
    out = [[False] * w for _ in range(h)]
    for k, m in enumerate(ms):
        x0 = (w - len(m[0])) // 2
        for y, row in enumerate(m):
            for x, v in enumerate(row):
                if v:
                    out[k * step + y][x0 + x] = True
    return out

def lum(c):
    return c[0] * 3 + c[1] * 6 + c[2]

def counts(obj, cell, box, oams=None, per_pixel=False):
    """Counters of values per box row (or per pixel), relative to the box."""
    old = obj.get(obj.pixels(cell, box, oams))
    out = {}
    for (x, y), v in old.items():
        out.setdefault((x - box[0], y - box[1]) if per_pixel else y - box[1], Counter())[v] += 1
    return out

def label(obj, cell, text, box=None, oams=None, dy=0, rows=None, pool=None, per_pixel=False, span=False, outline=None, dark=None, flat=False, fill=None, back=None, align='c',
          clear=None):
    """rows: Counters pooled over the labels of the same layout (pool key; default the box
    size): the background is each row's most common value, or each pixel's with per_pixel
    (plates with a gradient; labels sharing it put their text in different places)."""
    box = box or obj.text_box(cell)
    m = obj.pixels(cell, box, oams)
    old = obj.get(m)
    bx, by, bw, bh = box
    rows = rows or counts(obj, cell, box, oams, per_pixel)
    if per_pixel:
        bgp = {(bx + x, by + y): c.most_common(1)[0][0] for (x, y), c in rows.items()}
        bg = {y: Counter(v for p, v in bgp.items() if p[1] == y).most_common(1)[0][0] for y in range(by, by + bh)}
    else:
        bank_ = obj.bank(cell)
        ok = lambda v: dark is None or lum(obj.P.colors[bank_ + v]) < dark
        bg = {by + y: next((v for v, _ in c.most_common() if ok(v)), c.most_common(1)[0][0]) for y, c in rows.items()}
        if flat:                     # one colour for the whole box
            total = sum(rows.values(), Counter())
            one = next(v for v, _ in total.most_common() if ok(v))
            if back is not None:
                n_ = 256 if obj.T.bpp == 8 else 16
                one = nearest([obj.P.colors[bank_ + k] for k in range(n_)], back)
            bg = {y: one for y in bg}
        bgp = {p: bg.get(p[1], v) for p, v in old.items()}
    bank = obj.bank(cell)
    col = lambda v: obj.P.colors[bank + v]
    allc = sum(rows.values(), Counter())
    if clear is None:
        clear = allc.most_common(1)[0][0] == 0  # transparent text layer: outline the text
    if clear:
        bg = {y: 0 for y in bg}
        bgp = {p: 0 for p in bgp}
    ink = Counter(v for p, v in old.items() if v != bg.get(p[1]))
    if not ink:
        raise ValueError('%s cell %d: no text in box' % (obj.name, cell))
    common = [v for v, _ in ink.most_common(6)]
    fill_rgb = fill
    if clear and outline is None:
        outline = min((col(v) for v in common if v), key=lum)
    fill = max(common, key=lambda v: abs(lum(col(v)) - lum(col(bg[by + bh // 2])))) if not clear else \
        max((v for v in common if v), key=lambda v: lum(col(v)))
    mid = [tuple((a + b) // 2 for a, b in zip(col(fill), col(bg[by + bh // 2])))]
    shade = min(common, key=lambda v: sum((a - b) ** 2 for a, b in zip(col(v), mid[0])) if v != fill else 1e9)
    mask = lines_mask(text)
    h, w = len(mask), len(mask[0])
    if w > bw:
        raise ValueError('%s cell %d: %r is %d px, box %d' % (obj.name, cell, text, w, bw))
    ox, oy = bx + (bw - w - 1) // 2 if align == 'c' else bx + 2, by + (bh - h - 1) // 2 + dy
    new = {p: bgp.get(p, v) for p, v in old.items()}
    if span:                         # rebuild rows from the pixels just outside the box
        allpx = obj.get(obj.pixels(cell))
        n = 256 if obj.T.bpp == 8 else 16
        sub = [obj.P.colors[bank + k] for k in range(n)]
        for y in range(by, by + bh):
            a, b = allpx.get((bx - 1, y)), allpx.get((bx + bw, y))
            if a is None or b is None:
                continue
            a, b = col(a), col(b)
            for x in range(bx, bx + bw):
                t = (x - bx + 1) / (bw + 1)
                if (x, y) in new:
                    new[(x, y)] = nearest(sub, tuple(round(p + (q - p) * t) for p, q in zip(a, b)))
    n = 256 if obj.T.bpp == 8 else 16
    if outline is not None:
        shade = nearest([obj.P.colors[bank + k] for k in range(n)], outline)
    if fill_rgb is not None:
        fill = nearest([obj.P.colors[bank + k] for k in range(n)], fill_rgb)
    on = lambda x, y: 0 <= x < w and 0 <= y < h and mask[y][x]
    for y in range(-1, h + 1):
        for x in range(-1, w + 1):
            p = (ox + x, oy + y)
            if p not in new:
                continue
            if on(x, y):
                new[p] = fill
            elif on(x - 1, y) or on(x, y - 1) or (outline is not None and any(
                    on(x + dx, y + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1))):
                new[p] = shade
    obj.unshare(cell, {m[p][0] for p in new if new[p] != old[p]}, box)
    obj.put(obj.pixels(cell, box, oams), new)

class Bg:
    """bg/<name>.dat images: a 0x80-byte header (u16 width at 2, u16 height at 4), a
    256-colour palette, an identity 32x32 map (full screens only), 8bpp tiles."""
    def __init__(self, rom, name):
        self.rom, self.name = rom, name
        self.parts = koeipack.split(rom.getFileByName(name + '.dat'), rom.getFileByName(name + 'Info.dat'))
        self.cache = {}

    def image(self, i):
        if i not in self.cache:
            u = bytearray(koeipack.unpack(self.parts[i]))
            w, h = struct.unpack_from('<HH', u, 2)
            pal = [((c & 31) * 255 // 31, (c >> 5 & 31) * 255 // 31, (c >> 10 & 31) * 255 // 31)
                   for c in struct.unpack_from('<256H', u, 0x80)]
            self.cache[i] = (u, w, len(u) - w * h, pal)
        return self.cache[i]

    def at(self, i, x, y):
        u, w, off, _ = self.image(i)
        return off + (y // 8 * (w // 8) + x // 8) * 64 + y % 8 * 8 + x % 8

    def get(self, i, box):
        u = self.image(i)[0]
        bx, by, bw, bh = box
        return {(x, y): u[self.at(i, x, y)] for y in range(by, by + bh) for x in range(bx, bx + bw)}

    def put(self, i, vals):
        u = self.image(i)[0]
        for (x, y), v in vals.items():
            u[self.at(i, x, y)] = v

    def save(self):
        parts = list(self.parts)
        for i, (u, *_) in self.cache.items():
            parts[i] = koeipack.pack(bytes(u))
        data, info = koeipack.join(parts, align=0x80)
        self.rom.files[self.rom.filenames.idOf(self.name + '.dat')] = data
        self.rom.files[self.rom.filenames.idOf(self.name + 'Info.dat')] = info

def dist(a, b):
    return sum((p - q) ** 2 for p, q in zip(a, b))

def bg_label(bg, i, box, text, align='l', dx=0, dy=0, room=None, span=False, fill=None, clean=None,
             outline=None, glow=None, line=13, bold=False, scale=1, rows=None):
    """Erase the text in box and draw English in its place.

    Erasing: pixels nearer the text colour than the box's background are refilled from
    the nearest clean pixel in their row; span=True instead rebuilds whole rows from the
    pixels either side of the box (glowing text on smooth plates), span='v' clones the
    texture from the block below (or above; rows=(y0, n) names the clean rows, tiled),
    shifted per column to match the box edges; clean=[images] takes
    the per-pixel median of the same area in other images with the same painting.
    Drawing: text (lines split on \\n, line apart) in the old text colour (or fill=rgb),
    left-aligned at the box's x + dx or centred, caps centred on the box's middle;
    outline / glow = rgb rings around it. room = width allowed (default: box + 4).
    bold = bold capitals, scale = pixel size (big calligraphy-style captions)."""
    pal = bg.image(i)[3]
    old = bg.get(i, box)
    bx, by, bw, bh = box
    ring = bg.get(i, (bx - 1, by - 1, bw + 2, bh + 2))
    edge = Counter(v for p, v in ring.items() if p not in old).most_common(1)[0][0]
    count = Counter(old.values())
    fill_v = max((v for v, _ in count.most_common(10)), key=lambda v: dist(pal[v], pal[edge]))
    back = next(v for v, _ in count.most_common() if dist(pal[v], pal[fill_v]) > dist(pal[edge], pal[fill_v]) / 2)
    far = dist(pal[fill_v], pal[back])
    new = dict(old)
    if clean:                        # same painting under other overlays: take a colour two of them agree on
        win = (bx - 6, by - 6, bw + 12, bh + 12)
        here = bg.get(i, win)
        srcs = []
        for j in clean:              # each source's colours fitted to this image (per channel, least squares)
            v, sp = bg.get(j, win), bg.image(j)[3]
            ps = [p for p in here if p not in old]
            fit = []
            for c in range(3):
                xs = [sp[v[p]][c] for p in ps]; ys = [pal[here[p]][c] for p in ps]
                mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
                vx = sum((x - mx) ** 2 for x in xs) or 1
                k = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / vx
                fit.append((k, my - k * mx))
            srcs.append({p: tuple(max(0, min(255, round(k * sp[v[p]][c] + o))) for c, (k, o) in enumerate(fit))
                         for p in old})
        for p in old:
            cs = [src[p] for src in srcs]
            pairs = [(dist(cs[a], cs[b]), a) for a in range(len(cs)) for b in range(a + 1, len(cs))]
            d, a = min(pairs) if pairs else (0, 0)
            if d > 24 * 24 * 3:          # no agreement: the one nearest this image's own pixel
                a = min(range(len(cs)), key=lambda k: dist(cs[k], pal[old[p]]))
            new[p] = nearest(pal, cs[a])
    elif span == 'v':                # texture cloned from clean rows below (or above), shifted
        h = (len(bg.image(i)[0]) - bg.image(i)[2]) // bg.image(i)[1]  # per column to match the edges
        y0, n = rows or ((by + bh + 1, bh + 2) if by + 2 * bh + 2 < h else (by - bh - 3, bh + 2))
        src = bg.get(i, (bx, y0, bw, n))
        sp = lambda x, y: pal[src[(x, y0 + (y - by + 1) % n)]]
        for x in range(bx, bx + bw):
            top = [a - b for a, b in zip(pal[ring[(x, by - 1)]], sp(x, by - 1))]
            bot = [a - b for a, b in zip(pal[bg.get(i, (x, by + bh, 1, 1))[(x, by + bh)]], sp(x, by + bh))]
            for y in range(by, by + bh):
                t = (y - by + 1) / (bh + 1)
                new[(x, y)] = nearest(pal, tuple(max(0, min(255, round(c + p + (q - p) * t)))
                                                 for c, p, q in zip(sp(x, y), top, bot)))
    elif span:
        ends = bg.get(i, (bx - 1, by, 1, bh)), bg.get(i, (bx + bw, by, 1, bh))
        for y in range(by, by + bh):
            a, b = pal[ends[0][(bx - 1, y)]], pal[ends[1][(bx + bw, y)]]
            for x in range(bx, bx + bw):
                t = (x - bx + 1) / (bw + 1)
                new[(x, y)] = nearest(pal, tuple(round(p + (q - p) * t) for p, q in zip(a, b)))
    else:
        ink = {p for p, v in old.items() if dist(pal[v], pal[back]) > far * 0.12}
        for (x, y) in ink:
            for d in range(1, bw):
                c = [q for q in ((x - d, y), (x + d, y)) if q in old and q not in ink]
                if c:
                    new[(x, y)] = old[c[0]]; break
    fill = nearest(pal, fill) if fill is not None else fill_v
    rings = [nearest(pal, c) for c in (outline, glow) if c is not None]
    lines = text.split('\n')
    room = room or bw + 4 - dx       # labels may run a little past the kanji they replace
    top = by + (bh - 9 * scale - line * (len(lines) - 1)) // 2 + dy
    for n, t in enumerate(lines):
        mask = gfxtext.render(t.upper(), gap=1, stretch=()) if bold else gfxtext.render_plain(t)
        mask = [[v for v in row for _ in range(scale)] for row in mask for _ in range(scale)]
        h, w = len(mask), len(mask[0])
        if w > room:
            raise ValueError('%s %d: %r is %d px, room %d' % (bg.name, i, t, w, room))
        ox = bx + dx if align == 'l' else bx + (bw - w) // 2 + dx
        oy = top + n * line
        m = gfxtext.pad(mask, len(rings))
        layers = [m]
        for _ in rings:
            layers.append(gfxtext.dilate(layers[-1]))
        k0 = len(rings)
        for y in range(len(m)):
            for x in range(len(m[0])):
                p = (ox - k0 + x, oy - k0 + y)
                if m[y][x]:
                    new[p] = fill
                else:
                    for k, c in enumerate(rings):
                        if layers[k + 1][y][x]:
                            if p not in new or new[p] != fill:
                                new[p] = c
                            break
    bg.put(i, new)

def grid(xs, ys, w, h, texts):
    """Labels on a table of plates: texts row by row, one box per (x, y)."""
    return [((x, y, w, h), t) for y, row in zip(ys, texts) for x, t in zip(xs, row)]

PROVINCE = [((135, 12, 23, 11), 'Lord')] + grid((54, 108, 156, 204), (29, 44, 59), 23, 11, [
    ('Gold', 'Comm', 'Law', 'Cult'),
    ('Food', 'Koku', 'Def', 'Tech'),
    ('Men', 'Drill', 'Guns', 'Gens')]) + [
    ((14, 89, 36, 11), 'Gold Net'), ((92, 89, 47, 11), 'Food Net'), ((8, 106, 23, 11), 'Ronin'),
    ((8, 139, 23, 11), 'Skill'), ((62, 139, 23, 11), 'Craft'), ((8, 156, 47, 11), 'Culture')]

def nearest(pal, rgb):
    return min(range(1, min(256, len(pal))), key=lambda v: dist(pal[v], rgb))

TITLE = dict(fill=[(238, 230, 255), (230, 213, 255), (222, 205, 255), (205, 189, 246)],
             outline=(0, 0, 0), glow=[(139, 139, 98)])

def bg_title(bg, i, box, text, style=TITLE, dy=0):
    """Screen-title banner: box = the whole plate, repainted with its flat colour (taken
    2px in from the left edge) and a frame line 1px in (colour taken from the left edge
    line); text in bold capitals with gradient fill, black outline and a glow ring."""
    bg.put(i, title_px(bg.get(i, box), bg.image(i)[3], box, text, style, dy, '%s %d' % (bg.name, i)))

def title_px(old, pal, box, text, style=TITLE, dy=0, where=''):
    """bg_title's drawing on a {(x, y): value} dict; returns the new values."""
    bx, by, bw, bh = box
    flat, line = Counter(old.values()).most_common(1)[0][0], old[(bx + 1, by + bh // 2)]
    new = {}
    for (x, y) in old:
        inner = bx + 1 <= x < bx + bw - 1 and by + 1 <= y < by + bh - 1
        edge = x in (bx + 1, bx + bw - 2) or y in (by + 1, by + bh - 2)
        new[(x, y)] = line if inner and edge else flat
    m = gfxtext.pad(gfxtext.render(text.upper(), gap=2, stretch=()), 3)
    h, w = len(m), len(m[0])
    if w - 6 > bw - 4:
        raise ValueError('%s: title %r is %d px, room %d' % (where, text, w - 6, bw))
    ox, oy = bx + (bw - w) // 2, by + (bh - h) // 2 + dy
    rings = [m]
    for _ in range(1 + len(style['glow'])):
        rings.append(gfxtext.dilate(rings[-1]))
    fill = [nearest(pal, c) for c in style['fill']]
    cols = [nearest(pal, style['outline'])] + [nearest(pal, c) for c in style['glow']]
    for y in range(h):
        for x in range(w):
            p = (ox + x, oy + y)
            if p not in new:
                continue
            if m[y][x]:
                new[p] = fill[min(len(fill) - 1, (y - 3) * len(fill) // (h - 6))]
            else:
                for k in range(len(cols)):
                    if rings[k + 1][y][x]:
                        new[p] = cols[k]; break
    return new

def obj_title(obj, cell, text):
    """A screen-title banner drawn as an 8bpp OBJ cell (144x24 at 0,0)."""
    m = obj.pixels(cell, BANNER)
    obj.put(m, title_px(obj.get(m), obj.P.colors[obj.bank(cell):][:256], BANNER, text, where='%s %d' % (obj.name, cell)))

OBJ_TITLES = {'obj/C256_ShoMainUe': {0: 'SP Officer Setup', 1: 'Settings'}, 'obj/C256_SaveLoadUe': {0: 'Load'},
              'obj/C256_ShoOptUe': {0: 'Strategy Manual'},
              'obj/C256_TsuushinUe': {0: 'Warring Link', 1: 'Wi-Fi Connection', 2: 'Download Officers',
                                      3: 'Officer Acquired', 4: 'Link Up', 5: 'DS Wireless'},
              'obj/C256_ShinbuUe1': {0: 'Re-edit', 1: 'Delete', 2: 'Set Parent'},
              'obj/C256_ShinbuUe': dict(enumerate(['Create Officer', 'Choose Face', 'Set Name', 'Set Reading',
                                                   'Set Stats', 'Set Aptitude', 'Set Age', 'Set Parent',
                                                   'Set Affinity', 'Set Traits']))}

T = dict(title=True)
BANNER = (0, 0, 144, 24)              # screen-title plate, top left

TITLES = {86: 'Unit Formation', 88: 'Assign Spoils', 115: 'Confirm Settings', 1: 'Officer Acquired', 10: 'Register Officer', 19: 'Tutorial', 54: 'Daimyo Select', 56: 'Daimyo Select', 76: 'Options', 84: 'Army Name', 93: 'Best Record', 95: 'Record', 96: 'Stage Select', 100: 'Battle Practice', 101: 'Battle Prep', 102: 'Domestic Practice', 103: 'Battle Guide', 109: 'New Officer Setup', 113: 'Save', 118: 'Scenario Select', 121: 'Start Menu', 125: 'Objectives'}

# officer panel (officer info, daimyo select, ...)
OFFICER = [((54, 46, 23, 11), 'Clan'), ((54, 61, 23, 11), 'Loyal'), ((102, 61, 23, 11), 'Age')] + \
    grid((8, 56, 104, 152), (85,), 23, 11, [('POL', 'WAR', 'LRN', 'CHA')]) + [
    ((8, 106, 23, 11), 'Apt.'), ((55, 107, 24, 12), 'Foot'), ((115, 107, 24, 12), 'Horse'), ((176, 107, 24, 12), 'Guns')]

def daimyo(dy):
    """Daimyo panel (daimyo select / clan info), dy = rows below the clan-info layout."""
    return [((54, 46 + dy, 23, 11), 'Lands'), ((122, 46 + dy, 23, 11), 'Gold'), ((188, 46 + dy, 23, 11), 'Amity'),
            ((54, 61 + dy, 23, 11), 'Gens'), ((122, 61 + dy, 23, 11), 'Food'), ((188, 61 + dy, 23, 11), 'Ally'),
            ((54, 76 + dy, 23, 11), 'Men'), ((122, 76 + dy, 23, 11), 'Guns'), ((8, 99 + dy, 23, 11), 'Tact.')]

PROVINCE2 = [((135, 8, 23, 11), 'Lord')] + grid((56, 110, 158, 206), (27, 43, 59), 23, 11, [
    ('Gold', 'Comm', 'Law', 'Cult'),
    ('Food', 'Koku', 'Def', 'Tech'),
    ('Men', 'Drill', 'Guns', 'Gens')]) + [
    ((8, 84, 23, 11), 'Ronin'), ((56, 84, 23, 11), 'Rice $'), ((104, 84, 23, 11), 'Men $')]

TRANSPORT = [((36, 37, 35, 11), 'From'), ((163, 37, 35, 11), 'To')] + \
    grid((43, 170), (69, 90, 111, 132), 23, 11, [('Gold', 'Gold'), ('Food', 'Food'), ('Men', 'Men'), ('Guns', 'Guns')])

# Clash of Warlords: stage / record screens
CLASH_STAGE = [((69, 51, 60, 14), 'Enemy Commander', dict(room=100, span=True)),
               ((70, 67, 52, 13), 'Normal', dict(span=True)), ((69, 82, 40, 13), 'Hard', dict(span=True, fill=(140, 140, 148))),
               ((20, 96, 91, 14), 'Gems Available', dict(room=95, span=True))]
DATE_INK = dict(badge=True, sy=1, plain=True, warm=40, fill=(255, 222, 82), outline=(66, 16, 0))
# officer list 'jump to kana' grid: officers are grouped by the kana their Japanese
# reading starts with, and English names are romanised from those readings, so each
# cell gets its romaji syllable (greyed cells: no officers)
KANA_ROWS = [('A I U E O', 'Ha Hi Fu He Ho'), ('Ka Ki Ku Ke Ko', 'Ma Mi Mu Me Mo'),
             ('Sa Shi Su Se So', 'Ya - Yu - Yo'), ('Ta Chi Tsu Te To', 'Ra Ri Ru Re Ro'),
             ('Na Ni Nu Ne No', 'Wa - Wo - N')]
KANA_GREY = {'Ke', 'Te', 'Ra', 'Re', 'Wo', 'N'}
KANA_INK = dict(align='c', clean=[63, 64, 79], outline=(16, 24, 41))   # same painting without the grid
KANA_JUMP = [((round(x0 + dx * c) + 1, 34 + 21 * r, 17, 17), t,
              dict(KANA_INK, fill=(140, 140, 148) if t in KANA_GREY else (246, 246, 255)))
             for r, row in enumerate(KANA_ROWS) for x0, dx, part in ((16, 21, row[0]), (139, 20.5, row[1]))
             for c, t in enumerate(part.split()) if t != '-'] + \
            [((186, 145, 54, 20), 'All Officers', dict(KANA_INK, fill=(246, 246, 255)))]
# Clash of Warlords unit formation (top screen)
CLASH_FORMATION = grid((52, 108, 158), (12, 27), 23, 11, [('Gold', 'Men', 'Guns'), ('Food', 'Drill', 'Def')]) + \
    [((x, 86, 56, 40), t, dict(badge=True)) for x, t in ((4, 'Brave'), (84, 'Fiery'), (164, 'Wise'))] + \
    [((x, 99, 20, 24), '', dict(badge=True)) for x in (59, 143, 226)]
INPUT_UNIT = [((92, 109, 47, 11), 'Input Unit', dict(room=60))]

GLOW = dict(fill=(238, 238, 246), glow=(41, 57, 98))
SETTINGS = ['Mode', 'Difficulty', 'Message Speed', 'Carry Over Stats', 'Battle Deaths', 'Lifespan']
CONFIRM_ROWS = ['Daimyo', 'Provinces', 'Officers'] + SETTINGS[:1] + SETTINGS[2:]

def rows(x, y0, step, w, h, texts, **opt):
    return [((x, y0 + k * step, w, h), t, dict(opt)) for k, t in enumerate(texts) if t]

# Clash: officer acquired / SP officer card
CARD = [((58, 69, 35, 11), 'Born'),
        ((136, 71, 90, 16), 'Clash OK!', dict(span=True, fill=(246, 246, 246), outline=(24, 24, 32), align='c'))] + \
    grid((12, 60, 108, 156), (93,), 23, 11, [('POL', 'WAR', 'LRN', 'CHA')]) + [
    ((12, 113, 23, 11), 'Apt.'), ((58, 112, 27, 14), 'Foot'), ((118, 112, 27, 14), 'Horse'), ((179, 112, 27, 14), 'Guns')]

CLASH_CAPTION = dict(span='v', bold=True, scale=2, fill=(255, 238, 140), outline=(206, 150, 40), glow=(112, 76, 24))

BIG = dict(span=True, fill=(246, 246, 246), glow=(24, 32, 57))

def buttons(y, xs, w, texts):
    """New-officer choice buttons: text centred on each plate."""
    return [((x, y, w, 17), t, dict(BIG, align='c')) for x, t in zip(xs, texts)]

# bg pack: {image: [(box, text, options)]}
BG = {
    'bg/GrpBG': {
        40: PROVINCE, 57: PROVINCE, 46: PROVINCE2,
        37: OFFICER, 55: OFFICER, 58: OFFICER, 59: OFFICER, 60: OFFICER,
        39: daimyo(0), 54: daimyo(28), 56: daimyo(28),
        50: TRANSPORT,
        36: CLASH_FORMATION,
        94: [((4, 10, 66, 30), 'Spoils', dict(badge=True))],
        74: KANA_JUMP,
        # tutorial screenshots
        104: [((2, 2, 96, 13), 'Your orders for Omi?', dict(room=190, span=True)), ((200, 2, 42, 13), 'AP', dict(span=True)),
              ((41, 14, 18, 21), '/', dict(badge=True, sy=1, plain=True)), ((80, 14, 33, 21), 'Aut', dict(badge=True, sy=1, plain=True))] +
             [((x, y, 48, h), t, dict(align='c', span=True)) for y, h, row in ((76, 23, ((14, 'Domestic'), (79, 'Military'), (145, 'Staff'))),
                                                                  (107, 25, ((14, 'Foreign'), (79, 'Intel'), (145, 'End Turn'))))
              for x, t in row] +
             [((228, y, 28, 13), t, dict(room=30)) for y, t in ((62, 'Advice'), (86, 'Gens'), (110, 'Map'))] +
             [((236, 136, 20, 12), 'Auto', dict(room=22))],
        106: [((24, 18, 48, 13), 'Blitz', dict(fill=(239, 239, 239))),
              ((86, 18, 50, 12), 'Requires', dict(span=True)), ((137, 18, 26, 12), 'March', dict(span=True)),
              ((8, 36, 84, 16), '<Movement tactic>', dict(room=100, span=True)),
              ((20, 52, 132, 13), 'Raises mobility for a long time.', dict(room=180, span=True)),
              ((8, 102, 47, 11), 'Owned Skills', dict(room=54)), ((62, 101, 84, 13), '(Left/Owned/Land)')] +
             grid((26, 105, 184), (118, 137, 156), 25, 12, [('March', 'Spear', 'Bow'), ('Riding', 'Guns', 'Siege'),
                                                           ('Strat', 'Ninja')]),
        107: [((2, 2, 110, 13), 'Your orders for Azai Hisamasa?', dict(room=200, span=True))],
        108: [((26, 2, 27, 20), 'day', dict(DATE_INK)),
              ((74, 2, 19, 20), 'h', dict(DATE_INK)),
              ((98, 4, 38, 13), 'Lake Biwa', dict(room=58, span=True)),
              ((9, 28, 19, 19), 'Atk', dict(badge=True, sy=1, plain=True)),
              ((227, 28, 19, 19), 'Def', dict(badge=True, sy=1, plain=True)),
              ((32, 32, 40, 13), 'Rokkaku Army', dict(room=60, span=True)),
              ((162, 32, 40, 13), 'Azai Army', dict(room=60, span=True)),
              ((47, 50, 48, 12), 'Mikumo Sadamochi', dict(room=76)),
              ((173, 50, 48, 12), 'Azai Hisamasa', dict(room=70)),
              ((54, 130, 60, 12), 'Azai Hisamasa Unit', dict(room=82)),
              ((190, 130, 34, 12), 'HQ', dict(span=True))],
        105: [((2, 2, 144, 13), 'This tactic cannot be changed.', dict(span=True)),
              ((96, 141, 64, 14), 'Confirm', dict(align='c', span=True))] +
             [((x + 5, 34, 43, 31), t, dict(align='c', span=True, line=12, fill=f, outline=(32, 32, 32)))
              for x, t, f in ((21, 'Blitz', (255, 255, 246)), (101, 'Bow\nReady', (176, 176, 176)),
                              (181, 'On-\nslaught', (176, 176, 176)))],
        99: CLASH_FORMATION[:6] + [((x, 48, 48, 11), t, dict(fill=(239, 239, 239)))
                                   for x, t in ((36, 'Blitz'), (108, 'Bow Ready'), (180, 'Onslaught'))] +
            [((x, 86, 46, 40), t, dict(badge=True)) for x, t in ((4, 'Brave'), (84, 'Fiery'), (164, 'Wise'))] +
            [((x, 99, 20, 24), '', dict(badge=True)) for x in (59, 143, 226)] + [((x, 99, 20, 24), ' ') for x in (59, 143, 226)] + [((208, 106, 8, 10), ' ')] +
            grid((16, 100, 183), (126, 143, 160), 50, 12, [('Mobility', 'Morale', 'Foe Morale'),
                                                          ('Wait Bonus', 'Attack', 'Defense'),
                                                          ('Climb', 'Attack', 'Defense')]),
        38: [((132, 12, 23, 11), 'Grade'), ((54, 46, 23, 11), 'Owner')],
        123: [((22, 66, 216, 60), 'Press a button\nor touch the lower screen', dict(align='c', clean=[52],
              fill=(230, 222, 255), outline=(41, 41, 131), glow=(82, 172, 197), line=26, room=200))],
        1: CARD, 75: CARD,
        129: [(box, t, dict(CLASH_CAPTION, align='c', rows=(69, 37))) for box, t in (((94, 21, 68, 48), 'Type'), ((80, 106, 100, 52), 'Tactic'))],
        16: [((73, 18, 132, 18), '', dict(pitch=19, n=7)),        # name entry: one field for letters
             ((50, 19, 22, 15), 'Family', dict(room=24))],
        8: [((58, 39, 11, 11), ' '), ((127, 39, 11, 11), ' '),    # 姓/名/読: the names are drawn right after
            ((58, 54, 11, 11), ' ')] +
           grid((12, 63, 114, 165), (93,), 23, 11, [('POL', 'WAR', 'LRN', 'CHA')]) +
           [((12, 110, 23, 11), 'Apt.'), ((12, 127, 23, 11), 'Age'), ((60, 127, 11, 11), 'Parent', dict(room=40)),
            ((12, 144, 23, 11), 'Affinity', dict(room=40))] +
           grid((12, 70, 127, 184), (161,), 23, 11, [('Amb.', 'Duty', 'Type', 'Voice')]),
        13: [((8, 26 + 28 * k, 40, 19), t, dict(BIG, align='c')) for k, t in enumerate(('Politics', 'War', 'Learning', 'Charm'))],
        14: [((14, 26 + 30 * k, 40, 19), t, dict(BIG, align='c')) for k, t in enumerate(('Ambition', 'Duty', 'Type', 'Voice'))] +
            buttons(26, (68, 128, 188), 51, ('Low', 'Normal', 'High')) +
            buttons(56, (68, 128, 188), 51, ('Low', 'Normal', 'High')) +
            buttons(86, (68, 128, 188), 51, ('Brave', 'Fiery', 'Wise')) +
            buttons(116, (67, 103, 139, 175, 211), 29, ('Normal', 'Fiery', 'Noble', 'Monk', 'Ninja')),
        15: [((17, 41 + 30 * k, 82, 20), t, dict(BIG, room=76)) for k, t in enumerate(('Ashigaru', 'Cavalry', 'Gunners'))],
        80: [((90, 5, 70, 15), 'Password', dict(span=True, fill=(246, 246, 246), align='c'))],
        82: [((56, 17, 60, 19), 'Army Name', dict(BIG, align='c'))], 83: [((56, 17, 60, 19), 'Army Name', dict(BIG, align='c'))],
        47: INPUT_UNIT, 73: INPUT_UNIT, 97: INPUT_UNIT,
        85: [((130, 26, 28, 13), 'Men'), ((187, 26, 28, 13), 'Type')],
        86: grid((49, 109, 163), (38, 53), 23, 11, [('Gold', 'Men', 'Guns'), ('Food', 'Drill', 'Def')]) +
            [((x, 98, 56, 42), t, dict(badge=True)) for x, t in ((4, 'Brave'), (84, 'Fiery'), (164, 'Wise'))] +
            [((x, 112, 20, 26), '', dict(badge=True)) for x in (59, 143, 226)],
        88: [((23, 98 + 15 * k, 31, 14), t, dict(span=True))
             for k, t in enumerate(('POL', 'WAR', 'LRN', 'CHA'))],
        93: CLASH_STAGE + [((104, 125, 52, 13), 'Normal', dict(align='c', span=True)),
                           ((181, 125, 40, 14), 'Hard', dict(align='c', span=True, fill=(140, 140, 148))),
                           ((25, 140, 59, 11), 'Fastest Clear', dict(room=90)), ((25, 155, 59, 11), 'Most Defeated', dict(room=90)),
                           ((25, 170, 59, 11), 'Fewest Lost', dict(room=90))],
        95: [CLASH_STAGE[0], ((25, 124, 83, 11), 'Clear Turns', dict(room=90)),
             ((25, 139, 47, 11), 'Men Defeated', dict(room=90)), ((25, 154, 47, 11), 'Men Lost', dict(room=90))],
        96: CLASH_STAGE,
        98: [((2, 2, 215, 11), 'Choose the officers, troops and unit types.'),
             ((8, 29, 89, 14), 'All Officers', dict(align='c')), ((111, 29, 30, 14), 'Men', dict(align='c')),
             ((157, 29, 91, 14), 'All Types', dict(align='c')), ((90, 147, 100, 16), 'Confirm', dict(align='c'))],

        41: [((34, 35, 66, 18), 'Message Speed', dict(clean=[52], room=90, **GLOW)),
             ((34, 92, 52, 18), 'Sound FX', dict(clean=[52], **GLOW))],
        110: rows(41, 4, 24, 70, 18, SETTINGS, clean=[52], room=90, **GLOW),
        113: rows(81, 61, 15, 63, 14, ['Daimyo', 'Provinces', 'Mode', 'Carry Over Stats', 'Battle Deaths', 'Lifespan'],
                  span=True, room=80, fill=(238, 238, 246)),
        115: rows(81, 61, 15, 63, 14, CONFIRM_ROWS, span=True, room=80, fill=(238, 238, 246)),
        126: [((142, 12, 44, 32), 'Cmdr', dict(badge=True, sy=1))] +
             [((38, 64, 23, 11), 'Men'), ((102, 64, 23, 11), 'Drill'), ((37, 78, 35, 11), 'Mobility'),
              ((102, 78, 23, 11), 'Morale'), ((26, 126, 23, 11), 'Loyal')] +
             grid((26, 74, 122, 170), (143,), 23, 11, [('POL', 'WAR', 'LRN', 'CHA')]) + [((26, 164, 23, 11), 'Apt.')],
        127: [((11, 50, 35, 11), 'Cmdr.'), ((138, 50, 35, 11), 'Cmdr.')] +
             grid((64, 138), (64, 78, 92, 106), 23, 11, [('Food', 'Food'), ('Men', 'Men'), ('Drill', 'Drill'), ('Morale', 'Morale')]) +
             [((11, 106, 35, 11), 'Tact.'), ((202, 106, 35, 11), 'Tact.'), ((166, 130, 23, 11), 'Land'),
              ((54, 144, 23, 11), 'Men'), ((54, 158, 23, 11), 'WAR'), ((191, 144, 35, 11), 'Mobility'),
              ((191, 158, 23, 11), 'Effect'), ((191, 172, 35, 11), 'Durability', dict(room=44))],
        128: [((8, 26, 96, 19), 'Uses Left', dict(span=True, outline=(41, 24, 8)))],

        45: [((86, 18, 47, 11), 'Required Skills', dict(room=120)), ((8, 102, 47, 11), 'Owned Skills', dict(room=54)),
             ((62, 101, 84, 13), '(Left/Owned/Land)')],
    },
}
BG['bg/GrpBG'][108] += BG['bg/GrpBG'][127]     # tutorial screenshot of the battle status screen

def medallion(obj, cell, lines, region, first=130, y=None, grow=1, edge=500):
    """Start-menu medallion (64x64, 8bpp): the calligraphy (palette entries >= first, with
    the dark outline next to them) inside region (x0, y0, x1, y1) is flattened to the
    medallion's dark ground, and lines are drawn in bold capitals, cream on black."""
    pal = obj.P.colors[obj.bank(cell):][:256]
    m = obj.pixels(cell)
    v = obj.get(m)
    x0, y0, x1, y1 = region
    inside = lambda p: x0 <= p[0] < x1 and y0 <= p[1] < y1
    mask = {p for p, c in v.items() if c >= first and inside(p)}
    for _ in range(grow):
        mask |= {(x + dx, y_ + dy) for (x, y_) in mask for dx in (-1, 0, 1) for dy in (-1, 0, 1)
                 if inside((x + dx, y_ + dy)) and v.get((x + dx, y_ + dy)) and lum(pal[v[(x + dx, y_ + dy)]]) < edge}
    for _ in range(2):               # close small holes (speckles of glow inside the strokes)
        mask |= {p for p in v if inside(p) and v[p] and p not in mask and
                 sum((p[0] + dx, p[1] + dy) in mask for dx in (-1, 0, 1) for dy in (-1, 0, 1)) >= 5}
    dark = Counter(c for c in v.values() if c and lum(pal[c]) < 600).most_common(1)[0][0]
    new = dict(v)
    for p in mask:
        new[p] = dark
    ms = [gfxtext.render(t.upper(), stretch=()) for t in lines]
    h = sum(len(mm) for mm in ms) + 2 * (len(ms) - 1)
    ty = (y if y is not None else 40) - h // 2
    fill = [nearest(pal, c) for c in [(255, 247, 222), (246, 230, 189), (230, 205, 148)]]
    black = nearest(pal, (0, 0, 0))
    for mm in ms:
        w = len(mm[0])
        if w > 60:
            raise ValueError('%s cell %d: %r too wide' % (obj.name, cell, lines))
        tx = 32 - w // 2
        pm = gfxtext.pad(mm, 1)
        ring = gfxtext.dilate(pm)
        for yy in range(len(pm)):
            for xx in range(len(pm[0])):
                p = (tx - 1 + xx, ty - 1 + yy)
                if p in new and pm[yy][xx]:
                    new[p] = fill[min(2, (yy - 1) * 3 // len(mm))]
                elif p in new and ring[yy][xx]:
                    new[p] = black
        ty += len(mm) + 2
    obj.put(m, new)

RED = dict(first=200, grow=2, edge=900)
BLUE = dict(first=170, grow=1, edge=700)
MEDALLIONS = {'obj/C256_ShoMainShita': [(0, ['Continue'], (0, 16, 32, 64)), (5, ['New', 'Game'], (0, 18, 48, 64)),
              (8, ['Clash'], (0, 12, 44, 64)), (11, ['New', 'Officer'], (0, 12, 64, 64)),
              (14, ['Link'], (0, 16, 48, 64)), (17, ['Tutorial'], (0, 18, 64, 64)),
              (20, ['Options'], (0, 10, 64, 64))],
              'obj/C256_SouhaMenuShita': [(0, ['Resume'], (0, 12, 64, 64), RED), (5, ['Continue'], (0, 16, 44, 64), RED),
                                          (10, ['New', 'Game'], (0, 18, 48, 64), RED)],
              'obj/C256_ShoOptShita': [(0, ['Officer', 'File'], (0, 30, 64, 64), BLUE),
                                       (3, ['SP', 'File'], (0, 26, 64, 64), BLUE),
                                       (8, ['Manual'], (0, 36, 64, 64), BLUE),
                                       (14, ['Erase', 'Data'], (0, 22, 64, 64), BLUE)],
              'obj/C256_ShinbuShita1': [(0, ['Create'], (0, 40, 64, 64), BLUE), (5, ['Re-edit'], (0, 40, 64, 64), BLUE),
                                        (10, ['Delete'], (0, 40, 64, 64), BLUE)]}

def tutor_scroll(obj, cell, chapter, name):
    """Tutorial chapter scroll: OAM 0 = text layer, OAM 4 = its dark halo (cleared)."""
    halo = obj.pixels(cell, oams=[4])
    obj.put(halo, {p: 0 for p in halo})
    o = obj.C.cells[cell][0]
    ox, oy = o['x'], o['y']
    label(obj, cell, chapter, box=(ox + 30, oy + 2, 34, 18), oams=[0], fill=(255, 255, 246), outline=(24, 16, 32))
    label(obj, cell, name, box=(ox + 0, oy + 18, 64, 22), oams=[0], fill=(255, 255, 246), outline=(24, 16, 32))

TUTOR = ['Prologue', 'Basics', 'Officers', 'Domestic', 'Diplomacy', 'Battle Prep', 'Battle Guide', 'In Battle',
         'Epilogue']

def chamfer(core, w, h):
    """3-4 chamfer distance (in thirds of a pixel) from every pixel to the set core."""
    INF = 1 << 20
    d = [[0 if (x, y) in core else INF for x in range(w)] for y in range(h)]
    for ys, xs, nb in ((range(h), range(w), ((-1, -1, 4), (0, -1, 3), (1, -1, 4), (-1, 0, 3))),
                       (range(h - 1, -1, -1), range(w - 1, -1, -1), ((1, 1, 4), (0, 1, 3), (-1, 1, 4), (1, 0, 3)))):
        for y in ys:
            for x in xs:
                for dx, dy, c in nb:
                    if 0 <= x + dx < w and 0 <= y + dy < h and d[y + dy][x + dx] + c < d[y][x]:
                        d[y][x] = d[y + dy][x + dx] + c
    return d

def skill_banner(u, text):
    """Tactic cut-in name (obj/HexSkillGrp entry, unpacked): 256 colours at 0x20, then 8bpp
    tiles at 0x220 as four 64x32 OAMs = two 128x32 frames (left half, right half), the second
    with a brighter glow. Per frame, the old kanji give a colour ramp: by depth inside the
    bright strokes and by distance outside them (the glow); English bold capitals (2x high,
    up to 2x wide) are repainted with the same ramps, centred."""
    pal = [((c & 31) * 255 // 31, (c >> 5 & 31) * 255 // 31, (c >> 10 & 31) * 255 // 31)
           for c in struct.unpack_from('<256H', u, 0x20)]
    W, H = 128, 32
    at = lambda f, x, y: 0x220 + (2 * f + x // 64) * 2048 + (y // 8 * 8 + x % 64 // 8) * 64 + y % 8 * 8 + x % 8
    g = gfxtext.render(text.upper(), gap=1, stretch=())
    for f in range(2):
        old = {(x, y): u[at(f, x, y)] for y in range(H) for x in range(W)}
        top = max(lum(pal[v]) for v in old.values() if v)
        core = {p for p, v in old.items() if v and lum(pal[v]) >= top * 0.8}
        out, inn = chamfer(core, W, H), chamfer({p for p in old if p not in core}, W, H)
        ramp_out, ramp_in = {}, {}
        for (x, y), v in old.items():
            ramp, k = (ramp_in, inn[y][x]) if (x, y) in core else (ramp_out, out[y][x])
            ramp.setdefault((k + 1) // 3, Counter())[v] += 1
        ramp_out = {k: c.most_common(1)[0][0] for k, c in ramp_out.items()}
        ramp_in = {k: c.most_common(1)[0][0] for k, c in ramp_in.items()}
        reach = max(k for k, v in ramp_out.items() if v)
        gw = min(2 * len(g[0]), W - 2 * reach - 2)
        m = [[r[x * len(r) // gw] for x in range(gw)] for r in g for _ in range(2)]
        ox, oy = (W - gw) // 2, (H - len(m)) // 2
        mask = {(ox + x, oy + y) for y, r in enumerate(m) for x, v in enumerate(r) if v}
        out, inn = chamfer(mask, W, H), chamfer({(x, y) for y in range(H) for x in range(W)} - mask, W, H)
        deep = max(ramp_in)
        for y in range(H):
            for x in range(W):
                if (x, y) in mask:
                    v = ramp_in[min((inn[y][x] + 1) // 3, deep)]
                else:
                    v = ramp_out.get((out[y][x] + 1) // 3, 0)
                u[at(f, x, y)] = v

def skill_banners(rom):
    import json
    rows = sorted(json.load(open(os.path.join(os.path.dirname(__file__), '..', 'tl', 'names_tactics.json'),
                                 encoding='utf-8')), key=lambda r: r['id'])
    name = 'obj/HexSkillGrp'
    parts = koeipack.split(rom.getFileByName(name + '.dat'), rom.getFileByName(name + 'Info.dat'))
    for i, p in enumerate(parts):
        u = bytearray(koeipack.unpack(p))
        skill_banner(u, rows[i]['en'])
        parts[i] = koeipack.pack(bytes(u))
    data, info = koeipack.join(parts, align=0x80)
    rom.files[rom.filenames.idOf(name + '.dat')] = data
    rom.files[rom.filenames.idOf(name + 'Info.dat')] = info

def big_label(obj, cell, oams, text, sx=2, sy=2):
    """Large banner text (bold capitals scaled sx x sy) drawn over the given OAMs of a
    cell, whose old art is cleared. Colours come from the old art: brightest = fill,
    darkest = outline, a middle one = glow ring."""
    m = obj.pixels(cell, oams=oams)
    old = obj.get(m)
    bank = obj.bank(cell, oams[0])
    col = lambda v: obj.P.colors[bank + v]
    common = [v for v, _ in Counter(v for v in old.values() if v).most_common(8)]
    fill = max(common, key=lambda v: lum(col(v)))
    dark = min(common, key=lambda v: lum(col(v)))
    glow = sorted(common, key=lambda v: lum(col(v)))[len(common) * 2 // 3]
    g = gfxtext.render(text.upper(), gap=1, stretch=())
    g = [[r[x // sx] for x in range(len(r) * sx)] for r in g for _ in range(sy)]
    pm = gfxtext.pad(g, 2)
    ring1 = gfxtext.dilate(pm)
    ring2 = gfxtext.dilate(ring1)
    xs = [p[0] for p in m]; ys = [p[1] for p in m]
    h, w = len(pm), len(pm[0])
    if w - 4 > max(xs) - min(xs) + 1:
        raise ValueError('%s cell %d: %r too wide' % (obj.name, cell, text))
    ox = (min(xs) + max(xs) + 1 - w) // 2
    oy = (min(ys) + max(ys) + 1 - h) // 2
    new = {p: 0 for p in m}
    for y in range(h):
        for x in range(w):
            p = (ox + x, oy + y)
            if p in new:
                if pm[y][x]:
                    new[p] = fill
                elif ring1[y][x]:
                    new[p] = dark
                elif ring2[y][x]:
                    new[p] = glow
    obj.unshare(cell, {m[p][0] for p in m}, (min(xs), min(ys), max(xs) - min(xs) + 1, max(ys) - min(ys) + 1))
    obj.put(obj.pixels(cell, oams=oams), new)

def badge_px(old, pal, text, where='', solid=False, sx=1, sy=2, hi=0.75, lo=450, mask=None, dy=0, clear=False, fill=None, outline=None, disc=None, warm=None, fringe=True, plain=False, ring=True):
    """Replace kanji painted on a picture (type badges, gem cards): pixels brighter than
    hi x the brightest or darker than lum lo (the kanji and its outline, plus a 1px fringe)
    are refilled from the nearest other pixel in their row; then bold capitals (scaled
    sx x sy) or a given mask are drawn in the kanji's own fill and outline colours,
    centred on where the kanji was. clear=True blanks the old art instead (a brush-drawn
    stamp replaced by a symbol). fill / outline = rgb overrides. disc=(cx, cy, r): the kanji
    sit inside a ring; the disc within it is refilled with its darkest colour. warm=k: the
    kanji are the pixels whose red exceeds their blue by k (orange text on a cool picture).
    Works on {(x, y): value} with palette pal and returns the new values; index 0 is
    transparent unless solid (BG images). An empty text only erases."""
    col = lambda v: pal[v]
    on = lambda v: solid or v
    top = max(lum(col(v)) for v in old.values() if on(v))
    bright = {p for p, v in old.items() if on(v) and lum(col(v)) >= top * hi} if warm is None else \
             {p for p, v in old.items() if on(v) and col(v)[0] - col(v)[2] > warm}
    dark = {p for p, v in old.items() if on(v) and lum(col(v)) < lo}
    auto = Counter(old[p] for p in bright).most_common(1)[0][0]
    edge = Counter(old[p] for p in dark).most_common(1)[0][0] if dark else min(
        (v for v in old.values() if on(v)), key=lambda v: lum(col(v)))
    fill = nearest(pal, fill) if fill else auto
    edge = nearest(pal, outline) if outline else edge
    near = lambda p, s: any((p[0] + dx_, p[1] + dy_) in s for dx_ in (-1, 0, 1) for dy_ in (-1, 0, 1))
    ink = bright | {p for p in dark if near(p, bright)}
    if fringe:
        ink |= {p for p in old if on(old[p]) and near(p, ink)}
    xs = [p[0] for p in ink]; ys = [p[1] for p in ink]
    cx, cy = (min(xs) + max(xs) + 1) / 2, (min(ys) + max(ys) + 1) / 2
    new = {p: 0 for p in old} if clear else dict(old)
    if disc:
        cx_, cy_, r = disc
        inside = {p for p in old if (p[0] - cx_) ** 2 + (p[1] - cy_) ** 2 <= r * r}
        new.update({p: edge for p in inside})
        ink = inside
        xs = [p[0] for p in ink]; ys = [p[1] for p in ink]
        cx, cy = (min(xs) + max(xs) + 1) / 2, (min(ys) + max(ys) + 1) / 2
    for (x, y) in ([] if clear or disc else ink):
        for d in range(1, 64):
            c = [q for q in ((x - d, y), (x + d, y)) if q in old and q not in ink]
            if c:
                new[(x, y)] = old[c[d % len(c)]]; break
    if not text and not mask:
        return new
    g = mask or (gfxtext.render_plain(text) if plain else gfxtext.render(text.upper(), gap=1, stretch=()))
    g = [r for r in g if any(r)] if plain else g   # small tags: no blank rows
    g = [[r[x // sx] for x in range(len(r) * sx)] for r in g for _ in range(sy)]
    pm = gfxtext.pad(g, 1) if ring else g
    ring = gfxtext.dilate(pm) if ring else [[False] * len(r) for r in pm]
    h, w = len(pm), len(pm[0])
    ox, oy = round(cx - w / 2), round(cy - h / 2) + dy
    ax = [p[0] for p in old]; ay = [p[1] for p in old]   # kept inside the area
    ox, oy = max(min(ax), min(ox, max(ax) + 1 - w)), max(min(ay), min(oy, max(ay) + 1 - h))
    for y in range(h):
        for x in range(w):
            p = (ox + x, oy + y)
            if p not in new:
                if pm[y][x] or ring[y][x]:
                    raise ValueError('%s: %r does not fit' % (where, text))
                continue
            if pm[y][x]:
                new[p] = fill
            elif ring[y][x]:
                new[p] = edge
    return new

def badge(obj, cell, text, box=None, **opt):
    """badge_px on an OBJ cell (box = part of it)."""
    m = obj.pixels(cell, box)
    bank = obj.bank(cell)
    pal = obj.P.colors[bank:bank + (256 if obj.T.bpp == 8 else 16)]
    new = badge_px(obj.get(m), pal, text, '%s cell %d' % (obj.name, cell), **opt)
    bx = [p[0] for p in m]; by = [p[1] for p in m]
    obj.unshare(cell, {m[p][0] for p in m}, (min(bx), min(by), max(bx) - min(bx) + 1, max(by) - min(by) + 1))
    obj.put(obj.pixels(cell, box), new)

def bg_merge(bg, i, box, text, pitch, n):
    """Join a row of n framed boxes (pitch px apart, starting at the box's x) into one
    field: the columns where two frames meet (bevels and gap) are copied from inside the box."""
    bx, by, bw, bh = box
    for k in range(1, n):
        for x in range(bx + pitch * k - 5, bx + pitch * k + 2):
            bg.put(i, {(x, y): v for (_, y), v in bg.get(i, (x - 7, by, 1, bh)).items()})

def bg_badge(bg, i, box, text, **opt):
    """badge_px on a box of a BG image."""
    bg.put(i, badge_px(bg.get(i, box), bg.image(i)[3][:256], text, '%s %d' % (bg.name, i), solid=True, **opt))


def tag(obj, cell, text, box, fill=None):
    """A tiny one-kanji tag: box (its inside) is refilled with its most common colour
    other than the kanji's (the brightest), and text drawn in plain letters (blank rows
    trimmed, no outline) in fill (default: the kanji's colour)."""
    bx, by, bw, bh = box
    ringm = obj.pixels(cell, (bx - 1, by - 1, bw + 2, bh + 2))
    m = {p: v for p, v in ringm.items() if bx <= p[0] < bx + bw and by <= p[1] < by + bh}
    vals = obj.get(ringm)
    pal = obj.P.colors[obj.bank(cell):][:256 if obj.T.bpp == 8 else 16]
    old = max((vals[p] for p in m), key=lambda v: lum(pal[v]))
    plate = Counter(vals[p] for p in m if vals[p] != old).most_common(1)[0][0]
    ink = nearest(pal, fill) if fill else old
    g = [r for r in gfxtext.render_plain(text) if any(r)]
    h, w = len(g), len(g[0])
    if w > bw or h > bh:
        raise ValueError('%s cell %d: %r is %dx%d, box %dx%d' % (obj.name, cell, text, w, h, bw, bh))
    ox, oy = bx + (bw - w + 1) // 2, by + (bh - h + 1) // 2
    new = {p: plate for p in m}
    for y in range(h):
        for x in range(w):
            if g[y][x]:
                new[(ox + x, oy + y)] = ink
    obj.unshare(cell, {t for t, _ in m.values()}, box)
    obj.put(obj.pixels(cell, box), new)

# tiny tags: Farming, Commerce, Industry, Courtier, Nanban, Buddhism, Ninja; Domestic / Military
TAGS = {'obj/SenryakuMainUe': [(c, t, (1, 1, 13, 9)) for c, t in enumerate(('Fa', 'Co', 'In', 'Ct', 'Nb', 'Bu', 'Ni'))] +
                              [(24, 'D', (13, 2, 9, 10)), (25, 'M', (13, 2, 9, 10))]}

HEART = [[c == '#' for c in r] for r in (
    '.##...##.',
    '####.####',
    '#########',
    '#########',
    '.#######.',
    '..#####..',
    '...###...',
    '....#....')]
def stack(*lines, gap=2):
    """Bold-capital lines centred over each other, as one mask (for badge())."""
    ms = [gfxtext.render(t.upper(), gap=1, stretch=()) for t in lines]
    w = max(len(m[0]) for m in ms)
    out = []
    for k, m in enumerate(ms):
        pad = (w - len(m[0])) // 2
        out += [[False] * pad + list(r) + [False] * (w - len(m[0]) - pad) for r in m]
        if k < len(ms) - 1:
            out += [[False] * w for _ in range(gap)]
    return out

def credit(obj, cell, lines, fill=(222, 222, 222), outline=(0, 0, 0)):
    """Staff-credit sprite: the cell's text lines (bands of rows with ink) are cleared and
    each redrawn in English, centred where the Japanese line was. A line starting with '*'
    is a role (bold capitals); '**' = bold capitals at double size (the closing company name)."""
    m = obj.pixels(cell)
    old = obj.get(m)
    ys = sorted({p[1] for p, v in old.items() if v})
    bands = []
    for y in ys:
        if bands and y - bands[-1][1] <= 2:
            bands[-1][1] = y
        else:
            bands.append([y, y])
    if len(bands) != len(lines):
        raise ValueError('%s cell %d: %d lines, %d given' % (obj.name, cell, len(bands), len(lines)))
    pal = obj.P.colors[obj.bank(cell):][:16]
    fv, ov = nearest(pal, fill), nearest(pal, outline)
    new = {p: 0 for p in old}
    for (y0, y1), t in zip(bands, lines):
        xs = [p[0] for p, v in old.items() if v and y0 <= p[1] <= y1]
        k = 2 if t.startswith('**') else 1
        fonts = [lambda u: gfxtext.render(u.upper(), gap=1, stretch=()), gfxtext.render_plain]
        for font in (fonts if t.startswith('*') else fonts[1:]):  # roles: bold, plain if too wide
            g = font(t.lstrip('*'))
            g = [[r[x // k] for x in range(len(r) * k)] for r in g for _ in range(k)]
            pm = gfxtext.pad(g, 1)
            ring = gfxtext.dilate(pm)
            h, w = len(pm), len(pm[0])
            ox, oy = (min(xs) + max(xs) + 1 - w) // 2, (y0 + y1 + 1 - h) // 2
            on = [(x, y) for y in range(h) for x in range(w) if pm[y][x] or ring[y][x]]
            d = next((d for d in sorted(range(-48, 49), key=abs)   # nearest sideways shift that fits
                      if all((ox + d + x, oy + y) in new for x, y in on)), None)
            if d is not None:
                break
        else:
            raise ValueError('%s cell %d: %r (%d px) does not fit' % (obj.name, cell, t, w))
        for x, y in on:
            new[(ox + d + x, oy + y)] = fv if pm[y][x] else ov
    bx = [p[0] for p in m]; by = [p[1] for p in m]
    hidden = {k: obj.pixels(cell, oams=[k]) for k in range(len(obj.C.cells[cell]))}
    tiles = {t for mk in hidden.values() for t, _ in mk.values()}
    obj.unshare(cell, tiles, (min(bx), min(by), max(bx) - min(bx) + 1, max(by) - min(by) + 1))
    for k in hidden:                  # OAMs overlap: clear the ones behind too
        mk = obj.pixels(cell, oams=[k])
        obj.put(mk, {p: 0 for p in mk})
    obj.put(obj.pixels(cell), new)

# staff roll (obj/Ending), one entry per cell; names romanized from the kanji (readings unconfirmed
# except Kou Shibusawa and Yoko Kanno)
CREDITS = [
    ['*General Producer', 'Kou Shibusawa'],
    ['*Producer', 'Ken Kitami'],
    ['*Director', 'Hiroyuki Koyama', '*Main Programmer', 'Makoto Takezawa'],
    ['*CG Director', 'Atsukichi Munechika', '*Sound Director', 'Genki Yamada'],
    ['*Game Planners', 'Shohei Yotoriyama', 'Takayuki Okuyama'],
    ['Sho Maeno'],
    ['*Programmer', 'Hiroshi Inaishi'],
    ['Hideomi Kayano'],
    ['*CG', 'Yura Nishizaki'],
    ['Shinsaku Ishii', 'Kazuhiro Yoshida'],
    ['Makiko Kiyoto'],
    ['Ryota Kamei', 'Masahiko Tabe'],
    ['*Movie', 'Tomomi Kiryu'],
    ['*MobileJOY', 'T. Yoshisaka'],
    ['Motohiro Nojiri'],
    ['*Manual', 'Masahiro Kato'],
    ['*PR', 'Yuka Kanefuri'],
    ['*Music', 'Yoko Kanno'],
    ['*Thanks', 'Bridge Co., Ltd.'],
    ['Fontworks Japan, Inc.'],
    ['Koeisha Co., Ltd.'],
    ['Beijing Koei Software Co., Ltd.'],
    ['**KOEI Co., Ltd.'],
]

def logo(obj, cell, lines, moves=(), oams=None, scale=2, fill=((255, 255, 16), (255, 213, 16), (222, 213, 8), (164, 131, 8)),
         outline=(0, 0, 0), glow=(90, 8, 0)):
    """A calligraphy logo replaced by bold capitals (scale x, lines centred under each
    other) with a gradient fill, black outline and a glow ring. moves = [(oam, dx)]
    first shifts OAMs; oams = the ones the text goes on (the others are only cleared)."""
    for k, dx in moves:
        o = obj.C.cells[cell][k]
        nitrogfx.set_oam(obj.C, o, x=o['x'] + dx)
    m = obj.pixels(cell)
    pal = obj.P.colors[obj.bank(cell):][:256]
    room = obj.pixels(cell, oams=oams)
    g = stack(*lines)
    g = [[r[x // scale] for x in range(len(r) * scale)] for r in g for _ in range(scale)]
    pm = gfxtext.pad(g, 2)
    r1 = gfxtext.dilate(pm); r2 = gfxtext.dilate(r1)
    h, w = len(pm), len(pm[0])
    xs = [p[0] for p in room]; ys = [p[1] for p in room]
    ox, oy = (min(xs) + max(xs) + 1 - w) // 2, (min(ys) + max(ys) + 1 - h) // 2
    fills = [nearest(pal, c) for c in fill]
    ov, gv = nearest(pal, outline), nearest(pal, glow)
    new = {p: 0 for p in m}
    for y in range(h):
        for x in range(w):
            p = (ox + x, oy + y)
            v = fills[min(len(fills) - 1, (y % (11 * scale + 2 * scale)) * len(fills) // (11 * scale + 2))] \
                if pm[y][x] else ov if r1[y][x] else gv if r2[y][x] else None
            if v is not None:
                if p not in room:
                    raise ValueError('%s cell %d: logo does not fit' % (obj.name, cell))
                new[p] = v
    obj.unshare(cell, {t for t, _ in m.values()}, (min(xs), min(ys), max(xs) - min(xs) + 1, max(ys) - min(ys) + 1))
    for k in range(len(obj.C.cells[cell])):
        mk = obj.pixels(cell, oams=[k])
        obj.put(mk, {p: 0 for p in mk})
    obj.put(obj.pixels(cell), new)

TYPES = ('Brave', 'Fiery', 'Wise')
LINK_ICON = dict(sy=1, warm=40, fill=(255, 197, 82), outline=(16, 24, 41))
BADGES = {'obj/C256_SenryakuMainUe': [(c, TYPES[c % 3]) for c in range(6)],
          'obj/SouhaHenseiShita': [(c, t, dict(sy=1, fringe=False, plain=True)) for c, t in ((19, 'F'), (20, 'B'), (21, 'W'))],
          'obj/C256_SouhaUe': [(c, t) for c, t in enumerate(('Fiery', 'Brave', 'Wise'))] +
                              [(7, '', dict(mask=stack('New', 'Record'), sy=1, disc=(26, 27, 20), outline=(0, 0, 0))),
                               (9, 'Goal Met!', dict(sx=2)), (10, 'Goal Lost!', dict(sx=2))],
          'obj/HexInfo256': [(20 + c, t) for c, t in enumerate(('Fiery', 'Brave', 'Wise'))],
          'obj/C256_SouhaSensekiShita': [(c, ('S', 'M', 'L', 'SP')[c % 4], dict(box=(8, 31, 33, 17), sy=1, lo=900, fill=(238, 230, 189)))
                                         for c in range(16)],
          'obj/ShoOptBFileUe': [(1, '', dict(mask=HEART, sx=2, clear=True))],
          'obj/C256_ShoOptBFileUe': [(c, t) for c, t in enumerate(TYPES)],   # officer screen corner
          # small tags (Farming, Commerce, Industry, Courtier, Nanban, Buddhism, Ninja), Domestic/Military, favourite
          'obj/SenryakuMainUe': [(22, '', dict(mask=HEART, sx=2, clear=True))],
          'obj/SouhaUe': [(61, '', dict(mask=HEART, sx=2, clear=True))],
          'obj/C256_TsuushinMenu': [(0, '', dict(LINK_ICON, box=(0, 30, 64, 30), mask=stack('Wi-Fi', 'Connect'))),
                                    (4, '', dict(LINK_ICON, box=(0, 30, 64, 30), mask=stack('DS', 'Wireless'))),
                                    (7, 'Link', dict(LINK_ICON, box=(0, 42, 44, 20)))]}

BIG = {'obj/HexChalSuc': [(0, [5], 'Goal'), (0, [0, 1, 2, 3, 4], 'Met!'), (2, [0, 1, 2, 3, 4, 5], 'Goal Met!'),
                          (4, [0, 1, 2, 3], 'Goal Met!'), (7, [0, 1, 2, 7], 'Goal Met!'), (8, [0, 1, 2, 3], 'Goal Met!')],
       'obj/HexChalFail': [(c, [0, 1, 2, 3], 'Goal Lost!') for c in (0, 1, 2)]}

# pack: [(cell, text, options)] -- one cell per tile set; palette variants follow
SMALL = dict(box=(4, 3, 78, 15))      # small buttons: the text runs over all five OAMs
PRESSED = dict(box=(5, 4, 78, 15))    # their pressed cells: same text OAMs 1px down-right, own frame tiles

def card_text(name):
    """Tactic card: two lines when the name is wide."""
    split = {'Misreport': 'Mis-\nreport', 'Firebombs': 'Fire-\nbombs', 'Furinkazan': 'Furin-\nkazan',
             'Onslaught': 'On-\nslaught'}
    if name in split:
        return split[name]
    w = len(gfxtext.render_plain(name)[0])
    return name.replace(' ', '\n', 1) if w > 30 and ' ' in name else name

def tactic_cards():
    import json
    rows = sorted(json.load(open(os.path.join(os.path.dirname(__file__), '..', 'tl', 'names_tactics.json'),
                                 encoding='utf-8')), key=lambda r: r['id'])
    return [(5 * r['id'], card_text(r['en']), dict(box=(2, 2, 48, 36), fill=(255, 255, 246), outline=(24, 16, 16)))
            for r in rows[:40]]

GOLD_TEXT = (255, 231, 156)
ICON = lambda x: dict(box=(x, 4, 48 - x, 13), flat=True, back=(49, 98, 98), fill=(222, 255, 255), outline=(16, 16, 24))   # pill buttons
ICON2 = lambda x: dict(box=(x, 3, 46 - x, 14), flat=True, dark=700, fill=(255, 255, 255), outline=(16, 16, 24))  # square ones
TAB = dict(box=(1, 2, 37, 15))
FLAT = dict(flat=True, dark=700)

HEX_BROWN, HEX_RED = (82, 41, 0), (90, 24, 0)   # battle button plates

SCENARIOS = [('1555', 'Turmoil of War'), ('1561', 'Time to Rise'), ('1571', 'Nobunaga Besieged'),
             ('1582', "Hegemon's Heir"), ('1557', 'Warlords Assemble'), ('1572', 'Grand Reshuffle')]
SCEN_TOP = [(c, y, dict(band=(0, 64), fill=GOLD_TEXT)) for c, (y, n) in enumerate(SCENARIOS)] + \
           [(c, n, dict(band=(64, 999), fill=GOLD_TEXT)) for c, (y, n) in enumerate(SCENARIOS)]

EDITS = {
    'obj/C256_ShinbuShita3': [(0, 'Done', dict(box=(5, 5, 22, 22), flat=True, fill=(99, 57, 24)))],
    'obj/HexUnit': [(128 + 5 * k, t, dict(box=(5, 4, 38, 16), oams=[0, 1])) for k, t in enumerate((
        'Tactic', 'Order', 'Retreat', 'Melee', 'Charge', 'Guns', 'Archery', 'Cannon', 'Province', 'Castle',
        'Demand', 'Betray', 'Sortie', 'Move', 'Open'))] +
        [(c, t, dict(box=(4, 4, 78, 14), clear=False, flat=True, back=HEX_RED if c == 218 else HEX_BROWN))
         for c, t in ((204, 'Save'), (207, 'Load'), (212, 'Settings'), (215, 'Manual'), (218, 'Quit Game'),
                      (221, 'Suspend'), (224, 'Objectives'))] +
        [(c, t, dict(box=(x, 4, 46 - x, 16), clear=False, flat=True, back=HEX_RED if c == 238 else HEX_BROWN)) for c, x, t in ((228, 14, 'Skip'), (230, 14, 'Top'), (232, 14, 'Wait'),
                                                            (234, 14, 'Cmd'), (236, 14, 'Info'), (238, 24, 'Stop'))],
    'obj/MainKunisentaku': [
        (0, 'Save', SMALL), (2, 'Save', PRESSED),
        (3, 'Load', SMALL), (5, 'Load', PRESSED),
        (8, 'Settings', SMALL), (10, 'Settings', PRESSED),
        (11, 'Manual', SMALL), (13, 'Manual', PRESSED),
        (14, 'SP Officers', SMALL), (16, 'SP Officers', PRESSED),
        (19, 'Demo Play', SMALL), (21, 'Demo Play', PRESSED),
        (22, 'Quit Game', SMALL), (24, 'Quit Game', PRESSED),
        (25, 'Suspend', SMALL), (27, 'Suspend', PRESSED),
        (28, 'Objectives', SMALL), (30, 'Objectives', PRESSED),
        (31, 'Retainers', SMALL), (33, 'Retainers', PRESSED),
        (34, 'Ronin', SMALL), (36, 'Ronin', PRESSED),
        (37, 'Persuade', SMALL), (39, 'Persuade', PRESSED),
        (40, 'Suppress', SMALL), (42, 'Suppress', PRESSED),
        (43, 'Accept', SMALL), (45, 'Accept', PRESSED),
        (46, 'Refuse', SMALL), (48, 'Refuse', PRESSED),
        (49, 'Capture', SMALL), (51, 'Capture', PRESSED),
        (52, 'Direct', SMALL), (54, 'Direct', PRESSED),
        (55, 'Military', SMALL), (57, 'Military', PRESSED),
        (58, 'Domestic', SMALL), (60, 'Domestic', PRESSED),
        (61, 'Recruit', SMALL), (63, 'Recruit', PRESSED),
        (64, 'Release', SMALL), (66, 'Release', PRESSED),
        (67, 'Execute', SMALL), (69, 'Execute', PRESSED),
        (70, 'Normal', SMALL), (72, 'Normal', PRESSED),
        (73, 'Hard', SMALL), (75, 'Hard', PRESSED),
        (122, 'List', ICON2(25)), (124, 'Prov.', ICON2(17)), (126, 'Confirm', ICON2(13)), (128, 'Info', ICON2(17))],
    'obj/C256_ShinbuShita2': [(c, t, dict(box=(4, 3, 51, 17), flat=True, dark=700, outline=(16, 16, 24), pool=c,
                                          fill=(255, 222, 115))) for c, t in (
        (12, 'Low'), (13, 'Normal'), (14, 'High'), (15, 'Low'), (16, 'Normal'), (17, 'High'), (18, 'Brave'),
        (19, 'Fiery'), (20, 'Wise'))] +
        [(c, t, dict(box=(3, 3, 29, 17), flat=True, dark=700, outline=(16, 16, 24), pool=c, fill=(255, 222, 115)))
         for c, t in ((21, 'Normal'), (22, 'Fiery'), (23, 'Noble'), (24, 'Monk'), (25, 'Ninja'))] +
        [(c, t, dict(box=(1, 2, 23, 16), flat=True, fill=(255, 255, 255))) for c, t in ((26, 'Given'), (27, 'Army'))],
    'obj/C256_ShoOptBFileUe': [(c, t, dict(box=(4, 3, 136, 17), flat=True, dark=700, outline=(16, 16, 24), pool=c,
                                           fill=(255, 255, 255))) for c, t in ((3, 'Officer File'), (4, 'SP Officer File'))],
    'obj/TsuushinShita1': [(0, 'Confirm', dict(band=(30, 999))), (3, 'Download Officers'), (6, 'Wi-Fi Settings'),
                           (9, 'Send Officer Data'), (12, 'Receive Officer Data'), (15, 'Connect'),
                           (28, 'Quit', ICON2(25))],
    'obj/HexInfoTensei': [(10, 'Atk', dict(box=(3, 3, 15, 14), flat=True, back=(131, 57, 0), fill=(238, 230, 230),
                                           outline=(32, 24, 16), pool=10)),
                          (11, 'Def', dict(box=(3, 3, 15, 14), flat=True, back=(0, 123, 106), fill=(238, 230, 230),
                                           outline=(32, 24, 16), pool=11))],
    'obj/HexInfo16': [(28, 'Atk', dict(box=(3, 3, 15, 14), flat=True, back=(131, 57, 0), fill=(238, 230, 230),
                                       outline=(32, 24, 16), pool=28)),
                      (29, 'Def', dict(box=(3, 3, 15, 14), flat=True, back=(0, 123, 106), fill=(238, 230, 230),
                                       outline=(32, 24, 16), pool=29)),
                      (44, 'day', dict(box=(0, 0, 32, 16), align='l', clear=True)),
                      (45, 'h', dict(box=(0, 0, 16, 16), align='l', clear=True))],
    'obj/HexSelSen': tactic_cards() + [(200, 'Confirm', dict(band=(30, 999))), (202, 'Confirm', dict(band=(30, 999))), (205, 'Clear', ICON2(17))],
    'obj/ComTutor': [(6, 'Quit', ICON2(25)), (8, 'Log', ICON2(18)), (10, 'End Log', ICON2(13)), (12, 'Next', ICON2(18)),
                     (14, 'Back', ICON2(18))],
    'obj/C256_ShoOptShita': [(c, t, dict(box=(5, 4, 42, 19), span=True, fill=(238, 238, 255), outline=(16, 24, 48)))
                             for c, t in ((17, 'Strategy'), (18, 'Battle'), (19, 'Tactics'))],
    'obj/ShoOptShita': [(0, 'Confirm', dict(band=(30, 999))), (78, 'All'), (104, 'Delete', ICON2(17))],
    'obj/ButaiHenseiShita': [(0, 'Confirm', dict(band=(30, 999))), (5, 'All Officers', FLAT), (10, 'Men', FLAT), (12, 'Men', FLAT),
                             (15, 'All Types', FLAT),
                             (64, 'Auto', dict(ICON2(17), box=(17, 3, 29, 14))), (68, 'Foot'), (73, 'Horse'), (78, 'Guns')],
    'obj/SouhaHenseiShita': [(0, 'Confirm', dict(band=(60, 999))), (5, 'All Officers', dict(box=(3, 2, 86, 14), oams=[0, 1])),
                             (7, 'All Officers', dict(box=(3, 2, 86, 15), oams=[0, 1])), (17, 'Auto', dict(ICON2(17), box=(17, 3, 29, 14)))],
    'obj/SaveLoadShita': [(c, 'No Data', dict(box=(36, 6, 128, 32))) for c in (3, 25)] +
                         [(c, 'Play Time', dict(box=(100, 20, 64, 16))) for c in (14, 36)] +
                         [(44, 'Latest', dict(box=(0, 0, 40, 24)))],
    'obj/C256_SouhaUe': [(8, 'Hard', dict(box=(0, 0, 40, 16), clear=False, flat=True, back=(115, 98, 156), fill=(255, 255, 255))),
                         (11, 'Hard', dict(box=(0, 0, 48, 16), clear=False, flat=True, back=(230, 197, 213), fill=(255, 255, 255),
                                           outline=(115, 98, 205)))],
    'obj/SouhaUe': [(0, 'Clear!', dict(band=(), fill=GOLD_TEXT))] + [(c, t, dict(band=(), fill=GOLD_TEXT)) for c, t in enumerate((
        'Old Beard & Onikuro', 'One-Eyed Dragon Burns', 'Northern Schemer', 'Terror! The War God Nears',
        "Demon Yoshishige Attacks", 'Feast of Old Generals', "Odawara's High Walls", 'Temple Fortress',
        'Furinkazan Nightmare', 'Blood Wind! Okehazama', 'Sanada Chronicle', 'Field of Treason',
        'Too Good for the Tanuki', 'The Viper and His Son', 'Fall, Demon King', 'With Father',
        'Rokkaku Ninja Bandits', 'Shogun Strikes Back', 'Great Evil Erupts', 'RUN&GUN', 'Tea Battle at Daigo',
        'Schemer and Ironclads', 'Grant Me All Hardships', 'Three Strong Arrows', "The Dandy's Wrath",
        'An Elegant War', 'Ah, the Maiden Prince', 'First Cannon', 'Reins of the Red Bear', 'Heroes of the South'),
        31)],
    'obj/ShinbuShita': [(0, 'Confirm', dict(band=(30, 999))), (5, 'Face'), (8, 'Name'), (11, 'Reading'), (14, 'Stats'), (17, 'Aptitude'),
                        (20, 'Age'), (23, 'Parent'), (28, 'Affinity'), (31, 'Traits'), (128, 'Delete', ICON2(17))],
    'obj/SouhaShita': [(0, 'Confirm', dict(band=(30, 999))), (5, 'Check', dict(pool='chk')), (37, 'Clear', ICON2(17))],
    'obj/ShoMainUe': SCEN_TOP, 'obj/SaveLoadUe': SCEN_TOP,
    'obj/Common': [(4, 'Yes', dict(fill=(255, 255, 255))), (7, 'No', dict(fill=(255, 255, 255))),
                   (10, 'Menu', ICON2(24)), (13, 'Back', ICON2(17))],
    'obj/SenryakuMainUe': [(c, t, dict(widen=(0, 32, 0), box=(0, 0, 32, 16))) for c, t in (
        (17, 'Daimyo'), (18, 'Lord'), (19, 'Advisor'), (20, 'Officer'), (21, 'Ronin'))],
    'obj/SenryakuHannyou': [(c, t, *o) for c, t, *o in (
        (0, 'Daimyo'), (2, 'Amity'), (4, 'Ally'), (6, 'Lands'), (8, 'Gens'), (10, 'Men'), (12, 'Gold', dict(widen=(0, 32, -8))), (14, 'Food'),
        (16, 'Guns'), (18, 'Tea'), (20, 'Ironclad'), (22, 'Prov.'), (24, 'Clan'), (26, 'Lord'),
        (36, 'Drill'), (40, 'Law'), (42, 'Koku'), (44, 'Comm'), (46, 'Tech'), (48, 'Skill'),
        (50, 'Cult'), (52, 'Line'), (54, 'Def'), (56, 'Done'), (58, 'Auto'), (60, 'Reading'), (62, 'Name'),
        (66, 'Loc.'), (68, 'Rank'), (70, 'Loyal'), (72, 'POL'), (74, 'WAR'), (76, 'LRN'), (78, 'CHA'), (80, 'Foot'),
        (82, 'Horse'), (86, 'Age'), (88, 'Type'), (94, 'Done'), (96, 'Born'), (98, 'Recv.'), (100, 'Sorties'),
        (104, 'Kind'), (106, 'Grade'), (108, 'Price'), (110, 'Owner'), (112, 'Tactic'), (114, 'Req. Skill'),
        (116, 'Clash'), (118, 'Parent', dict(widen=(0, 32, -8))),
        (126, 'Confirm'), (205, 'Sell Rice'), (210, 'Buy Rice'), (215, 'Guns'), (220, 'Tea Ware'), (225, 'Grant'),
        (230, 'Seize'), (240, 'Ironclad'), (245, 'Diplomacy'), (250, 'Domain'), (255, 'Officers'), (275, 'Castle'),
        (280, 'Gold'), (285, 'Food'), (295, 'Men'), (300, 'Leader'), (303, 'Men'), (306, 'Type'),
        (308, 'Type'), (340, 'Confirm', dict(pool='green')), (349, 'Direct'), (352, 'Domestic'),
        (355, 'Military'), (360, 'Vassals'), (363, 'Ronin'),
        (366, 'Confirm', dict(pool='green')), (302, 'Leader'), (305, 'Men'),
        (170, 'Sort', dict(box=(17, 3, 29, 14), flat=True)), (338, 'Auto', dict(box=(17, 3, 29, 14), flat=True)),
        (358, 'Check', dict(box=(17, 3, 29, 14), flat=True)), (172, 'All', dict(box=(25, 3, 21, 14), flat=True)),
        (174, 'Swap', dict(box=(25, 3, 21, 14), flat=True)), (176, 'List', dict(box=(25, 3, 21, 14), flat=True)),
        (185, 'Min', dict(box=(25, 3, 32, 16))), (190, 'Half', dict(box=(25, 3, 32, 16))),
        (195, 'Max', dict(box=(25, 3, 32, 16))), (200, 'Half', dict(box=(25, 3, 32, 16))))],
    'obj/ShoMainShita': [(c, y, dict(box=(5, 3, 64, 16), align='l', fill=GOLD_TEXT)) for c, y in ((1, '1555'), (4, '1561'), (7, '1571'), (10, '1582'),
                                                                   (13, '1557'), (16, '1572'))] +
                        [(c, t, dict(band=(70, 999), fill=GOLD_TEXT)) for c, t in ((1, 'Turmoil of War'), (4, 'Time to Rise'),
                                                                  (7, 'Nobunaga Besieged'), (10, "Hegemon's Heir"),
                                                                  (13, 'Warlords Assemble'), (16, 'Grand Reshuffle'))] +
                        [(c, t, dict(band=(), fill=GOLD_TEXT)) for c, t in ((19, 'Add New Officers'), (22, 'Set Location/Status'),
                                                            (27, 'Change All Ages'), (32, 'Reset'), (37, 'Add SP Officers'))] +
                        [(50, 'Change Daimyo', dict(band=(30, 999))), (53, 'Confirm', dict(band=(30, 999)))] +
                        [(0, 'Press a button', dict(box=(0, 0, 200, 19), fill=(156, 246, 164), outline=(57, 41, 164), pool=1)),
                         (0, 'or touch the lower screen', dict(box=(0, 29, 200, 18), fill=(156, 246, 164),
                                                               outline=(57, 41, 164), pool=2))],
    'obj/C256_ShoMainShita': [(c, t, dict(box=(3, 3, 42, 15), dark=700, flat=True, outline=(16, 16, 24), pool=c,
                                         fill=(255, 222, 115) if c % 2 else (189, 197, 213))) for c, t in (
        (23, 'Beginner'), (24, 'Beginner'), (25, 'Standard'), (26, 'Standard'), (27, 'Easy'), (28, 'Easy'),
        (29, 'Hard'), (30, 'Hard'), (31, 'Normal'), (32, 'Normal'), (33, 'Wait'), (34, 'Wait'),
        (35, 'On'), (36, 'On'), (37, 'Off'), (38, 'Off'), (39, 'On'), (40, 'On'), (41, 'Off'), (42, 'Off'),
        (43, 'On'), (44, 'On'), (45, 'Off'), (46, 'Off'))],
    'obj/SenryakuMainShita': [
        (253, 'Advice', ICON(19)), (256, 'Gens', ICON(19)), (259, 'Map', ICON(19)), (262, 'Auto', ICON(26)),
        (302, 'Join', ICON2(18)), (304, 'Log', ICON2(18)), (306, 'End Log', ICON2(13)), (308, 'Next', ICON2(18)),
        (310, 'Back', ICON2(18)), (316, 'Quit', ICON2(25)),
        (266, 'Domestic', dict(TAB, box=(3, 2, 39, 15))), (267, 'Military', TAB), (268, 'Staff', TAB), (269, 'Foreign', TAB), (270, 'Intel', TAB),
        (286, '/', dict(box=(0, 0, 16, 16))), (287, ' ', dict(box=(0, 0, 16, 16))),
        (288, 'Spr', dict(box=(0, 0, 16, 16))), (289, 'Sum', dict(box=(0, 0, 16, 16))),
        (290, 'Aut', dict(box=(0, 0, 16, 16))), (291, 'Win', dict(box=(0, 0, 16, 16))),
        (0, 'Domestic'),
        (5, 'Military'),
        (10, 'Staff'),
        (15, 'Foreign'),
        (20, 'Intel'),
        (25, 'End Turn'),
        (30, 'Cultivate'),
        (35, 'Commerce'),
        (40, 'Order'),
        (45, 'Tech'),
        (50, 'Fortify'),
        (55, 'Gold Mine'),
        (60, 'Trade'),
        (65, 'Move'),
        (70, 'Transport'),
        (75, 'Battle'),
        (80, 'Joint War'),
        (85, 'Draft'),
        (90, 'Train'),
        (95, 'Produce'),
        (100, 'Tactics'),
        (105, 'Recruit'),
        (110, 'Reward'),
        (115, 'Tea Ware'),
        (120, 'Tea Party'),
        (125, 'Appoint'),
        (130, 'Banish'),
        (135, 'Spy'),
        (140, 'Subvert'),
        (145, 'Rumor'),
        (150, 'Hostility'),
        (155, 'Tribute'),
        (160, 'Alliance'),
        (165, 'Demand'),
        (170, 'Sever'),
        (175, 'Daimyo'),
        (178, 'Lands'),
        (181, 'Diplomacy'),
        (184, 'Domain'),
        (187, 'Retainers'),
        (190, 'Tea Ware'),
        (195, 'Back'),
        (198, 'Save', SMALL),
        (200, 'Save', PRESSED),
        (201, 'Load', SMALL),
        (203, 'Load', PRESSED),
        (206, 'Settings', SMALL),
        (208, 'Settings', PRESSED),
        (209, 'Manual', SMALL),
        (211, 'Manual', PRESSED),
        (212, 'SP Officers', SMALL),
        (214, 'SP Officers', PRESSED),
        (217, 'Demo Play', SMALL),
        (219, 'Demo Play', PRESSED),
        (220, 'Quit Game', SMALL),
        (222, 'Quit Game', PRESSED),
        (223, 'Retainers', SMALL),
        (225, 'Retainers', PRESSED),
        (226, 'Ronin', SMALL),
        (228, 'Ronin', PRESSED),
        (229, 'Persuade', SMALL),
        (231, 'Persuade', PRESSED),
        (232, 'Suppress', SMALL),
        (234, 'Suppress', PRESSED),
        (235, 'Accept', SMALL),
        (237, 'Accept', PRESSED),
        (238, 'Refuse', SMALL),
        (240, 'Refuse', PRESSED),
        (241, 'Capture', SMALL),
        (243, 'Capture', PRESSED),
        (244, 'Recruit', SMALL),
        (246, 'Recruit', PRESSED),
        (247, 'Release', SMALL),
        (249, 'Release', PRESSED),
        (250, 'Execute', SMALL),
        (252, 'Execute', PRESSED),
    ],
}

def merged(images, extra):
    out = {i: list(v) for i, v in images.items()}
    for i, labels in extra.items():
        out.setdefault(i, []).extend(labels)
    return out

EDITS['obj/ShoInpNum'] = [e for e in EDITS['obj/SenryakuHannyou'] if e[0] <= 340]
EDITS['obj/ShoInpNum'] += [(c, t, dict(box=(20, 3, 43, 16), oams=[0, 1], clear=False, flat=True, back=(65, 41, 16))) for c, t in ((369, 'Min'), (374, 'Half'), (379, 'Max'), (384, 'Half'))]

def apply(rom):
    for name, edits in EDITS.items():
        obj = Obj(rom, name)
        edits = [(cell, text, dict(opt[0]) if opt else {}) for cell, text, *opt in edits
                 if cell < len(obj.C.cells) and obj.C.cells[cell]]
        pooled = {}
        key = lambda opt: opt.get('pool') or (opt['box'][2:], tuple(opt.get('oams') or ()))
        for cell, text, opt in edits:
            if 'widen' in opt:
                obj.widen(cell, *opt.pop('widen'))
        for cell, text, opt in edits:
            if 'band' in opt:
                opt['box'] = obj.band(cell, *opt.pop('band'))
            opt.setdefault('box', obj.text_box(cell))
            for y, c in counts(obj, cell, opt['box'], opt.get('oams'), opt.get('per_pixel')).items():
                pooled.setdefault(key(opt), {}).setdefault(y, Counter()).update(c)
        for cell, text, opt in edits:
            label(obj, cell, text, rows=pooled[key(opt)], **opt)
        obj.save()
    for name, cells in OBJ_TITLES.items():
        obj = Obj(rom, name)
        for cell, text in cells.items():
            obj_title(obj, cell, text)
        obj.save()
    for name, items in BIG.items():
        obj = Obj(rom, name)
        for cell, oams, text in items:
            big_label(obj, cell, oams, text)
        obj.save()
    obj = Obj(rom, 'obj/C256_SouhaMenuUe')     # 群雄争覇: the game places the 覇 block (OAMs 2, 3) itself,
    logo(obj, 1, ['Clash of', 'Warlords'], moves=[(0, 40), (1, 40)], oams=[0, 1])  # so the text goes on 群雄争, centred
    obj.save()
    obj = Obj(rom, 'obj/Ending')
    for cell, lines in enumerate(CREDITS):
        credit(obj, cell, lines)
    obj.save()
    for name, items in TAGS.items():
        obj = Obj(rom, name)
        for cell, text, box in items:
            tag(obj, cell, text, box)
        obj.save()
    for name, items in BADGES.items():
        obj = Obj(rom, name)
        for cell, text, *opt in items:
            badge(obj, cell, text, **(opt[0] if opt else {}))
        obj.save()
    skill_banners(rom)
    obj = Obj(rom, 'obj/C256_TutorShita')
    for k, t in enumerate(TUTOR * 2):
        tutor_scroll(obj, 3 * k, 'Ch.%d' % (k % 9 + 1), t)
    obj.save()
    for name, meds in MEDALLIONS.items():
        obj = Obj(rom, name)
        for cell, lines, region, *opt in meds:
            medallion(obj, cell, lines, region, **(opt[0] if opt else {}))
        obj.save()
    BG['bg/GrpBG'] = merged(BG['bg/GrpBG'], {i: [(BANNER, t, T)] for i, t in TITLES.items()})
    for name, images in BG.items():
        bg = Bg(rom, name)
        for i, labels in images.items():
            for box, text, *opt in labels:
                opt = dict(opt[0]) if opt else {}
                draw = bg_title if opt.pop('title', False) else bg_badge if opt.pop('badge', False) else \
                    bg_merge if 'pitch' in opt else bg_label
                draw(bg, i, box, text, **opt)
        bg.save()
    return len(EDITS) + len(BG)

if __name__ == '__main__':          # gfx.py out.nds: apply to the clean ROM only (quick preview)
    import ndspy.rom
    rom = ndspy.rom.NintendoDSRom.fromFile(os.path.join(os.path.dirname(__file__), '..', 'nobunaga_ds_2.nds'))
    apply(rom)
    rom.saveToFile(sys.argv[1])
