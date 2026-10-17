"""usage: bgshow.py out.png rom.nds bg/<Pack> i [i...]   (2x, original left, edited right if rom != clean)"""
import sys, os; sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import ndspy.rom, gfx
from PIL import Image

def render(rom, pack, i):
    b = gfx.Bg(rom, pack); u, w, off, pal = b.image(i)
    h = (len(u) - off) // w
    im = Image.new('RGB', (w, h))
    im.putdata([pal[u[b.at(i, x, y)]] for y in range(h) for x in range(w)])
    return im

clean = ndspy.rom.NintendoDSRom.fromFile('nobunaga_ds_2.nds')
built = ndspy.rom.NintendoDSRom.fromFile(sys.argv[2])
ims = [(render(clean, sys.argv[3], int(i)), render(built, sys.argv[3], int(i))) for i in sys.argv[4:]]
W = max(a.size[0] for a, _ in ims); H = sum(a.size[1] for a, _ in ims)
M = Image.new('RGB', (2 * W + 4, H + 4 * len(ims))); y = 0
for a, b in ims:
    M.paste(a, (0, y)); M.paste(b, (W + 4, y)); y += a.size[1] + 4
M.resize((M.size[0] * 2, M.size[1] * 2), 0).save(sys.argv[1])
