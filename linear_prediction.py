import serial
import serial.tools.list_ports
import time
import os
import sys
import ctypes

# ── Sensor strip configuration ────────────────────────────────────────────────
# Add or remove positions (mm from heel) to switch between 2-sensor and
# 3-sensor mode. The script auto-adapts to however many entries are listed.
#
#   2 sensors:  SENSOR_POSITIONS = [0, 89]
#   3 sensors:  SENSOR_POSITIONS = [0, 44.5, 89]
#
SENSOR_POSITIONS = [38, 48, 70]   # mm from big toe reference point

NUM_POINTS = 9   # interpolated points per segment (including endpoints)
BAUD = 115200

# ── Helpers ───────────────────────────────────────────────────────────────────

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

def linear_interpolate(ta, tb, num_points):
    return [ta + (tb - ta) * i / (num_points - 1) for i in range(num_points)]

def temp_bar(temp, lo=18.0, hi=42.0, width=20):
    n = int((temp - lo) / (hi - lo) * width)
    n = max(0, min(width, n))
    return "[" + "#" * n + "-" * (width - n) + "]"

# ── Display ───────────────────────────────────────────────────────────────────

def display(sensor_temps, segments, frame):
    sys.stdout.write("\033[H")
    sys.stdout.flush()

    n = len(SENSOR_POSITIONS)
    label_str = "  ->  ".join(f"T{i+1}" for i in range(n))
    print(f"  Sensor Strip: {label_str}  |  {n} sensors  |  Frame {frame}".ljust(70))
    print("=" * 70)
    print(f"  {'Position':<12}  {'Type':<14}  {'Temp':>8}  Level".ljust(70))

    for seg_idx, (seg, (pos_a, pos_b)) in enumerate(zip(segments, zip(SENSOR_POSITIONS, SENSOR_POSITIONS[1:]))):
        print("-" * 70)
        span = pos_b - pos_a
        step = span / (NUM_POINTS - 1)

        for i, t in enumerate(seg):
            # Skip the first point of every segment after the first (already shown as last of previous)
            if seg_idx > 0 and i == 0:
                continue
            pos = pos_a + step * i
            if seg_idx == 0 and i == 0:
                label = f"T1 (sensor)"
            elif i == NUM_POINTS - 1:
                label = f"T{seg_idx + 2} (sensor)"
            else:
                label = "interpolated"
            print(f"  {pos:>5.0f} mm      {label:<14}  {t:>7.2f} C  {temp_bar(t)}".ljust(70))

    print("=" * 70)
    readings = "  ".join(f"T{i+1}={sensor_temps[i]:.2f}C" for i in range(n))
    print(f"  {readings}  |  Ctrl+C to stop".ljust(70))

# ── Main ──────────────────────────────────────────────────────────────────────

enable_ansi()

port = find_port()
if not port:
    print("No Arduino found.")
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

n_sensors = len(SENSOR_POSITIONS)
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
            sensor_temps = [float(parts[i]) for i in range(n_sensors)]
        except ValueError:
            continue

        segments = [
            linear_interpolate(sensor_temps[i], sensor_temps[i + 1], NUM_POINTS)
            for i in range(n_sensors - 1)
        ]

        if frame == 0:
            os.system("cls")
        display(sensor_temps, segments, frame + 1)
        frame += 1

except KeyboardInterrupt:
    print("\nStopped.")
    ser.close()
    input("Press Enter to close.")
