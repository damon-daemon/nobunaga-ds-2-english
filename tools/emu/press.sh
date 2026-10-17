#!/bin/bash
# usage: press.sh out.png key ...   keys: wtype key names (x=A z=B s=X a=Y q=L w=R Return=Start BackSpace=Select, Up/Down/Left/Right); 'w' alone = wait 1s
hyprctl dispatch 'hl.dsp.focus({ window = "class:net.kuribo64.melonDS" })' >/dev/null
timeout 0.5 tail -f /dev/null
for k in "${@:2}"; do
  if [ "$k" = w ]; then timeout 1 tail -f /dev/null; continue; fi
  [ "$k" = R ] && k=w; [ "$k" = L ] && k=q
  wtype -P "$k" -s 120 -p "$k"; timeout 0.5 tail -f /dev/null
done
timeout 1 tail -f /dev/null
[ "$1" = /dev/null ] || $(dirname "$0")/shot.sh "$1"
