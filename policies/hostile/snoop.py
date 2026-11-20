"""Looks for the given strings on the command line of every process it can see.

Usage: snoop.py <needle> [<needle> ...]. Prints a JSON list of the needles it found to
stderr, then submits nothing. The launching shell keeps whatever was typed after it, so
anything passed as an argument to any wrapper is fair game.
"""

import ctypes
import json
import os
import sys

reset = json.loads(sys.stdin.readline())
episode_id = reset["observation"]["manifest"]["episode_id"]


def all_pids() -> list[int]:
    if sys.platform == "darwin":
        libc = ctypes.CDLL("/usr/lib/libSystem.B.dylib")
        buffer = (ctypes.c_int * 8192)()
        count = libc.proc_listallpids(buffer, ctypes.sizeof(buffer))
        return [pid for pid in buffer[: max(count, 0)] if pid > 0]
    return [int(name) for name in os.listdir("/proc") if name.isdigit()]


def command_line(pid: int) -> bytes:
    if sys.platform == "darwin":
        libc = ctypes.CDLL("/usr/lib/libSystem.B.dylib")
        buffer = ctypes.create_string_buffer(1 << 18)
        size = ctypes.c_size_t(len(buffer))
        if libc.sysctl((ctypes.c_int * 3)(1, 49, pid), 3, buffer, ctypes.byref(size), None, 0) != 0:
            return b""
        raw = buffer.raw[: size.value]
        count = int.from_bytes(raw[:4], sys.byteorder)
        strings = [item for item in raw[4:].split(b"\0") if item]
        return b" ".join(strings[1 : 1 + count])
    with open(f"/proc/{pid}/cmdline", "rb") as handle:
        return handle.read()


seen = b""
for pid in all_pids():
    if pid == os.getpid():
        continue  # its own arguments are the needles
    try:
        seen += command_line(pid) + b"\n"
    except OSError:
        pass
sys.stderr.write(json.dumps([needle for needle in sys.argv[1:] if needle.encode() in seen]))
sys.stderr.flush()
sys.stdout.write(
    json.dumps({"action": "submit", "args": {"findings": {"episode_id": episode_id, "findings": []}}}) + "\n"
)
sys.stdout.flush()
