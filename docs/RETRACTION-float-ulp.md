# Retraction: the float64-ULP analysis artifact

Every per-pulse MAD/percentile claim made by this project **before 2026-08-29 evening**
is retracted. The original analysis computed fractional seconds via
`(sec + ns*1e-9) % 1.0` — float64, whose ULP at epoch ~1.79×10⁹ s is exactly
**2⁻²² s = 238.4 ns**. Consequences:

- Robust statistics pinned to the grid: scaled MAD reported **exactly 353.5 ns**
  (= 1.4826 × ULP) across five different experiments — an eerie invariance we
  interpreted as a physical "±240 ns core wobble". It was the analyzer.
- p95/max snapped to 238.4/476.8-ns multiples; sub-ULP distributions read "MAD 0.0".
- σ survived nearly intact (quantization adds only ~ULP/√12 ≈ 69 ns in quadrature),
  so the era-to-era σ narrative stands; the exact-MAD claims do not.

Fix: parse the seconds and nanoseconds fields as separate integers and do all
arithmetic in integer nanoseconds (`tools/pps_stats.py`). Red flags that this bug is
active in any timestamp pipeline: robust statistics identical across experiments to
four digits; values equal to 2⁻ⁿ×10⁹ ns (238.4, 476.8, 953.7, 119.2…); MAD of zero
over a visibly wide histogram.

Kept as a permanent document because the bug did more than corrupt numbers: it
manufactured *corroborating evidence for a false hardware floor*, and the project's
central lesson — declared limits are hypotheses about the search, not the silicon —
was learned partly at this bug's hands.
