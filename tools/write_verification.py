"""Run every verification command on the current tree and write docs/VERIFICATION.md.

The log names the exact tree it was measured on: a SHA-256 over the content of every
file git would commit (tracked or untracked, not ignored), the log itself excluded.
Anyone can recompute that digest and see whether the log still describes their tree.

Usage: python tools/write_verification.py            (from the repository root)
"""

from __future__ import annotations

import hashlib
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG = ROOT / "docs" / "VERIFICATION.md"
TAIL_LINES = 14
DOCKER_IMAGE = "python:3.11-slim"


def tree_digest() -> tuple[str, int]:
    """Digest of everything git would commit, except this log."""
    listed = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout.splitlines()  # fmt: skip
    files = sorted(name for name in listed if name != "docs/VERIFICATION.md" and (ROOT / name).is_file())
    digest = hashlib.sha256()
    for name in files:
        digest.update(name.encode("utf-8") + b"\0" + hashlib.sha256((ROOT / name).read_bytes()).digest())
    return digest.hexdigest(), len(files)


def git_state() -> str:
    """HEAD and whether the working tree differs from it, as text for the log."""

    def git(*args: str) -> str:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=False).stdout.strip()

    head, branch = git("rev-parse", "--short", "HEAD") or "no commit", git("branch", "--show-current") or "detached"
    dirty = [line for line in git("status", "--porcelain").splitlines() if not line.endswith("docs/VERIFICATION.md")]
    state = f"{len(dirty)} uncommitted path(s) on top of it" if dirty else "working tree clean apart from this log"
    return f"HEAD `{head}` on `{branch}`, {state}."


def run(label: str, command: list[str], env_extra: dict[str, str] | None = None, timeout: int = 900) -> tuple[str, str]:
    import os

    try:
        done = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False, timeout=timeout,
                              env={**os.environ, **(env_extra or {})})  # fmt: skip
        lines = [line for line in (done.stdout + done.stderr).splitlines() if line.strip()]
        status = "exit 0" if done.returncode == 0 else f"EXIT {done.returncode}"
    except (OSError, subprocess.TimeoutExpired) as error:
        lines, status = [f"{type(error).__name__}: {error}"], "DID NOT RUN"
    kept = lines[-TAIL_LINES:]
    # A long run can push its test summary out of the tail: keep every summary line as well.
    summaries = [line for line in lines[:-TAIL_LINES] if " passed" in line or " failed" in line]
    tail = "\n".join([*summaries, *(["..."] if summaries else []), *kept])
    return f"### {label}\n\n`{' '.join(command)}` -> **{status}**\n\n```\n{tail}\n```\n", status


def main() -> int:
    digest, count = tree_digest()
    sections, statuses = [], []
    plan: list[tuple[str, list[str], dict[str, str] | None]] = [
        ("Lint, format and types", ["make", "lint"], None),
        ("Tests with coverage (gate 80%)", ["make", "test"], None),
        ("Self-check on this machine", ["uv", "run", "python", "-m", "genesis_audit", "check"], None),
    ]
    for version in ("3.12", "3.13"):
        interpreter = shutil.which(f"python{version}")
        if interpreter:
            plan.append((f"Self-check under Python {version} (no virtual environment)",
                         [interpreter, "-m", "genesis_audit", "check"], {"PYTHONPATH": str(ROOT / "src")}))  # fmt: skip
    if shutil.which("docker"):
        plan.append(("Container: Python 3.11, no network, 60s limit; evaluator as root, policies under setuid",
                     ["make", "docker-check"], None))  # fmt: skip
        plan.append(("Per-policy Docker backend: hostile probe",
                     ["uv", "run", "pytest", "-p", "no:cacheprovider", "tests/test_boundary.py", "-k", "docker"],
                     {"GENESIS_AUDIT_DOCKER_IMAGE": DOCKER_IMAGE}))  # fmt: skip
    for label, command, env_extra in plan:
        section, status = run(label, command, env_extra)
        sections.append(section)
        statuses.append(status)
        sys.stdout.write(f"{status:12s} {label}\n")
        sys.stdout.flush()
    after, _ = tree_digest()
    header = [
        "# Verification log",
        "",
        "Written by `python tools/write_verification.py`. Every block is the tail of a command that was run on",
        "the tree named below. Nothing here is typed in by hand.",
        "",
        f"- **Tree digest:** `{digest}` over {count} files (everything git would commit, this log excluded).",
        f"- **Tree unchanged by the run:** {'yes' if after == digest else 'NO - the commands modified files'}.",
        f"- **Host:** {platform.system()} {platform.machine()}, Python {platform.python_version()} for this script.",
        f"- **Git state when run:** {git_state()}",
        "  The digest above identifies the tree whether or not it is committed. Recompute it with `tree_digest` in this script.",
        f"- **Result:** {sum(status == 'exit 0' for status in statuses)} of {len(statuses)} commands exited 0.",
        "",
    ]
    LOG.write_text("\n".join(header) + "\n" + "\n".join(sections), encoding="utf-8")
    return 0 if all(status == "exit 0" for status in statuses) else 1


if __name__ == "__main__":
    raise SystemExit(main())
