"""Dies with a traceback and a lot of stderr before acting."""

import sys

sys.stdin.readline()
sys.stderr.write("x" * 1_000_000)
raise RuntimeError("policy crashed")
