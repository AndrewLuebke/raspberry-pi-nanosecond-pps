#!/usr/bin/env python3
"""Run a MicroPython source file on a board over the raw REPL and print its output.
usage: mprun.py FILE [PORT]   (PORT defaults to the first /dev/ttyACM*)"""
import glob, serial, sys, time

path = sys.argv[1]
port = sys.argv[2] if len(sys.argv) > 2 else sorted(glob.glob('/dev/ttyACM*'))[0]
code = open(path, 'rb').read()

s = serial.Serial(port, 115200, timeout=1)
time.sleep(0.4)
s.write(b'\x03\x03')                       # interrupt anything running
time.sleep(0.3); s.reset_input_buffer()
s.write(b'\x01')                           # raw REPL
time.sleep(0.4)
banner = s.read(400)
if b'raw REPL' not in banner:
    print("no raw REPL prompt; got:", banner[:200], file=sys.stderr); sys.exit(1)
s.write(code + b'\x04')                    # send + execute
time.sleep(0.2)
if s.read(2) != b'OK':
    print("board did not accept the code", file=sys.stderr); sys.exit(1)

out = b''
deadline = time.time() + 30
while time.time() < deadline:
    chunk = s.read(4096)
    if chunk:
        out += chunk
        if out.count(b'\x04') >= 2:
            break
    elif out:
        break
s.write(b'\x02')                           # back to friendly REPL
s.close()

body, _, rest = out.partition(b'\x04')
err = rest.partition(b'\x04')[0]
sys.stdout.write(body.decode('utf-8', 'replace'))
if err.strip():
    sys.stderr.write("\n--- board error ---\n" + err.decode('utf-8', 'replace'))
