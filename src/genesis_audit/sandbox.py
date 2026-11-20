"""Operating-system confinement for policy processes.

A separate process is structure, not secrecy: a child with the same user id can
read every file its parent can, and can signal it. These backends add an
enforced boundary:

* seatbelt (macOS): a sandbox profile that denies reading the home, temporary and
  external volumes except the interpreter and the policy's own directory, denies
  all file writes, all network, fork, and signals to any other process.
* setuid (POSIX, evaluator running as root, for example in the container): the
  policy runs as an unprivileged user; private roots must be root-owned, mode 0700.
* docker: the policy runs in a container with no network, a read-only root, and
  only its own directory mounted. Private files are simply not there.
* none: no boundary. For debugging and for the control half of the boundary test.

On the local backends the policy starts through a small launcher that lowers its
resource limits (CPU seconds, file size, core dumps; address space and process
count where the platform enforces them) before it executes the policy script.
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
import stat
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

BACKENDS = ("seatbelt", "setuid", "docker", "none")
UNPRIVILEGED_ID = 65534
PYTHON_FLAGS = ("-B", "-E", "-s", "-S")  # no bytecode, no PYTHON* variables, no user site, no site
DOCKER_IMAGE_VARIABLE = "GENESIS_AUDIT_DOCKER_IMAGE"
CPU_SECONDS = 120
MAX_FILE_BYTES = 1_048_576
MAX_ADDRESS_SPACE = 2**30
MAX_PROCESSES = 64
_DENIED_AREAS = (
    "/Users",
    "/Volumes",
    "/private/tmp",
    "/private/var/folders",
    "/private/var/tmp",
    "/tmp",  # noqa: S108 - an area the sandbox denies, not a file this code writes
    "/var/folders",
)
_CLEAN_ENVIRONMENT = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"}
# Runs inside the confinement, before the policy: lower the limits, then become the policy.
_LAUNCHER = (
    "import json,os,resource,sys\n"
    "for name,value in json.loads(sys.argv[1]).items():\n"
    "    try:\n"
    "        resource.setrlimit(getattr(resource,name),(value,value))\n"
    "    except (AttributeError,ValueError,OSError):\n"
    "        pass\n"
    "os.execv(sys.executable,[sys.executable,'-B','-E','-s','-S',*sys.argv[2:]])\n"
)


class ConfinementError(Exception):
    """The requested boundary cannot be established. Refuse to run rather than run unconfined."""


def base_python() -> str:
    """The interpreter without any virtual environment: policies use the standard library only."""
    return os.path.realpath(getattr(sys, "_base_executable", None) or sys.executable)


def available_backends() -> list[str]:
    """Backends usable on this machine, strongest local one first. 'none' is always last."""
    found = []
    if sys.platform == "darwin" and shutil.which("sandbox-exec"):
        found.append("seatbelt")
    if os.name == "posix" and os.geteuid() == 0:
        found.append("setuid")
    if os.environ.get(DOCKER_IMAGE_VARIABLE) and shutil.which("docker"):
        found.append("docker")
    return [*found, "none"]


def resource_limits(backend: str) -> dict[str, int]:
    """Limits the launcher applies. A limit the platform refuses is skipped, so the probe reports what holds."""
    limits = {"RLIMIT_CPU": CPU_SECONDS, "RLIMIT_FSIZE": MAX_FILE_BYTES, "RLIMIT_CORE": 0}
    if sys.platform != "darwin":
        limits["RLIMIT_AS"] = MAX_ADDRESS_SPACE  # not enforced on macOS
    if backend == "setuid":
        limits["RLIMIT_NPROC"] = MAX_PROCESSES  # per user id: meaningful only for the dedicated unprivileged user
    return limits


def _quote(path: str) -> str:
    return '"' + path.replace("\\", "\\\\").replace('"', '\\"') + '"'


def seatbelt_profile(readable: Sequence[Path], private: Sequence[Path]) -> str:
    """Deny-by-area profile. Later rules win, so the private roots are denied last."""
    readable_real = sorted({os.path.realpath(path) for path in readable})
    private_real = sorted({os.path.realpath(path) for path in private})
    ancestors = sorted({str(parent) for path in readable_real for parent in Path(path).parents})
    rules = [
        "(version 1)",
        "(allow default)",
        "(deny network*)",
        "(deny file-write*)",
        "(deny process-fork)",
        # Otherwise a same-user policy could kill the evaluator. The narrower `(target others)` filter
        # was tried and did not deny anything on macOS 27, so everything is denied and self re-allowed.
        "(deny signal)",
        "(allow signal (target self))",
    ]
    if _DENIED_AREAS:
        rules.append("(deny file-read* " + " ".join(f"(subpath {_quote(area)})" for area in _DENIED_AREAS) + ")")
    rules += [
        "(allow file-read-metadata " + " ".join(f"(literal {_quote(path)})" for path in ancestors) + ")",
        "(allow file-read* " + " ".join(f"(subpath {_quote(path)})" for path in readable_real) + ")",
    ]
    if private_real:
        rules.append("(deny file-read* " + " ".join(f"(subpath {_quote(path)})" for path in private_real) + ")")
    return "\n".join(rules)


@dataclass(frozen=True)
class Confinement:
    backend: str
    private_roots: tuple[Path, ...] = ()
    docker_image: str | None = None

    def __post_init__(self) -> None:
        if self.backend not in BACKENDS:
            raise ConfinementError(f"unknown confinement backend: {self.backend}")

    @classmethod
    def strongest(cls, private_roots: Sequence[Path]) -> Confinement:
        """The first real boundary this machine offers. If there is none the backend is 'none': check it."""
        backend = available_backends()[0]
        return cls(backend, tuple(private_roots), os.environ.get(DOCKER_IMAGE_VARIABLE))

    def launch(self, script: Path, args: Sequence[str]) -> tuple[list[str], dict[str, Any]]:
        """Return (argv, Popen keyword arguments) to run a policy script under this backend."""
        script = Path(os.path.realpath(script))
        common: dict[str, Any] = {"cwd": "/", "env": dict(_CLEAN_ENVIRONMENT)}
        if self.backend == "docker":
            return self._docker(script, args), {"cwd": "/", "env": dict(os.environ)}  # the client needs its own
        limits = json.dumps(resource_limits(self.backend))
        local = [base_python(), *PYTHON_FLAGS, "-c", _LAUNCHER, limits, str(script), *args]
        if self.backend == "none":
            return local, common
        if self.backend == "seatbelt":
            if sys.platform != "darwin" or not shutil.which("sandbox-exec"):
                raise ConfinementError("the seatbelt backend needs macOS sandbox-exec")
            readable = [Path(sys.base_prefix), Path(sys.base_exec_prefix), Path(base_python()).parent, script.parent]
            return ["sandbox-exec", "-p", seatbelt_profile(readable, self.private_roots), *local], common
        self._require_root_only_private_roots()
        return local, {**common, "user": UNPRIVILEGED_ID, "group": UNPRIVILEGED_ID, "extra_groups": []}

    def _docker(self, script: Path, args: Sequence[str]) -> list[str]:
        if not self.docker_image:
            raise ConfinementError(f"the docker backend needs an image name in {DOCKER_IMAGE_VARIABLE}")
        if not shutil.which("docker"):
            raise ConfinementError("the docker backend needs the docker client")
        if any(character in str(script.parent) for character in ":,"):
            raise ConfinementError("the policy directory path cannot be used as a docker mount")
        return [
            "docker", "run", "--rm", "-i", "--name", f"genesis-policy-{secrets.token_hex(6)}",
            "--network", "none", "--read-only", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges", "--pids-limit", str(MAX_PROCESSES), "--memory", "256m",
            "--cpus", "1", "--ulimit", f"cpu={CPU_SECONDS}", "--ulimit", f"fsize={MAX_FILE_BYTES}",
            "--user", f"{UNPRIVILEGED_ID}:{UNPRIVILEGED_ID}", "-v", f"{script.parent}:/policy:ro",
            self.docker_image, "python", *PYTHON_FLAGS, f"/policy/{script.name}", *args,
        ]  # fmt: skip

    def cleanup_command(self, argv: Sequence[str]) -> list[str] | None:
        """A command that removes whatever `launch` may have left behind, or None."""
        if self.backend != "docker" or "--name" not in argv:
            return None
        return ["docker", "kill", argv[list(argv).index("--name") + 1]]

    def _require_root_only_private_roots(self) -> None:
        if os.name != "posix" or os.geteuid() != 0:
            raise ConfinementError("the setuid backend needs the evaluator to run as root")
        for root in self.private_roots:
            info = os.stat(root)
            if info.st_uid != 0 or stat.S_IMODE(info.st_mode) & 0o077:
                raise ConfinementError(f"private path must be owned by root and closed to others: {root}")

    def describe(self) -> dict[str, Any]:
        """What this backend does and does not protect, for the evaluator's run record."""
        protects = {
            "seatbelt": (
                "reads of home, temp and external volumes except interpreter and policy code; all file writes; "
                "all network; fork; signals to other processes; CPU seconds and file size by rlimit"
            ),
            "setuid": (
                "reads and writes of root-only paths, including private roots; signals to the evaluator; CPU "
                "seconds, file size, address space and process count by rlimit; network only if the container has none"
            ),
            "docker": (
                "everything not mounted: private files are absent; no network; read-only root; limited pids, "
                "memory, cpu, CPU seconds and file size"
            ),
            "none": "nothing: the policy can read any file the evaluator can",
        }[self.backend]
        return {"backend": self.backend, "protects": protects}
