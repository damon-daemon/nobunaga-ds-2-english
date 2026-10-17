"""usage: bgboxes.py out.png image [pack=bg/GrpBG] [rom]
Finds text-like clusters (pixels much brighter or darker than their 7x7 surroundings),
prints their boxes (x, y, w, h) and saves a 3x zoom with numbered boxes."""
import sys, os; sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import ndspy.rom, gfx
from PIL import Image, ImageDraw
out, i = sys.argv[1], int(sys.argv[2])
pack = sys.argv[3] if len(sys.argv) > 3 else 'bg/GrpBG'
rom = ndspy.rom.NintendoDSRom.fromFile(sys.argv[4] if len(sys.argv) > 4 else 'nobunaga_ds_2.nds')
bg = gfx.Bg(rom, pack)
u, w, off, pal = bg.image(i)
h = (len(u) - off) // w
L = [[gfx.lum(pal[u[bg.at(i, x, y)]]) for x in range(w)] for y in range(h)]
import statistics
mask = [[False] * w for _ in range(h)]
for y in range(h):
    for x in range(w):
        nb = [L[yy][xx] for yy in range(max(0, y - 3), min(h, y + 4)) for xx in range(max(0, x - 3), min(w, x + 4))]
        med = statistics.median(nb)
        mask[y][x] = L[y][x] - med > 700
seen = [[False] * w for _ in range(h)]
boxes = []
for y in range(h):
    for x in range(w):
        if mask[y][x] and not seen[y][x]:
            st = [(x, y)]; seen[y][x] = True; pts = []
            while st:
                a, b = st.pop(); pts.append((a, b))
                for dy in range(-2, 3):
                    for dx in range(-3, 4):
                        c, d = a + dx, b + dy
                        if 0 <= c < w and 0 <= d < h and mask[d][c] and not seen[d][c]:
                            seen[d][c] = True; st.append((c, d))
            xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
            bw, bh = max(xs) - min(xs) + 1, max(ys) - min(ys) + 1
            if 6 <= bh <= 16 and bw >= 5 and len(pts) >= 12:
                boxes.append((min(xs), min(ys), bw, bh))
boxes.sort(key=lambda b: (b[1] // 6, b[0]))
im = Image.new('RGB', (w, h)); im.putdata([pal[u[bg.at(i, x, y)]] for y in range(h) for x in range(w)])
im = im.resize((w * 3, h * 3), Image.NEAREST); d = ImageDraw.Draw(im)
for n, (x, y, bw, bh) in enumerate(boxes):
    d.rectangle((x * 3 - 1, y * 3 - 1, (x + bw) * 3, (y + bh) * 3), outline=(255, 0, 255))
    d.text((x * 3, y * 3 - 11), str(n), fill=(0, 255, 255))
    print(n, (x, y, bw, bh))
im.save(out)
