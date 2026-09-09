#!/bin/bash
# v4 feeder drop test: single / double / quad consecutive datagram loss, then clean.
TL=/tmp/v4-timeline.txt
mkdir -p /run/qpps-shm
stamp(){ echo "$1 $(date -u +%FT%TZ)" >> "$TL"; }
: > "$TL"
stamp A10_1_start; echo "10 1" > /run/qpps-shm/drop; sleep 600; stamp A10_1_end
stamp B10_2_start; echo "10 2" > /run/qpps-shm/drop; sleep 600; stamp B10_2_end
stamp C10_4_start; echo "10 4" > /run/qpps-shm/drop; sleep 600; stamp C10_4_end
rm -f /run/qpps-shm/drop; stamp CLEAN_start; sleep 300; stamp CLEAN_end
stamp DONE
