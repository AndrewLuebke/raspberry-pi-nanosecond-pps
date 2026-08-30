#!/bin/bash
# pps-warm-watchdog — arm pps_prewarm only while chrony is PPS-locked,
# disarm on anomalies. Satisfies the production conditions from the
# adversarial review (grok ~/pps-warm-review/REVIEW-v2.md): arm gated on
# lock (R2), skip-burst and leaf-rate watches, storm e-stop.
P=/sys/module/pps_prewarm/parameters
CHRONYC=/usr/local/bin/chronyc

log() { logger -t pps-warm-watchdog "$*"; }

locked() {
	$CHRONYC tracking 2>/dev/null | awk '
		/^Reference ID/ { ok1 = /PPS/ }
		/^Stratum/      { ok2 = ($3 == 1) }
		/^System time/  { ok3 = ($4 < 0.00001) }
		END { exit !(ok1 && ok2 && ok3) }'
}

leaf_count() { awk '/pps@12/ {print $2+$3+$4+$5}' /proc/interrupts; }

# mask GPIO bank0 at the GIC (ICENABLER bit for hwirq 145): kills PPS until
# re-enabled or reboot — deliberate last resort for a suspected re-pend storm.
estop() {
	python3 - <<-'EOF'
	import mmap, os
	fd = os.open('/dev/mem', os.O_RDWR | os.O_SYNC)
	mm = mmap.mmap(fd, 0x1000, offset=0xFF841000)
	mm[0x190:0x194] = (1 << 17).to_bytes(4, 'little')  # ICENABLER[4] bit17
	mm.close(); os.close(fd)
	EOF
}

log "watchdog started"
prev_leaf=$(leaf_count); prev_fires=0; prev_skips=0; armed=0
while sleep 30; do
	[ -e "$P/armed" ] || continue
	# read the REAL state each pass: a module reload resets armed to N and
	# invalidates any shadowed state (bug found 2026-08-30: internal tracking
	# left a freshly reloaded module disarmed forever)
	armed=$([ "$(cat "$P/armed")" = "Y" ] && echo 1 || echo 0)
	leaf=$(leaf_count); fires=$(cat "$P/fires"); skips=$(cat "$P/late_skips")
	dl=$((leaf - prev_leaf)); ds=$((skips - prev_skips))
	prev_leaf=$leaf; prev_fires=$fires; prev_skips=$skips
	if [ "$armed" = 1 ]; then
		if [ "$dl" -eq 0 ]; then
			echo 0 > "$P/armed"; armed=0; estop
			log "CRITICAL: leaf stalled while armed - disarmed + bank0 MASKED (PPS down, investigate)"
		elif [ "$dl" -gt 40 ] || [ "$ds" -gt 5 ] || ! locked; then
			echo 0 > "$P/armed"; armed=0
			log "DISARMED: leaf +$dl/30s, skips +$ds, lock=$(locked && echo y || echo n)"
		fi
	else
		if locked && [ "$dl" -ge 25 ] && [ "$dl" -le 35 ]; then
			echo 1 > "$P/armed"; armed=1
			log "ARMED (chrony PPS-locked, leaf rate $dl/30s)"
		fi
	fi
done
