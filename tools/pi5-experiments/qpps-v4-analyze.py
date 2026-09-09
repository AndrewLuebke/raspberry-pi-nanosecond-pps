#!/usr/bin/env python3
"""Per-phase analysis of the v4 feeder drop test (run as root on .18).
Inputs: timeline file (arg 1, default /tmp/v4-timeline.txt), journal of qpps-shm, /var/log/chrony/refclocks.log,
/var/log/chrony/statistics.log.  For each phase: LATE count / age stats, PRED pub/skip
with LINEAR error, unpublished, and the CROSS-CHECK: every LATE/PRED-published second must
appear as a QPPS raw sample in refclocks.log (proves chrony accepted the late sample)."""
import re, subprocess, sys, statistics, datetime as dt
TLPATH = sys.argv[1] if len(sys.argv) > 1 else "/tmp/v4-timeline.txt"

tl = {}
for line in open(TLPATH):
    k, t = line.split()
    tl[k] = dt.datetime.strptime(t, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc).timestamp()
phases = sorted([(k[:-6], tl[k], tl[k[:-6] + "_end"]) for k in tl if k.endswith("_start") and k[:-6] + "_end" in tl], key=lambda x: x[1])
T0 = min(a for _, a, _ in phases)

j = subprocess.run(["journalctl", "-u", "qpps-shm", "--since", "@%d" % int(T0 - 5), "--no-pager", "-o", "short-unix"],
                   capture_output=True, text=True).stdout.splitlines()
late, pred, summ = [], [], []
for l in j:
    m = re.match(r"^(\d+\.\d+) .*qpps-shm: (LATE|PRED),(.*)$", l)
    if m:
        t = float(m.group(1)); f = m.group(3).split(",")
        if m.group(2) == "LATE":
            late.append((t, int(f[0]), int(f[1]), float(f[2])))
        else:
            pred.append((t, int(f[0]), int(f[1]), float(f[2]), float(f[3]), float(f[4]), float(f[5]), float(f[6]), f[7]))
    elif re.search(r"samples \(|published \(", l):
        summ.append(l)

# QPPS raw samples chrony logged (receive-time second -> True), in log order
qpps_secs = set(); qpps_order = []
for l in open("/var/log/chrony/refclocks.log"):
    f = l.split()
    if len(f) > 3 and f[2] == "QPPS" and f[3] != "-":      # raw samples only (a "-" driver-poll field = the per-poll filtered sample)
        try:
            t = dt.datetime.strptime(f[0] + " " + f[1], "%Y-%m-%d %H:%M:%S.%f").replace(tzinfo=dt.timezone.utc).timestamp()
        except ValueError:
            continue
        qpps_secs.add(int(round(t))); qpps_order.append(int(round(t)))
# QPPS filtered std dev per phase from statistics.log
stats_rows = []
for l in open("/var/log/chrony/statistics.log"):
    f = l.split()
    if len(f) > 6 and f[2] == "QPPS":
        try:
            t = dt.datetime.strptime(f[0] + " " + f[1], "%Y-%m-%d %H:%M:%S").replace(tzinfo=dt.timezone.utc).timestamp()
            stats_rows.append((t, float(f[3])))
        except ValueError:
            pass

for p, a, b in phases:
    L = [x for x in late if a <= x[0] < b]
    P = [x for x in pred if a <= x[0] < b]
    ages = [x[2] for x in L]
    print(f"== {p}: {int((b-a)/60)} min")
    if L:
        print(f"  LATE n={len(L)} age ms: min {min(ages)} med {statistics.median(ages):.0f} p90 {sorted(ages)[int(0.9*len(ages))-1]} max {max(ages)}")
        missing = [x[1] for x in L if x[1] not in qpps_secs]
        print(f"  cross-check: {len(L)-len(missing)}/{len(L)} late seconds present as QPPS raw samples in refclocks.log" + (f"  MISSING: {missing[:8]}" if missing else ""))
    pub = [x for x in P if x[8] == "pub"]; skip = [x for x in P if x[8] == "skip"]
    if P:
        el = [abs(x[7]) for x in pub]
        print(f"  PRED n={len(P)} pub {len(pub)} skip {len(skip)}" + (f"; published LINEAR |err| mean {statistics.mean(el):.2f} max {max(el):.2f} ns, >3ns {sum(1 for e in el if e>3)}" if el else ""))
        missing = [x[1] for x in pub if x[1] not in qpps_secs]
        print(f"  cross-check: {len(pub)-len(missing)}/{len(pub)} predicted seconds present in refclocks.log" + (f"  MISSING: {missing[:8]}" if missing else ""))
        pos = {}
        for i, s_ in enumerate(qpps_order): pos.setdefault(s_, i)
        rev = sum(1 for x in pub if x[1] in pos and any(pos.get(x[1] + d, 1 << 30) < pos[x[1]] for d in (1, 2, 3, 4)))
        print(f"  ordering: {rev}/{len(pub)} predicted seconds were logged AFTER a later second (time reversal in SHM)")
    if p.startswith("QUIET"):
        holes = [int(x) for x in range(int(a), int(b)) if x not in qpps_secs]
        runs = []
        for h in holes:
            if runs and h == runs[-1][1] + 1: runs[-1][1] = h
            else: runs.append([h, h])
        print("  unpublished runs (epoch start-end, len): " + ", ".join(f"{r[0]}-{r[1]} ({r[1]-r[0]+1})" for r in runs))
    sd = [s for t, s in stats_rows if a <= t < b]
    if sd:
        print(f"  QPPS statistics.log std dev: n={len(sd)} median {statistics.median(sd)*1e9:.2f} ns max {max(sd)*1e9:.2f} ns")
    # raw QPPS sample count in the phase vs seconds in phase, and STRICT time order of what chrony accepted
    ns = sum(1 for s in qpps_secs if a <= s < b)
    seq = [x for x in qpps_order if a <= x < b]
    viol = sum(1 for x, y in zip(seq, seq[1:]) if y <= x)
    print(f"  QPPS raw samples chrony logged: {ns} of {int(b-a)} seconds ({100*ns/(b-a):.1f}%); accepted sequence strictly increasing: {'yes' if viol == 0 else f'NO ({viol} violations)'}")
print("== feeder summaries:")
for l in summ[-4:]:
    print("  " + l.split("qpps-shm: ")[-1])
