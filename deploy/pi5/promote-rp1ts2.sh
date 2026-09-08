#!/bin/bash
# Promote the v2 entry-stamp kernel (kernel warmer): config.txt -> rp1ts2, tryboot.txt -> rp1ts (v1 escape hatch).
set -e
cp /boot/firmware/config.txt /boot/firmware/config.txt.bak-pre-rp1ts2
sed -i "s/^kernel=kernel-73rc1-rp1ts.img/kernel=kernel-73rc1-rp1ts2.img/" /boot/firmware/config.txt
sed -i "s/^kernel=.*/kernel=kernel-73rc1-rp1ts.img/" /boot/firmware/tryboot.txt
grep ^kernel= /boot/firmware/config.txt /boot/firmware/tryboot.txt
