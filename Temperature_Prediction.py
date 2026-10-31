"""
Temperature_Prediction.py

Right forefoot thermal prediction using RBF (Radial Basis Function,
thin-plate spline) interpolation.

Right foot: T1-T4  (Arduino indices 0-3)

Improvements over ripple_prediction.py:
  - RBF thin-plate spline instead of IDW: smoother maps, no circular
    artifacts around sensors (clipped to the measured range to stop
    the spline overshooting far from the sensors)
  - Auto-scaled symbol map: the 10 symbols stretch over the current
    sensor range (min 2C span), so sub-degree differences on skin are visible
  - Rolling 30-frame LOO error

Coordinate system (matches ripple_prediction.py):
  X: 0 = big-toe side (inner),  89 = pinky side (outer)   [mm]
  Y: 0 = ball of foot,          100 = toe tips             [mm]
"""

import serial
import serial.tools.list_ports
import sys
import os
import ctypes
import time
import numpy as np
from scipy.interpolate import RBFInterpolator

BAUD         = 115200
FOOT_W       = 89     # mm
FOOT_H       = 100    # mm
GRID_W       = 40     # display columns
GRID_H       = 20     # display rows
MIN_SPAN     = 2.0    # minimum scale span (deg C) so sensor noise isn't exaggerated
SCALE_SMOOTH = 0.2    # 0-1, how fast the scale follows the readings

SENSORS = [
    {'name': 'S1', 'label': '1st MTH (Inner Ball)', 'pos': (8,   8)},
    {'name': 'S2', 'label': 'Hallux (Big Toe)',     'pos': (5,  93)},
    {'name': 'S3', 'label': '5th MTH (Outer Ball)', 'pos': (72,  8)},
    {'name': 'S4', 'label': '3rd Toe Center',       'pos': (38, 55)},
]

RIGHT_IDX = [0, 1, 2, 3]   # T1-T4

# Pre-compute grid and sensor arrays
_xs = np.linspace(0, FOOT_W, GRID_W)
_ys = np.linspace(0, FOOT_H, GRID_H)
GRID_X, GRID_Y = np.meshgrid(_xs, _ys)
QUERY_PTS  = np.column_stack([GRID_X.ravel(), GRID_Y.ravel()])  # (GRID_W*GRID_H, 2)
SENSOR_PTS = np.array([s['pos'] for s in SENSORS], dtype=float)  # (4, 2)

# ── Foot shape mask (forefoot region only) ────────────────────────────────────

def build_mask():
    mask = [[False] * GRID_W for _ in range(GRID_H)]
    for row in range(GRID_H):
        yf = 1.0 - row / (GRID_H - 1)   # 1.0 = toe tips, 0.0 = ball
        if yf < 0.30:
            x0, x1 = 0.04, 0.96
        elif yf < 0.55:
            x0, x1 = 0.06, 0.92
        elif yf < 0.75:
            x0, x1 = 0.08, 0.85
        elif yf < 0.88:
            x0, x1 = 0.04, 0.72
        else:
            x0, x1 = 0.00, 0.50
        for col in range(int(x0 * GRID_W), int(x1 * GRID_W)):
            mask[row][col] = True
    return mask

MASK = build_mask()

# ── RBF prediction ────────────────────────────────────────────────────────────

def rbf_predict(sensor_temps):
    """
    RBF thin-plate spline interpolation over the foot grid.
    Smoother and more accurate than IDW — avoids circular hot-spot halos.
    The spline's linear trend overshoots far from the 4 sensors (phantom
    hot/cold zones up to ~2.5C beyond any reading), so predictions are
    clipped to the measured range.
    """
    vals = np.array(sensor_temps, dtype=float)
    rbf  = RBFInterpolator(SENSOR_PTS, vals, kernel='thin_plate_spline', smoothing=0.0)
    pred = rbf(QUERY_PTS).reshape(GRID_H, GRID_W)
    return np.clip(pred, vals.min(), vals.max())

def loo_error(sensor_temps):
    """
    Leave-One-Out cross-validation error using RBF.
    Predicts each sensor from the remaining three, returns mean abs error.
    """
    errors = []
    for i in range(len(SENSORS)):
        others_pts  = np.delete(SENSOR_PTS, i, axis=0)
        others_vals = np.delete(np.array(sensor_temps, dtype=float), i)
        rbf  = RBFInterpolator(others_pts, others_vals,
                               kernel='thin_plate_spline', smoothing=0.0)
        pred = float(np.clip(rbf(SENSOR_PTS[i:i+1])[0], others_vals.min(), others_vals.max()))
        errors.append(abs(pred - float(sensor_temps[i])))
    return float(np.mean(errors))

# ── Display helpers ───────────────────────────────────────────────────────────

# Symbols, cold -> hot, stretched over the current scale ('.' not ' ' so the
# coldest zone is still visible against the background)
CHARS = '.,-:=+*#%@'

def temp_char(t, lo, hi):
    i = int((t - lo) / (hi - lo) * len(CHARS))
    return CHARS[max(0, min(len(CHARS) - 1, i))]

def sensor_mark(n):
    return str(n)

SCALE_BAR = f'[ {CHARS} ]'

def sensor_cells():
    """Map (col, row) → sensor number label for display."""
    cells = {}
    for s in SENSORS:
        col = round(s['pos'][0] / FOOT_W * (GRID_W - 1))
        row = round((1 - s['pos'][1] / FOOT_H) * (GRID_H - 1))
        col = max(0, min(GRID_W - 1, col))
        row = max(0, min(GRID_H - 1, row))
        cells[(col, row)] = sensor_mark(s['name'][-1])   # '1', '2', '3', '4'
    return cells

SENSOR_CELLS = sensor_cells()

def update_scale(scale, sensor_temps):
    """Smoothly track [min, max] of the readings, at least MIN_SPAN wide."""
    lo, hi = min(sensor_temps), max(sensor_temps)
    if hi - lo < MIN_SPAN:
        mid = (lo + hi) / 2
        lo, hi = mid - MIN_SPAN / 2, mid + MIN_SPAN / 2
    if scale is None:
        return [lo, hi]
    scale[0] += SCALE_SMOOTH * (lo - scale[0])
    scale[1] += SCALE_SMOOTH * (hi - scale[1])
    return scale

LINE_W = 90

def ln(text=''):
    sys.stdout.write(text.ljust(LINE_W) + '\n')

# ── Main display ──────────────────────────────────────────────────────────────

def display(temps, frame, loo_hist, scale):
    os.system('cls')

    grid   = rbf_predict(temps)
    lo, hi = scale

    loo_hist.append(loo_error(temps))
    if len(loo_hist) > 30:
        loo_hist.pop(0)
    avg_loo = sum(loo_hist) / len(loo_hist)

    ln(f"  Right Foot Prediction  |  Frame {frame}  |  RBF Interpolation")
    ln(f"  Scale: {lo:.1f}C {SCALE_BAR} {hi:.1f}C   (auto, {(hi - lo) / len(CHARS):.2f}C per symbol)")
    ln('=' * 70)
    ln(f"  {'RIGHT FOOT  (T1-T4)':^{GRID_W + 2}}")
    ln(f"  {'TOES':^{GRID_W + 2}}")
    ln(f"  +{'-' * GRID_W}+")

    for row in range(GRID_H):
        line = '  |'
        for col in range(GRID_W):
            if (col, row) in SENSOR_CELLS:
                line += SENSOR_CELLS[(col, row)]
            elif MASK[row][col]:
                line += temp_char(grid[row][col], lo, hi)
            else:
                line += ' '
        line += '|'
        if row == GRID_H - 1:
            line += ' BALL'
        ln(line)

    ln(f"  +{'-' * GRID_W}+")
    ln()

    for i, s in enumerate(SENSORS):
        ln(f"  {s['name']}  {s['label']:22s} {temps[i]:6.2f}C")
    ln()
    hot = int(np.argmax(temps))
    ln(f"  Warmest: {SENSORS[hot]['name']} {SENSORS[hot]['label']}   |   "
       f"Spread: {max(temps) - min(temps):.2f}C   |   LOO error: {avg_loo:.3f}C")
    ln(f"  Ctrl+C to stop")

# ── Entry point ───────────────────────────────────────────────────────────────

def enable_ansi():
    kernel32 = ctypes.windll.kernel32
    handle   = kernel32.GetStdHandle(-11)
    mode     = ctypes.c_ulong()
    kernel32.GetConsoleMode(handle, ctypes.byref(mode))
    kernel32.SetConsoleMode(handle, mode.value | 0x0004)

def find_port():
    for p in serial.tools.list_ports.comports():
        if any(k in (p.description or '').lower()
               for k in ['arduino', 'usb serial', 'ch340', 'cp210', 'ftdi']):
            return p.device
    ports = serial.tools.list_ports.comports()
    return ports[0].device if ports else None

enable_ansi()

port = find_port()
if not port:
    print('No Arduino found. Plug it in and run again.')
    input('Press Enter to exit.')
    sys.exit()

try:
    ser = serial.Serial(port, BAUD, timeout=2)
except serial.SerialException as e:
    print(f'Cannot open {port}: {e}')
    print('Close Arduino IDE Serial Monitor first.')
    input('Press Enter to exit.')
    sys.exit()

time.sleep(2)
ser.reset_input_buffer()

loo_hist = []
scale    = None
frame    = 0

try:
    while True:
        line = ser.readline().decode('utf-8', errors='replace').strip()
        if not line:
            continue
        parts = line.split(',')
        if len(parts) != 16:
            continue
        try:
            all_temps = [float(p) for p in parts]
        except ValueError:
            continue

        temps = [all_temps[i] for i in RIGHT_IDX]

        # Disconnected thermistor -> Arduino sends NaN; skip frame instead of crashing
        bad = [f'T{i+1}' for i in RIGHT_IDX if np.isnan(all_temps[i])]
        if bad:
            os.system('cls')
            print(f"  Waiting: no reading from {', '.join(bad)} (check thermistor wiring)")
            continue

        scale = update_scale(scale, temps)
        frame += 1
        display(temps, frame, loo_hist, scale)

except KeyboardInterrupt:
    print('\nStopped.')
    ser.close()
    input('Press Enter to close.')
