"""Rebuild the ROM with translated script and produce a patch.

usage: .venv/bin/python tools/build.py [clean.nds] [out.nds]
"""
import os, subprocess, sys
import ndspy.rom

sys.path.insert(0, os.path.dirname(__file__))
import script, patch_arm9, setup, arm9str, names, msgspill, gfx

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def crc16(data, crc=0xFFFF):
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc

def match_header_crc(path, clean):
    """Give the patched ROM the clean ROM's header CRC16 by setting two reserved header
    bytes (0x15-0x16, unused and zero in the original). Loaders such as TWiLight Menu++ /
    nds-bootstrap identify a game by game code + header CRC to apply their per-game
    compatibility settings and fixes; the rebuilt header (new offsets and sizes) would
    otherwise not be recognised."""
    import struct
    with open(clean, 'rb') as f:
        target = struct.unpack_from('<H', f.read(0x160), 0x15E)[0]
    with open(path, 'r+b') as f:
        h = bytearray(f.read(0x160))
        for v in range(0x10000):
            h[0x15], h[0x16] = v & 0xFF, v >> 8
            if crc16(h[:0x15E]) == target:
                break
        else:
            raise RuntimeError('no reserved-byte value gives the clean header CRC')
        struct.pack_into('<H', h, 0x15E, target)
        f.seek(0); f.write(h)

def main():
    clean = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, 'nobunaga_ds_2.nds')
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(ROOT, 'build', 'nobunaga_ds_2_en.nds')
    rom = ndspy.rom.NintendoDSRom.fromFile(clean)
    sdir = os.environ.get('SCRIPT_DIR', os.path.join(ROOT, 'script'))
    built = {n: script.build_entries(sdir, 'msgsec%02d.dat' % n) for n in range(setup.MSG_FILES)}
    fitted = msgspill.spill({n: v for n, v in built.items() if n > 0})
    fitted[0] = built[0]
    changed = 0
    for n in range(setup.MSG_FILES):
        fid = rom.filenames.idOf('msg/msgsec%02d.dat' % n)
        data = script.pack(fitted[n])
        if data != rom.files[fid]:
            rom.files[fid] = data; changed += 1
    extra = sorted(n for n in fitted if n >= setup.MSG_FILES)
    msgspill.add_files(rom, 'msg', [('msgsec%02d.dat' % n, script.pack(fitted[n])) for n in extra])
    if extra:
        print('message overflow files: %s' % ', '.join('msgsec%02d' % n for n in extra))
    fid = rom.filenames.idOf('scenario/common.snr')
    rom.files[fid] = names.apply(rom.files[fid])
    print('graphics: %d packs redrawn' % gfx.apply(rom))
    arm9 = rom.loadArm9()
    table = patch_arm9.apply(arm9)
    n_in, n_moved = arm9str.apply(arm9, patch_arm9.FREE)
    print('arm9 UI strings: %d in place, %d relocated' % (n_in, n_moved))
    rom.arm9 = arm9.save(compress=True)
    print('arm9 patched (ASCII font table at %#x)' % table)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    rom.saveToFile(out)
    match_header_crc(out, clean)
    print('rebuilt %s (%d message files changed)' % (out, changed))
    patch = os.path.splitext(out)[0] + '.xdelta'
    try:
        subprocess.run(['xdelta3', '-e', '-f', '-9', '-S', 'djw', '-s', clean, out, patch], check=True)
        print('patch', patch)
    except FileNotFoundError:
        print('xdelta3 not installed; skipped patch')

if __name__ == '__main__':
    main()
