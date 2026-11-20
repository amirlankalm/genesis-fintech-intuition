"""Starts a long-lived child that inherits its pipes, records the child's pid, then exits."""

import subprocess
import sys

sys.stdin.readline()
child = subprocess.Popen(["/bin/sleep", "600"])
with open(sys.argv[1], "w") as handle:
    handle.write(str(child.pid))
