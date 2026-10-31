import serial
import serial.tools.list_ports
import sys
import os
import ctypes
import time
import math


BAUD = 115200
FOOT_W = 89    # mm, forefoot width
FOOT_H = 100   # mm, forefoot height (ball to toe tips)
GRID_W = 38    # display columns
GRID_H = 18    # display rows
TEMP_LO = 20.0
TEMP_HI = 36.0
IDW_POWER = 2

ALL_SENSORS = [
    {'name': 'S1',  'label': '1st MTH (Inner Ball)',  'pos': (8,  8),  'idx': 0},
    {'name': 'S2',  'label': 'Hallux (Big Toe)',      'pos': (5,  93), 'idx': 1},
    {'name': 'S3',  'label': '5th MTH (Outer Ball)',  'pos': (72, 8),  'idx': 2},
    {'name': 'S4',  'label': '3rd Toe Center',        'pos': (38, 55), 'idx': 3},
    {'name': 'S5',  'label': '3rd MTH (Centre Ball)', 'pos': (40, 8),  'idx': 4},
    {'name': 'S6',  'label': '2nd MTH',               'pos': (24, 8),  'idx': 5},
    {'name': 'S7',  'label': '4th MTH',               'pos': (56, 8),  'idx': 6},
    {'name': 'S8',  'label': '2nd Toe',               'pos': (18, 80), 'idx': 7},
    {'name': 'S9',  'label': '5th Toe',               'pos': (65, 80), 'idx': 8},
    {'name': 'S10', 'label': 'Medial Arch',           'pos': (10, 40), 'idx': 9},
]

FEW, MANY = 4, 10   # the two layouts compared side by side
SENSOR_CONFIGS = {FEW: ALL_SENSORS[:FEW], MANY: ALL_SENSORS[:MANY]}
MAP_LABELS = '123456789X'   # one character per sensor on the map (X = 10)

def enable_ansi():
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.GetStdHandle(-11)
    mode = ctypes.c_ulong()
    kernel32.GetConsoleMode(handle, ctypes.byref(mode))
    kernel32.SetConsoleMode(handle, mode.value | 0x0004)

def find_port():
    for p in serial.tools.list_ports.comports():
        if any(k in (p.description or "").lower() for k in ["arduino", "usb serial", "ch340", "cp210", "ftdi"]):
            return p.device
    ports = serial.tools.list_ports.comports()
    return ports[0].device if ports else None

# ── IDW core ──────────────────────────────────────────────────────────────────

def idw_predict(x, y, sensors, temps, power=IDW_POWER):
    weighted_sum = 0.0
    weight_total = 0.0
    for s, t in zip(sensors, temps):
        dx = x - s['pos'][0]
        dy = y - s['pos'][1]
        dist = math.sqrt(dx*dx + dy*dy)
        if dist < 0.5:
            return t
        w = 1.0 / (dist ** power)
        weighted_sum += w * t
        weight_total += w
    return weighted_sum / weight_total

def loo_error(sensors, temps):
    """Leave-One-Out: predict each sensor using the rest, return list of abs errors."""
    errors = []
    for i in range(len(sensors)):
        others = [s for j, s in enumerate(sensors) if j != i]
        other_temps = [t for j, t in enumerate(temps) if j != i]
        predicted = idw_predict(sensors[i]['pos'][0], sensors[i]['pos'][1], others, other_temps)
        errors.append(abs(predicted - temps[i]))
    return errors



def build_mask():
    mask = [[False]*GRID_W for _ in range(GRID_H)]
    for row in range(GRID_H):
        yf = 1.0 - row / (GRID_H - 1)  # 0=ball, 1=toe tip
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
        for col in range(int(x0*GRID_W), int(x1*GRID_W)):
            mask[row][col] = True
    return mask

def build_grid(sensors, temps, mask):
    grid = [[None]*GRID_W for _ in range(GRID_H)]
    for row in range(GRID_H):
        for col in range(GRID_W):
            if mask[row][col]:
                x = (col / (GRID_W-1)) * FOOT_W
                y = (1 - row / (GRID_H-1)) * FOOT_H
                grid[row][col] = idw_predict(x, y, sensors, temps)
    return grid

def sensor_cell(s):
    col = round(s['pos'][0] / FOOT_W * (GRID_W-1))
    row = round((1 - s['pos'][1] / FOOT_H) * (GRID_H-1))
    return max(0, min(GRID_W-1, col)), max(0, min(GRID_H-1, row))

CHARS = ' .-:=+*#@'

def temp_char(t):
    if t is None:
        return ' '
    i = int((t - TEMP_LO) / (TEMP_HI - TEMP_LO) * (len(CHARS)-1))
    return CHARS[max(0, min(len(CHARS)-1, i))]

# ── Display ───────────────────────────────────────────────────────────────────

LINE_W = 90

def ln(text=""):
    sys.stdout.write(text.ljust(LINE_W) + "\n")

def pct_better(a, b):
    if a <= 0:
        return ""
    p = (a - b) / a * 100
    return f"({p:.1f}% better)" if p >= 0 else f"({-p:.1f}% worse)"

def display(temps_all, frame, mask, err_hist_few, err_hist_many):
    os.system("cls")

    sf = SENSOR_CONFIGS[FEW]
    sm = SENSOR_CONFIGS[MANY]
    tf = [temps_all[s['idx']] for s in sf]
    tm = [temps_all[s['idx']] for s in sm]

    gf = build_grid(sf, tf, mask)
    gm = build_grid(sm, tm, mask)

    spf = {sensor_cell(s): MAP_LABELS[i] for i, s in enumerate(sf)}
    spm = {sensor_cell(s): MAP_LABELS[i] for i, s in enumerate(sm)}

    W = GRID_W
    ln(f"  Forefoot IDW Prediction  |  Frame {frame}  |  Scale: {TEMP_LO}C[ .-:=+*#@ ]{TEMP_HI}C")
    ln("=" * 86)
    ln(f"  {f'  {FEW} SENSORS':^{W+2}}    {f'  {MANY} SENSORS':^{W+2}}")
    ln(f"  {'  TOES':^{W+2}}    {'  TOES':^{W+2}}")
    ln(f"  +{'-'*W}+    +{'-'*W}+")

    for row in range(GRID_H):
        rf = "  |"
        rm = "  |"
        for col in range(W):
            rf += spf.get((col, row), temp_char(gf[row][col]) if mask[row][col] else ' ')
            rm += spm.get((col, row), temp_char(gm[row][col]) if mask[row][col] else ' ')
        rf += "|"
        rm += "|"
        label = " BALL" if row == GRID_H-1 else ""
        ln(rf + "   " + rm + label)

    ln(f"  +{'-'*W}+    +{'-'*W}+")
    ln()

    # LOO error this frame
    err_hist_few.append(loo_error(sf, tf))
    err_hist_many.append(loo_error(sm, tm))
    if len(err_hist_few) > 30:
        err_hist_few.pop(0)
        err_hist_many.pop(0)

    avgf = sum(sum(e)/len(e) for e in err_hist_few) / len(err_hist_few)
    avgm = sum(sum(e)/len(e) for e in err_hist_many) / len(err_hist_many)
    maxf = max(max(e) for e in err_hist_few)
    maxm = max(max(e) for e in err_hist_many)
    rmsf = math.sqrt(sum(x**2 for e in err_hist_few for x in e) / sum(len(e) for e in err_hist_few))
    rmsm = math.sqrt(sum(x**2 for e in err_hist_many for x in e) / sum(len(e) for e in err_hist_many))

    ln(f"  {'PREDICTION ERROR':^82}")
    ln(f"  {'':28}  {f'{FEW} Sensors':>12}  {f'{MANY} Sensors':>12}  {f'Benefit of {MANY}':>18}")
    ln(f"  {'-'*76}")
    ln(f"  {'Mean Error  (30-frame avg)':28}  {avgf:>11.3f}C  {avgm:>11.3f}C  {avgf-avgm:>+14.3f}C  {pct_better(avgf, avgm)}")
    ln(f"  {'Worst Case Error':28}  {maxf:>11.3f}C  {maxm:>11.3f}C  {maxf-maxm:>+14.3f}C  {pct_better(maxf, maxm)}")
    ln(f"  {'RMS Error':28}  {rmsf:>11.3f}C  {rmsm:>11.3f}C  {rmsf-rmsm:>+14.3f}C  {pct_better(rmsf, rmsm)}")
    ln()
    ln("  Sensor readings:")
    for i in range(0, MANY, 5):
        ln("    " + "   ".join(f"{s['name']:>3}={temps_all[s['idx']]:.2f}C" for s in sm[i:i+5]))
    ln(f"  Map: 1-9 = S1-S9, X = S10   |   Ctrl+C to stop")

# ── Main ──────────────────────────────────────────────────────────────────────

enable_ansi()

port = find_port()
if not port:
    print("No Arduino found. Plug it in and run again.")
    input("Press Enter to exit.")
    sys.exit()

try:
    ser = serial.Serial(port, BAUD, timeout=2)
except serial.SerialException as e:
    print(f"Cannot open {port}: {e}")
    print("Close Arduino IDE Serial Monitor first.")
    input("Press Enter to exit.")
    sys.exit()

time.sleep(2)
ser.reset_input_buffer()
mask = build_mask()
err_hist_few, err_hist_many = [], []
frame = 0

try:
    while True:
        line = ser.readline().decode("utf-8", errors="replace").strip()
        if not line:
            continue
        parts = line.split(",")
        if len(parts) != 16:
            continue
        try:
            temps_all = [float(p) for p in parts]
        except ValueError:
            continue

        # Disconnected thermistor -> Arduino sends NaN; skip frame instead of crashing
        bad = [s['name'] for s in SENSOR_CONFIGS[MANY] if math.isnan(temps_all[s['idx']])]
        if bad:
            os.system("cls")
            print(f"  Waiting: no reading from {', '.join(bad)} (check thermistor wiring)")
            continue

        frame += 1
        display(temps_all, frame, mask, err_hist_few, err_hist_many)

except KeyboardInterrupt:
    print("\nStopped.")
    ser.close()
    input("Press Enter to close.")
