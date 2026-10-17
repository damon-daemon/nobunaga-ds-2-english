"""tap.py x y [x y ...] : touch the DS bottom screen at native (x, y) in melonDS.
Moves the Hyprland cursor over the window and clicks with a temporary uinput mouse
(needs /dev/uinput writable). Window geometry as in shot.sh."""
import fcntl, json, struct, subprocess, sys, time

EV_SYN, EV_KEY, EV_REL, BTN_LEFT, REL_X = 0, 1, 2, 0x110, 0
UI_SET_EVBIT, UI_SET_KEYBIT, UI_SET_RELBIT, UI_DEV_CREATE, UI_DEV_DESTROY = 0x40045564, 0x40045565, 0x40045566, 0x5501, 0x5502

def window():
    c = [w for w in json.loads(subprocess.check_output(['hyprctl', 'clients', '-j'])) if 'melon' in w['class'].lower()][0]
    (X, Y), (W, H) = c['at'], c['size']
    MB = 24
    s = min(W / 256, (H - MB) / 384)
    return X + (W - 256 * s) / 2, Y + MB + ((H - MB) - 384 * s) / 2, s

def event(fd, t, c, v):
    fd.write(struct.pack('llHHi', 0, 0, t, c, v)); fd.flush()

def main(args):
    x0, y0, s = window()
    subprocess.run(['hyprctl', 'dispatch', 'hl.dsp.focus({ window = "class:net.kuribo64.melonDS" })'], capture_output=True)
    fd = open('/dev/uinput', 'wb', buffering=0)
    fcntl.ioctl(fd, UI_SET_EVBIT, EV_KEY); fcntl.ioctl(fd, UI_SET_KEYBIT, BTN_LEFT)
    fcntl.ioctl(fd, UI_SET_EVBIT, EV_REL); fcntl.ioctl(fd, UI_SET_RELBIT, REL_X); fcntl.ioctl(fd, UI_SET_RELBIT, 1)
    fd.write(struct.pack('80sHHHHI', b'tap-mouse', 3, 1, 1, 1, 0) + bytes(4 * 64 * 4))
    fcntl.ioctl(fd, UI_DEV_CREATE)
    time.sleep(1)
    try:
        for x, y in zip(args[::2], args[1::2]):
            px, py = round(x0 + (int(x) + 0.5) * s), round(y0 + (192 + int(y) + 0.5) * s)
            subprocess.run(['hyprctl', 'dispatch', 'hl.dsp.cursor.move({ x = %d, y = %d })' % (px, py)], capture_output=True)
            time.sleep(0.2)
            for v in (1, 0):
                event(fd, EV_KEY, BTN_LEFT, v); event(fd, EV_SYN, 0, 0); time.sleep(0.15)
            time.sleep(0.6)
    finally:
        fcntl.ioctl(fd, UI_DEV_DESTROY); fd.close()

if __name__ == '__main__':
    main(sys.argv[1:])
