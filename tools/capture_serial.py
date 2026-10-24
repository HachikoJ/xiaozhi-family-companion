import serial, time, sys

seconds = int(sys.argv[1]) if len(sys.argv) > 1 else 25
out = sys.argv[2] if len(sys.argv) > 2 else "serial_capture.log"

s = serial.Serial("/dev/cu.usbmodem2101", 115200, timeout=1)
data = b""
end = time.time() + seconds
while time.time() < end:
    data += s.read(4096)
s.close()
with open(out, "w") as f:
    f.write(data.decode("utf-8", errors="replace"))
print(f"captured {len(data)} bytes -> {out}")
