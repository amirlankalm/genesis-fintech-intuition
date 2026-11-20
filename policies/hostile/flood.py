"""Writes far more than one episode may send, with no newline."""

import sys

sys.stdin.readline()
chunk = "y" * 1_048_576
try:
    for _ in range(40):
        sys.stdout.write(chunk)
        sys.stdout.flush()
except BrokenPipeError:
    pass
