import os
import sys
import subprocess

# ── Launcher mode: run from IDE → opens a new terminal window ─────────────────
if "--run" not in sys.argv:
    import base64
    script = os.path.abspath(__file__)
    python = sys.executable
    ps_command = f"& '{python}' '{script}' --run"
    encoded = base64.b64encode(ps_command.encode("utf-16-le")).decode()
    subprocess.Popen(
        ["powershell", "-NoExit", "-EncodedCommand", encoded],
        creationflags=subprocess.CREATE_NEW_CONSOLE
    )
    sys.exit()

# ── Monitor mode: runs inside the new terminal window ─────────────────────────
import serial
import serial.tools.list_ports
import ctypes
import time

BAUD = 115200

LABELS = [
    "T1  MUX1-CH0", "T2  MUX1-CH1", "T3  MUX1-CH2", "T4  MUX1-CH3",
    "T5  MUX1-CH4", "T6  MUX1-CH5", "T7  MUX1-CH6", "T8  MUX1-CH7",
    "T9  MUX2-CH0", "T10 MUX2-CH1", "T11 MUX2-CH2", "T12 MUX2-CH3",
    "T13 MUX2-CH4", "T14 MUX2-CH5", "T15 MUX2-CH6", "T16 MUX2-CH7",
]

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

def bar(temp, lo=18.0, hi=42.0, width=20):
    if temp is None:
        return "[" + "?" * width + "]"
    n = int((temp - lo) / (hi - lo) * width)
    n = max(0, min(width, n))
    return "[" + "#" * n + "-" * (width - n) + "]"

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

prev = [None] * 16
frame = 0

try:
    while True:
        line = ser.readline().decode("utf-8", errors="replace").strip()
        if not line:
            continue
        parts = line.split(",")
        if len(parts) != 16:
            continue

        curr = []
        for p in parts:
            try:
                curr.append(float(p))
            except ValueError:
                curr.append(None)

        if frame == 0:
            os.system("cls")
        sys.stdout.write("\033[H")
        sys.stdout.flush()

        print(f"  Achilles Temp Monitor  |  {port}  |  {BAUD} baud  |  Frame {frame + 1}")
        print("=" * 65)
        print(f"  {'Sensor':<14}  {'Temp':>8}  {'Change':>9}  Level")
        print("-" * 65)

        for i in range(16):
            t = curr[i]
            temp_str = f"{t:>7.2f} C" if t is not None else "    NaN  "
            delta = ""
            if prev[i] is not None and t is not None:
                diff = t - prev[i]
                if abs(diff) >= 0.05:
                    delta = f"{'UP' if diff > 0 else 'DN'} {abs(diff):.2f}"
            print(f"  {LABELS[i]:<14}  {temp_str}  {delta:>9}  {bar(t)}")
            if i == 7:
                print("-" * 65)

        print("=" * 65)
        print("  Touch a sensor to see changes  |  Ctrl+C to stop")

        prev = curr
        frame += 1

except KeyboardInterrupt:
    print("\nMonitor stopped.")
    ser.close()
    input("Press Enter to close.")
