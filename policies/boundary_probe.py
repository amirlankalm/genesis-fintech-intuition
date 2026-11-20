"""A hostile policy process: it tries everything a policy must not be able to do.

Usage: boundary_probe.py <truth_path> <public_file> <write_target> <tcp_port> <evaluator_pid> <source_file>
       [<needle in the evaluator's arguments> <needle in the evaluator's environment>]
Prints one JSON object. Each attempt is "ok" (the attempt succeeded, which is bad
under confinement) or "denied:<ExceptionName>". `search_private` does not need to
be told where the truth is: it looks around its own directory, as a real attacker
would, so it also notices a mount that exposes too much.
"""

from __future__ import annotations

import json
import os
import resource
import socket
import sys


def attempt(action) -> str:
    try:
        action()
    except BaseException as error:  # noqa: BLE001 - the probe reports every kind of refusal
        return f"denied:{type(error).__name__}"
    return "ok"


def read(path: str) -> None:
    with open(path, encoding="utf-8") as handle:
        handle.read(64)


def write(path: str) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("probe")


def connect(port: int) -> None:
    socket.create_connection(("127.0.0.1", port), timeout=2).close()


def fork() -> None:
    child = os.fork()
    if child == 0:
        os._exit(0)
    # Reap it before going on. Until it is gone the child is a copy of this process, needles in
    # its arguments included, and the command-line scan below would find them in it.
    os.waitpid(child, 0)


def search_private() -> None:
    """Succeeds (returns) if a truth or provenance file is reachable from near this script."""
    start = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os.listdir(start)  # a denied listing is a denial, not a clean bill of health
    for directory, subdirectories, files in os.walk(start):
        depth = directory[len(start) :].count(os.sep)
        subdirectories[:] = [
            d for d in subdirectories if depth < 4 and d not in ("proc", "sys", "dev", ".git", ".venv")
        ]
        if "truth.json" in files or "provenance.json" in files:
            return
    raise FileNotFoundError("no private file reachable")


def process_strings(pid: int, part: str) -> list[bytes]:
    """The arguments or the initial environment of another process, read the way an attacker would."""
    if sys.platform == "darwin":
        import ctypes

        libc = ctypes.CDLL("/usr/lib/libSystem.B.dylib", use_errno=True)
        buffer = ctypes.create_string_buffer(1 << 18)
        size = ctypes.c_size_t(len(buffer))
        if libc.sysctl((ctypes.c_int * 3)(1, 49, pid), 3, buffer, ctypes.byref(size), None, 0) != 0:
            raise PermissionError("kern.procargs2 refused")
        raw = buffer.raw[: size.value]
        count = int.from_bytes(raw[:4], sys.byteorder)
        strings = [item for item in raw[4:].split(b"\0") if item]  # executable path, arguments, environment
        return strings[1 : 1 + count] if part == "cmdline" else strings[1 + count :]
    with open(f"/proc/{pid}/{part}", "rb") as handle:
        return handle.read().split(b"\0")


def all_pids() -> list[int]:
    if sys.platform == "darwin":
        import ctypes

        libc = ctypes.CDLL("/usr/lib/libSystem.B.dylib")
        buffer = (ctypes.c_int * 8192)()
        count = libc.proc_listallpids(buffer, ctypes.sizeof(buffer))
        return [pid for pid in buffer[: max(count, 0)] if pid > 0]
    return [int(name) for name in os.listdir("/proc") if name.isdigit()]


def find_needle(pids: list[int], part: str, needle: str) -> None:
    """Succeeds (returns) if the needle is visible in that part of any of those processes' metadata."""
    if not needle:
        raise LookupError("no needle to look for")
    refused = 0
    for pid in pids:
        if pid == os.getpid():
            continue  # the needle is among this probe's own arguments
        try:
            if any(needle.encode() in item for item in process_strings(pid, part)):
                return
        except OSError:
            refused += 1
    raise PermissionError("every read refused") if refused == len(pids) else LookupError("needle not visible")


def limit(name: str) -> int | None:
    value = resource.getrlimit(getattr(resource, name))[0]
    return None if value == resource.RLIM_INFINITY else value


def main() -> None:
    truth, public, target, port, evaluator = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4]), int(sys.argv[5])
    source = sys.argv[6]
    needle_argument, needle_environment = (sys.argv[7:9] + ["", ""])[:2]
    report = {
        "read_truth": attempt(lambda: read(truth)),
        "stat_truth": attempt(lambda: os.stat(truth)),
        "list_private": attempt(lambda: os.listdir(os.path.dirname(truth))),
        "read_public_file": attempt(lambda: read(public)),
        "read_source": attempt(lambda: read(source)),
        "write_file": attempt(lambda: write(target)),
        "connect": attempt(lambda: connect(port)),
        "search_private": attempt(search_private),
        "fork": attempt(fork),
        "signal_evaluator": attempt(lambda: os.kill(evaluator, 0)),
        # the argument needle is looked for on the command line of every process, launchers included
        "read_evaluator_cmdline": attempt(lambda: find_needle(all_pids(), "cmdline", needle_argument)),
        "read_evaluator_environ": attempt(lambda: find_needle([evaluator], "environ", needle_environment)),
        "limits": {name: limit(name) for name in ("RLIMIT_CPU", "RLIMIT_FSIZE", "RLIMIT_CORE")},
        "environment": sorted(os.environ),
        "uid": os.getuid(),
    }
    sys.stdout.write(json.dumps(report) + "\n")


if __name__ == "__main__":
    main()
