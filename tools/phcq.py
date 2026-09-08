# PHC read-quality probe: PTP_SYS_OFFSET gives sys,phc,sys triples; window = read latency,
# scatter of (phc - mid(sys)) after linear detrend = conversion noise a HW stamp inherits.
import sys, fcntl, struct, statistics as st
dev = sys.argv[1]; N = 10; ROUNDS = 6
PTP_SYS_OFFSET = 0x43403D05          # _IOW('=', 5, struct ptp_sys_offset) size 832
fd = open(dev, 'rb')
win, pts = [], []
for r in range(ROUNDS):
    buf = bytearray(struct.pack('I3I', N, 0, 0, 0)) + bytearray(51*16)
    fcntl.ioctl(fd, PTP_SYS_OFFSET, buf)
    ts = [struct.unpack_from('qI4x', buf, 16 + i*16) for i in range(2*N+1)]
    t = [s*10**9 + n for s, n in ts]
    for i in range(N):
        s1, p, s2 = t[2*i], t[2*i+1], t[2*i+2]
        win.append(s2 - s1); pts.append(((s1+s2)//2, p - (s1+s2)//2))
# linear detrend offset vs sys time (removes PHC freq offset over the burst)
xs = [x for x, _ in pts]; ys = [y for _, y in pts]
mx, my = st.mean(xs), st.mean(ys)
b = sum((x-mx)*(y-my) for x, y in pts) / sum((x-mx)**2 for x in xs)
res = [y - (my + b*(x-mx)) for x, y in pts]
print(f"{dev}: {len(win)} reads")
print(f"  read window  min/med/max = {min(win)}/{int(st.median(win))}/{max(win)} ns")
print(f"  offset scatter (detrended) stdev = {st.pstdev(res):.0f} ns   peak-peak = {max(res)-min(res):.0f} ns")
print(f"  PHC-vs-sys freq (burst est) = {b*1e6:+.1f} ppm")
