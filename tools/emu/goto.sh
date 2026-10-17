#!/bin/bash
# goto.sh place : from a fresh boot, navigate to a known screen (keys only, no screenshot)
P=$(dirname "$0")/press.sh
case "$1" in
  menu)    $P /dev/null Return w w Return w w ;;                       # start menu (cursor: New Game)
  options) $P /dev/null Return w w Return w w Down Right Right x w w ;;
  artofwar) $P /dev/null Return w w Return w w Down Right Right x w w Right Right x w w ;;
esac
case "$1" in
  clash)   # Clash of Warlords stage 1, all officers, battle started (dialogue skipped)
    $P /dev/null w w w Return w w w Return w w w Return w w w Right x w w w x w w w x w w s w w Left x w w w x w w w BackSpace w
    T="$(dirname "$0")/../../.venv/bin/python $(dirname "$0")/tap.py"
    $T 128 154; $P /dev/null w w; $T 128 157; $P /dev/null w; $T 90 118; $P /dev/null w w w w x w x w x w x w x w x w x w x w w w w w ;;
  confirm) $P /dev/null Return w w Return w w x w w x w w x w w s w w s w w w ;;   # 1555 Oda: settings check screen
esac
