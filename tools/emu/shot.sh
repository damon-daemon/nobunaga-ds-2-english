#!/bin/bash
# shot.sh out.png : capture melonDS, crop the two DS screens and sample to native 256x384.
# The screens are centred below the menu bar (MB px), scaled to fit the window.
G=$(hyprctl clients -j | python3 -I -c "import json,sys; c=[w for w in json.load(sys.stdin) if 'melon' in w['class'].lower()][0]; print('%d,%d %dx%d'%(*c['at'],*c['size']))")
T=$(mktemp --suffix .png); timeout 10 grim -g "$G" $T
$(dirname "$0")/../../.venv/bin/python -I - "$T" "$1" <<'PY'
import sys
from PIL import Image
im = Image.open(sys.argv[1]).convert('RGB'); W, H = im.size
MB = 24                                   # melonDS menu bar height (window px)
s = min(W / 256, (H - MB) / 384)
x0 = (W - 256 * s) / 2; y0 = MB + ((H - MB) - 384 * s) / 2
# box-filter: the window scale is not an integer, point sampling drops glyph columns
out = im.resize((256, 384), Image.BOX, box=(x0, y0, x0 + 256 * s, y0 + 384 * s))
out.save(sys.argv[2])
PY
rm -f $T
