#!/bin/bash
# run.sh rom.nds : (re)start melonDS on a ROM and wait for its window
pkill -9 -x melonDS; timeout 2 tail -f /dev/null
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
(flatpak run --user --filesystem="$ROOT" net.kuribo64.melonDS "$(realpath "$1")" >/dev/null 2>&1 &)
for i in $(seq 1 30); do
  hyprctl clients -j | grep -q kuribo64 && break; timeout 0.5 tail -f /dev/null
done
timeout 2 tail -f /dev/null
