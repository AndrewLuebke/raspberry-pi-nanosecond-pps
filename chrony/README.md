# chrony resolution patches

chrony's own numbers are doubles; the rounding happens at the edges. Two patches
against chrony 4.9 remove it where this project looks:

| patch | what it changes |
|---|---|
| `chrony49-tracking-ppt.patch` | `tracking.log`: frequency and skew columns at 6 decimals of ppm (ppt) instead of 3 (ppb). The Pi 4 / Pi 5 free-running OCXOs wander at the ppt level; at ppb the column is a flat line. `chrony-tracking-ppt.patch` is the older 4.8 version. |
| `chrony49-chronyc-ps-ppt.patch` | `chronyc`: `tracking` prints times and frequencies with an auto-scaled unit instead of a column of zeroes (`System time : 118 ps slow of NTP time`, `RMS offset : 1.342 ns`, `Frequency : 56.465 ppb slow`, `Residual freq : -2 ppt`, `Skew : 312 ppt`); `sources` / `sourcestats` / `selectdata` print values under 10 ns in picoseconds (`-1463ps[-1895ps]`, `Std Dev 5236ps`) and the frequency columns carry a unit (`-2ppt`, `+56.47ppb`, `+7.475ppm`), all in the same column widths. CSV mode (`-c`) stays numeric at 12 / 6 decimals. |

The hidden digits are real. The command protocol's `Float` has a 25-bit
coefficient (about 7 significant digits): a 3.6 ns offset is carried to ~2e-16 s,
residual frequency and skew to ~1e-10 ppm. Whole picoseconds and whole ppt are
shown below 1 ns / 1 ppb, three decimals of the next unit above that; the
absolute frequency's ppt digit (1 ppt of ~13 ppm) would sit at the wire quantum,
which is why ppm is shown at three decimals.

Build (native on the Pi, ~1 min; the same tree serves `chronyd` and `chronyc`):

```
tar xzf chrony-4.9.tar.gz && cd chrony-4.9
patch -p1 < .../chrony/chrony49-tracking-ppt.patch
patch -p1 < .../chrony/chrony49-chronyc-ps-ppt.patch
./configure --prefix=/usr/local && make -j4
sudo install -m 755 chronyc /usr/local/bin/chronyc          # display patch only needs this
sudo install -m 755 chronyd /usr/local/sbin/chronyd && sudo systemctl restart chronyd
```

Anything that parses `chronyc` human output has to be checked before this patch goes on a
box. Two consumers in this project: `deploy/pi5/pps-soaklog.sh` (normalises a `ps` suffix back
to `x.xxxns`) and `deploy/pps-warm-watchdog.sh` on the Pi 4, whose lock test read the "System
time" line's fourth field as seconds; with "118 ps" there it read 118, decided chrony was not
locked, disarmed the pre-warm interrupt, and the Pi 4 ran at 160 ns jitter for 17 hours before
the morning ladder showed it. It now uses `chronyc -c tracking`, which stays numeric. Prefer CSV
mode for any script.
