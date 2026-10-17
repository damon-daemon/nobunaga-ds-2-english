"""usage: disasm.py binfile base start end   (ARM mode, resolves pc-relative literals)

Decodes word by word, so literal pools and other data print as .word instead
of stopping the listing."""
import sys
from capstone import Cs, CS_ARCH_ARM, CS_MODE_ARM

def listing(d, base, start, end):
    md = Cs(CS_ARCH_ARM, CS_MODE_ARM)
    for addr in range(start, end, 4):
        w = d[addr - base:addr - base + 4]
        ins = next(md.disasm(w, addr), None)
        if ins is None:
            yield '%08x  .word    0x%08x' % (addr, int.from_bytes(w, 'little')); continue
        extra = ''
        if ins.mnemonic.startswith('ldr') and ins.op_str.endswith(']') and '[pc, #' in ins.op_str:
            a = ins.address + 8 + int(ins.op_str.split('#')[-1].rstrip(']'), 0)
            extra = '   ; =0x%08x' % int.from_bytes(d[a - base:a - base + 4], 'little')
        yield '%08x  %-8s %s%s' % (ins.address, ins.mnemonic, ins.op_str, extra)

if __name__ == '__main__':
    d = open(sys.argv[1], 'rb').read(); base = int(sys.argv[2], 0)
    for line in listing(d, base, int(sys.argv[3], 0), int(sys.argv[4], 0)):
        print(line)
