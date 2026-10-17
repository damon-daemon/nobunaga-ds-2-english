"""Fit English message files into the game's message buffer.

The expander (state at 0x022C1370) loads msgsec00 into an 8 KiB slot and every
other message file into one 16 KiB slot (buffer +0x2000..+0x6000; its own state
follows), so a file larger than 16384 bytes overwrites that state and the game
hangs. English is longer than Japanese, so entries are moved out of over-full
files into extra files msgsec26-39 (their paths are already in the game's file
table; tools/patch_arm9.py lifts the 26-file limit of LoadMsgFile 0x02094650).
A moved entry is replaced by a jump stub "{01}J<id lo><id hi>": message ids are
file * 1000 + entry, and {01}J loads the target's file before continuing.
"""
import os, struct, sys

sys.path.insert(0, os.path.dirname(__file__))
import script

CAP = 16384 - 64              # slot size minus a little slack
FIRST_EXTRA, LAST_EXTRA = 26, 39

def stub(file_no, idx):
    return b'\x01J' + struct.pack('<H', file_no * 1000 + idx) + b'\x05\x05\x05'

def size(strs):
    return 2 + 2 * len(strs) + sum(len(s) for s in strs)

def spill(files):
    """files: {n: [entry bytes]} for n in 1..25 (msgsec00 has its own slot).
    Returns {n: [entry bytes]} including any extra files 26.. that were needed."""
    out = {n: list(v) for n, v in files.items()}
    extra, cur = {}, FIRST_EXTRA
    for n in sorted(out):
        strs = out[n]
        # move the largest entries first; a stub is 7 bytes
        order = sorted(range(len(strs)), key=lambda i: -len(strs[i]))
        k = 0
        while size(strs) > CAP:
            i = order[k]; k += 1
            if len(strs[i]) <= 16:
                raise ValueError('msgsec%02d: cannot fit in %d bytes' % (n, CAP))
            while cur in extra and (size(extra[cur] + [strs[i]]) > CAP or len(extra[cur]) >= 999):
                cur += 1
            if cur > LAST_EXTRA:
                raise ValueError('out of extra message files')
            extra.setdefault(cur, []).append(strs[i])
            strs[i] = stub(cur, len(extra[cur]) - 1)
    out.update(extra)
    return out

def add_files(rom, folder_name, new):
    """Append files to a ROM folder (names -> data), renumbering file ids.
    Files are addressed by path in this game, so shifting later ids is safe."""
    root = rom.filenames
    order = []                                   # (folder, [ids]) in id order
    for name, sub in root.folders:
        order.append((name, sub, list(range(sub.firstID, sub.firstID + len(sub.files)))))
    files, next_id = [], 0
    for name, sub, ids in order:
        data = [rom.files[i] for i in ids]
        if name == folder_name:
            for fname, d in new:
                sub.files.append(fname); data.append(d)
        sub.firstID = next_id
        files += data; next_id += len(data)
    assert not root.files
    rom.files = files
