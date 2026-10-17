"""montage.py out.png in1.png in2.png ... [--top|--bottom] : tile screenshots 2x for viewing"""
import sys
from PIL import Image
args = [a for a in sys.argv[2:] if not a.startswith('--')]
part = {'--top': (0, 0, 256, 192), '--bottom': (0, 192, 256, 384)}.get(next((a for a in sys.argv if a.startswith('--')), ''), None)
ims = [Image.open(a) for a in args]
if part:
    ims = [im.crop(part) for im in ims]
w, h = ims[0].size; cols = min(len(ims), 2 if h > 200 else 3)
rows = (len(ims) + cols - 1) // cols
out = Image.new('RGB', (cols * w, rows * h))
for i, im in enumerate(ims):
    out.paste(im, (i % cols * w, i // cols * h))
out.resize((out.width * 2, out.height * 2), Image.NEAREST).save(sys.argv[1])
