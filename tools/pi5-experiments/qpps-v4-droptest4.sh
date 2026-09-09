#!/bin/bash
# v4.3 test driver take 4 (runs on claude-node): quad and five-loss windows via the drop hook on .18 (take 3 had a quoting bug: no drop file), then clean. Silent-forwarder phase =
# forwarder (qerr-forward stopped on .17, 12 s, twice) which the drop hook cannot simulate (HOLD_MAX path),
# then clean. Timeline stamped on .18 at /tmp/v4c-timeline.txt for v4-analyze.py.
set -e
TL=/tmp/v4d-timeline.txt
p18(){ ssh -o BatchMode=yes chronypi "sudo -n bash -c '$1'"; }
stamp(){ p18 "echo \"$1 \$(date -u +%FT%TZ)\" >> $TL"; }
p18 ": > $TL; mkdir -p /run/qpps-shm"
stamp C10_4_start; p18 "echo 10 4 > /run/qpps-shm/drop"; sleep 300; stamp C10_4_end
stamp D10_5_start; p18 "echo 10 5 > /run/qpps-shm/drop"; sleep 300; stamp D10_5_end
p18 "rm -f /run/qpps-shm/drop"
stamp CLEAN_start; sleep 180; stamp CLEAN_end
stamp DONE
