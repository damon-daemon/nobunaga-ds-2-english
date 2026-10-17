"""Create the working folder script/ from your own ROM and the English in tl/.

script/ holds the Japanese text extracted from the ROM next to the English, so it
is generated on each machine and never distributed. Run this once after cloning
(and again after editing tl/), then tools/build.py.

usage: .venv/bin/python tools/setup.py [clean.nds]
"""
import hashlib, json, os, sys
import ndspy.rom

sys.path.insert(0, os.path.dirname(__file__))
import script, tl, arm9str, names
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'gen'))
import msgsec00

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, 'script')
TL = os.path.join(ROOT, 'tl')
CLEAN_SHA1 = 'be0705a973809dd961c3fe7aba844208cecb29e8'
MSG_FILES = 26

def export_messages(rom):
    for n in range(MSG_FILES):
        name = 'msgsec%02d' % n
        d = bytes(rom.getFileByName('msg/%s.dat' % name))
        rows = [{'id': i, 'jp': script.decode(e), 'en': ''} for i, e in enumerate(script.entries(d))]
        json.dump(rows, open(os.path.join(SCRIPT, name + '.json'), 'w', encoding='utf-8'),
                  ensure_ascii=False, indent=1)

def main():
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, 'nobunaga_ds_2.nds')
    sha1 = hashlib.sha1(open(path, 'rb').read()).hexdigest()
    if sha1 != CLEAN_SHA1:
        sys.exit('%s: SHA-1 %s does not match the clean dump (%s)' % (path, sha1, CLEAN_SHA1))
    rom = ndspy.rom.NintendoDSRom.fromFile(path)
    os.makedirs(SCRIPT, exist_ok=True)
    export_messages(rom)
    msgsec00.apply(os.path.join(SCRIPT, 'msgsec00.json'))
    for n in range(MSG_FILES):
        batch = os.path.join(TL, 'msgsec%02d.txt' % n)
        if os.path.exists(batch):
            tl.apply('msgsec%02d' % n, batch)
    arm9str.export(path)
    names.export(bytes(rom.getFileByName('scenario/common.snr')))
    print('script/ ready; now run tools/build.py')

if __name__ == '__main__':
    main()
