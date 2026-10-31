"""
sensor_optimiser.py

Simulates 500 realistic foot temperature scenarios and measures how much
IDW prediction error drops as you add more sensors. Saves the result as
sensor_optimisation.png and opens it.
"""

import numpy as np
import matplotlib.pyplot as plt
import math, os

# ── Sensor positions in clinical priority order ───────────────────────────────
# Coordinate system matches ripple_prediction.py:
#   X: 0 = big-toe side (inner),  80 = pinky side (outer)   [mm]
#   Y: 0 = ball of foot,         100 = toe tips              [mm]
#   Y negative = heel (extended for this analysis)

ALL_SENSORS = [
    {"name": "1st MTH\n(Inner Ball)",  "pos": (8,   8)},
    {"name": "Hallux\n(Big Toe)",      "pos": (5,  93)},
    {"name": "5th MTH\n(Outer Ball)",  "pos": (72,  8)},
    {"name": "3rd Toe\n(Centre)",      "pos": (38, 55)},
    {"name": "3rd MTH\n(Centre Ball)", "pos": (40,  8)},
    {"name": "2nd MTH",                "pos": (24,  8)},
    {"name": "4th MTH",                "pos": (56,  8)},
    {"name": "2nd Toe",                "pos": (18, 80)},
]

IDW_POWER    = 2
N_SIMS       = 500    # random foot scenarios to average over
MAX_SENSORS  = len(ALL_SENSORS)

# ── Foot temperature model ────────────────────────────────────────────────────

def make_field_params(rng):
    """
    Generate parameters for one random foot temperature scenario.
    Returns a list of (cx, cy, amplitude, sigma) Gaussian sources.
    Base temperature is also included.
    """
    base = rng.uniform(28.0, 33.0)
    sources = [
        # (cx, cy, amplitude_lo, amplitude_hi, sigma)
        (8,   8,  1.5, 3.5, 12),   # 1st MTH — hottest zone
        (72,  8,  0.8, 2.5, 12),   # 5th MTH
        (40,  8,  0.5, 2.0, 10),   # 3rd MTH
        (5,  93,  0.3, 1.5, 10),   # Hallux
        (40, -25, 0.2, 1.2, 18),   # Heel
        (10,  40, -1.5, -0.3, 20), # Medial arch (cooler)
        (65,  40, -1.2, -0.2, 20), # Lateral arch (cooler)
    ]
    params = []
    for cx, cy, lo, hi, sigma in sources:
        amp = rng.uniform(lo, hi)
        params.append((cx, cy, amp, sigma))
    return base, params

def eval_field(x, y, base, params):
    """Evaluate the temperature field at scalar or array (x, y)."""
    t = base
    for cx, cy, amp, sigma in params:
        dist_sq = (x - cx)**2 + (y - cy)**2
        t = t + amp * np.exp(-dist_sq / (2.0 * sigma**2))
    return t

# ── IDW ───────────────────────────────────────────────────────────────────────

def idw_grid(grid_x, grid_y, sensor_pos, sensor_temps):
    """IDW prediction over a meshgrid from a list of (x,y) sensors."""
    preds      = np.zeros_like(grid_x, dtype=float)
    weight_sum = np.zeros_like(grid_x, dtype=float)
    for (sx, sy), t in zip(sensor_pos, sensor_temps):
        dist = np.sqrt((grid_x - sx)**2 + (grid_y - sy)**2)
        dist = np.maximum(dist, 0.5)
        w = 1.0 / dist**IDW_POWER
        preds      += w * t
        weight_sum += w
    return preds / weight_sum

def loo_mean_error(sensor_pos, sensor_temps):
    """Leave-One-Out: predict each sensor from the rest, return mean abs error."""
    errors = []
    for i in range(len(sensor_pos)):
        others_pos  = [p for j, p in enumerate(sensor_pos)   if j != i]
        others_temp = [t for j, t in enumerate(sensor_temps)  if j != i]
        sx, sy = sensor_pos[i]
        w_sum, t_sum = 0.0, 0.0
        for (ox, oy), ot in zip(others_pos, others_temp):
            d = max(math.sqrt((sx - ox)**2 + (sy - oy)**2), 0.5)
            w = 1.0 / d**IDW_POWER
            t_sum += w * ot
            w_sum += w
        errors.append(abs(t_sum / w_sum - sensor_temps[i]))
    return float(np.mean(errors))

# ── Run simulation ────────────────────────────────────────────────────────────

xs = np.linspace(0, 80,  40)
ys = np.linspace(-30, 100, 50)
grid_x, grid_y = np.meshgrid(xs, ys)

rng = np.random.default_rng(42)

mean_recon, std_recon = [], []
mean_loo,   std_loo   = [], []

print(f"Running {N_SIMS} simulations for N = 2 to {MAX_SENSORS} sensors...")

for n in range(2, MAX_SENSORS + 1):
    sensor_pos = [s["pos"] for s in ALL_SENSORS[:n]]
    recon_errs, loo_errs = [], []

    for _ in range(N_SIMS):
        base, params = make_field_params(rng)

        # Ground truth on full grid
        truth = eval_field(grid_x, grid_y, base, params)

        # Sample truth at sensor positions (+ tiny measurement noise)
        sensor_temps = [
            float(eval_field(sx, sy, base, params)) + rng.normal(0, 0.15)
            for sx, sy in sensor_pos
        ]

        # IDW reconstruction over the full grid
        pred = idw_grid(grid_x, grid_y, sensor_pos, sensor_temps)

        recon_errs.append(float(np.mean(np.abs(pred - truth))))
        loo_errs.append(loo_mean_error(sensor_pos, sensor_temps))

    mean_recon.append(np.mean(recon_errs))
    std_recon.append(np.std(recon_errs))
    mean_loo.append(np.mean(loo_errs))
    std_loo.append(np.std(loo_errs))
    print(f"  N={n:2d}  recon={mean_recon[-1]:.3f}°C  LOO={mean_loo[-1]:.3f}°C")

# ── Find optimal point (elbow — biggest single-step improvement) ──────────────

sensor_counts = list(range(2, MAX_SENSORS + 1))
me = np.array(mean_recon)
drops = np.diff(me)
# Biggest drop = most valuable sensor addition
elbow_idx = int(np.argmin(drops))   # index into drops array
elbow_n   = sensor_counts[elbow_idx + 1]  # +1 because diff shifts by 1

# Diminishing returns point: where the drop is < 10% of the total drop
total_drop = me[0] - me[-1]
diminishing_idx = next(
    (i for i, d in enumerate(-drops) if d < 0.1 * total_drop),
    len(drops) - 1
)
diminishing_n = sensor_counts[diminishing_idx + 1]

# ── Plot ──────────────────────────────────────────────────────────────────────

fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(13, 10),
                                gridspec_kw={"height_ratios": [3, 1]})

me  = np.array(mean_recon)
se  = np.array(std_recon)
ml  = np.array(mean_loo)
sl  = np.array(std_loo)

# ── Top panel: error curves ───────────────────────────────────────────────────
ax1.fill_between(sensor_counts, me - se, me + se, alpha=0.15, color='steelblue')
ax1.plot(sensor_counts, me, 'o-', color='steelblue', lw=2.5, ms=7,
         label='Reconstruction error vs ground truth')

ax1.fill_between(sensor_counts, ml - sl, ml + sl, alpha=0.15, color='tomato')
ax1.plot(sensor_counts, ml, 's--', color='tomato',    lw=2.5, ms=7,
         label='Leave-One-Out error (like ripple_prediction.py uses)')

# Elbow marker
ax1.axvline(elbow_n, color='green', lw=1.8, linestyle=':',
            label=f'Biggest single gain: adding sensor {elbow_n} ({ALL_SENSORS[elbow_n-1]["name"].replace(chr(10), " ")})')

# Diminishing returns marker
ax1.axvline(diminishing_n, color='orange', lw=1.8, linestyle='-.',
            label=f'Diminishing returns after N={diminishing_n}')

ax1.axvspan(diminishing_n - 0.4, MAX_SENSORS + 0.4, alpha=0.06, color='orange',
            label='< 10% of total gain remaining')

ax1.set_ylabel("Mean absolute temperature error (°C)", fontsize=12)
ax1.set_title(
    "Achilles — How prediction error changes with sensor count\n"
    f"({N_SIMS} simulated realistic foot temperature scenarios, IDW power={IDW_POWER})",
    fontsize=13
)
ax1.set_xticks(sensor_counts)
ax1.set_xticklabels(sensor_counts)
ax1.legend(fontsize=10, loc='upper right')
ax1.grid(True, alpha=0.3)
ax1.set_xlim(1.5, MAX_SENSORS + 0.5)

# ── Bottom panel: marginal gain per sensor ────────────────────────────────────
marginal = -np.diff(me)   # how much error drops when you add each sensor
bar_colors = ['green' if i == elbow_idx else
              ('orange' if sensor_counts[i+1] > diminishing_n else 'steelblue')
              for i in range(len(marginal))]

bars = ax2.bar(sensor_counts[1:], marginal, color=bar_colors, edgecolor='white', width=0.6)
ax2.axhline(0.1 * total_drop, color='orange', linestyle='-.', lw=1.5,
            label='10% of total gain threshold')
ax2.set_xlabel("Sensor added (N-th sensor)", fontsize=12)
ax2.set_ylabel("Error reduction (°C)", fontsize=11)
ax2.set_title("Marginal gain from each additional sensor", fontsize=11)
ax2.set_xticks(sensor_counts[1:])
xticklabels = [ALL_SENSORS[n-1]["name"].replace('\n', ' ') for n in sensor_counts[1:]]
ax2.set_xticklabels(xticklabels, fontsize=7.5, rotation=15, ha='right')
ax2.legend(fontsize=9)
ax2.grid(True, alpha=0.3, axis='y')

plt.tight_layout(pad=2.0)

out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sensor_optimization_graph.png")
plt.savefig(out_path, dpi=150, bbox_inches='tight')
print(f"\nSaved: {out_path}")
plt.show()
