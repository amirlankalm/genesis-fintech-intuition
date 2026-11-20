"""Sends exactly the line given as its argument, with a newline unless told otherwise."""

import sys

sys.stdin.readline()
sys.stdout.write(sys.argv[1].replace("EPISODE", sys.argv[2]) + ("" if len(sys.argv) > 3 else "\n"))
sys.stdout.flush()
