"""waitturns.py outdir n : in a battle, end every unit's turn with Wait for n steps,
closing the command menu when it is open, and save a screenshot whenever the
battle clock changes (to check each new turn asks for orders again)."""
import os, subprocess, sys
from PIL import Image
E = os.path.dirname(os.path.abspath(__file__))
out, n = sys.argv[1], int(sys.argv[2])
press = lambda *k: subprocess.run([E + '/press.sh', '/dev/null', *k])
last = None
for i in range(n):
    f = os.path.join(out, 'wt_now.png')
    subprocess.run([E + '/shot.sh', f])
    im = Image.open(f).convert('RGB')
    clock = im.crop((0, 0, 96, 22)).tobytes()
    if clock != last:
        im.save(os.path.join(out, 'wt_%03d.png' % i)); last = clock
    r, g, b = im.getpixel((240, 375))
    if r < 80:                             # 'B Back' (dark) instead of 'START Menu': a menu is open
        press('z', 'w')
    else:
        press('z', 'w', 'Left', 'x', 'w', 'w')
