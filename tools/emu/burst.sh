#!/bin/bash
# burst.sh prefix n interval_s : n screenshots of melonDS (native 256x384) every interval seconds
for i in $(seq 1 $2); do timeout $3 tail -f /dev/null; $(dirname "$0")/shot.sh $1_$i.png; done
