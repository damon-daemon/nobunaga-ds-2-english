"""usage: labels.py out.png obj/<Pack> [scale]
Montage of one cell per distinct label tile set (the number = cell to name in gfx.EDITS)."""
import sys, os; sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import ndspy.rom, nitrogfx, gfx
from PIL import Image, ImageDraw
rom = ndspy.rom.NintendoDSRom.fromFile(sys.argv[3] if len(sys.argv) > 3 and sys.argv[3].endswith('.nds') else 'nobunaga_ds_2.nds')
o = gfx.Obj(rom, sys.argv[2])
seen, reps = set(), []
for i, oams in enumerate(o.C.cells):
    if not oams: continue
    lead = o.lead(i)
    if lead:
        key = tuple(sorted((x['tile'], x['w'], x['h']) for x in lead))
    else:
        big = max(range(len(oams)), key=lambda k: oams[k]['w'] * oams[k]['h'])
        key = tuple(sorted(x['tile'] for k, x in enumerate(oams) if k != big or len(oams) == 1))
    if key in seen: continue
    seen.add(key); reps.append(i)
ims = [(i, nitrogfx.render_cell(o.C, o.T, o.P, i)) for i in reps]
W = 1000; x = y = rowh = 0; pos = []
for i, im in ims:
    w, h = max(im.size[0], 20) + 6, im.size[1] + 13
    if x + w > W and x: x = 0; y += rowh; rowh = 0
    pos.append((x, y)); x += w; rowh = max(rowh, h)
M = Image.new('RGB', (W, y + rowh), (60, 60, 90)); d = ImageDraw.Draw(M)
for (i, im), (x, y) in zip(ims, pos):
    d.text((x, y), str(i), fill='yellow'); M.paste(im, (x, y + 11), im)
M.save(sys.argv[1]); print(len(reps), 'label sets')
from collections import Counter
use = Counter((x['tile'], x['w'], x['h']) for oams in o.C.cells for x in oams)
with open(os.path.splitext(sys.argv[1])[0] + '.txt', 'w') as f:
    for i in reps:
        f.write('%d: %s\n' % (i, ' '.join('%d,%d %dx%d t%d%s' % (x['x'], x['y'], x['w'], x['h'], x['tile'],
                '*%d' % use[(x['tile'], x['w'], x['h'])] if use[(x['tile'], x['w'], x['h'])] > 1 else '') for x in o.C.cells[i])))
