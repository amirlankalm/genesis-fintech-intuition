"""The tool bridge: the only channel between the evaluator and a policy process.

Protocol: JSON lines. The evaluator writes one "reset" message, then one "step"
message per action; the policy writes one action per line. The policy process
receives observations only. It runs under a Confinement backend, in its own
process group, with a scrubbed environment, and the whole group is killed when
the episode ends.

The policy is assumed hostile, so the evaluator's main thread never blocks on it:

* reading is done by a thread that delivers bounded lines through a bounded queue,
  so a fast writer is slowed by back-pressure instead of filling memory;
* writing is done by a thread, so a policy that never reads cannot stall the loop;
* stderr is drained by a thread that keeps only its first bytes;
* a fourth thread reports when the process has exited, because a child it started
  can hold its pipes open long after;
* the only wait in the main loop is for the next action, and it ends at the
  episode's wall-time deadline.

A line longer than MAX_LINE_BYTES is an invalid action that costs a step, unless it
is recognisably a submission (a top-level "action": "submit" member, found by a
streaming scan): then it is a malformed submission, which ends the episode. More
than MAX_EPISODE_BYTES in one episode ends it. Silence runs into the wall-time
limit. Exiting early truncates the episode.
"""

from __future__ import annotations

import json
import os
import queue
import re
import signal
import subprocess
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any

from . import canon
from .env import BRIDGE_REJECT, BROKEN_SUBMIT, MAX_ACTION_BYTES, MAX_ACTION_DEPTH, AuditEnv
from .errors import LifecycleError
from .sandbox import Confinement

MAX_LINE_BYTES = MAX_ACTION_BYTES  # one action as UTF-8 JSON, newline excluded
MAX_EPISODE_BYTES = 32 * 1024 * 1024  # 100 maximal actions fit; a flood does not
STDERR_KEEP_BYTES = 2000
_INBOX_SIZE = 8
_READ_CHUNK = 65_536


class _Marker:
    """A non-data item in the inbox."""

    def __init__(self, name: str) -> None:
        self.name = name


_EOF, _TOO_LARGE, _FLOOD, _EXITED = _Marker("eof"), _Marker("too_large"), _Marker("flood"), _Marker("exited")
_TOO_LARGE_SUBMIT = _Marker("too_large_submit")
_EXIT_GRACE_S = 0.2  # after the policy exits, how long to wait for lines it had already written


@dataclass(frozen=True)
class PolicyRun:
    report: dict[str, Any]  # evaluator-only
    trajectory: list[dict[str, Any]]  # exactly what the policy saw and did
    process: dict[str, Any]  # evaluator-only: backend, exit code, bounded stderr


_IN_STRING = re.compile(rb'["\\]')
_TOP_LEVEL = re.compile(rb"[^ \t\r\n]")
_STRUCTURE = re.compile(rb'["{}\[\],]')
_LITERAL_KEEP = 8  # long enough for "action" and "submit"; a longer literal can match neither


class SubmitScanner:
    """canon.is_submission_attempt over a line that arrives in chunks and is never held whole.

    Same rule: a string literal "submit" as the value of a member named "action" directly inside
    the outermost object. Regular-expression skips keep the scan at C speed over long strings.
    """

    def __init__(self) -> None:
        self.depth = 0
        self.in_string = False
        self.escaped = False
        self.literal: bytearray | None = None
        self.name: bytes | None = None
        self.want_name = False
        self.verdict: bool | None = None

    def feed(self, chunk: bytes) -> None:
        position, size = 0, len(chunk)
        while position < size and self.verdict is None:
            position = self._string(chunk, position) if self.in_string else self._structure(chunk, position)

    def finish(self) -> bool:
        """End of the line: an unterminated last literal still counts, as in the one-pass version."""
        if self.in_string and self.verdict is None:
            self.in_string = False
            self._close_literal(None if self.literal is None else bytes(self.literal))
        return self.verdict is True

    def _keep(self, data: bytes) -> None:
        if self.literal is not None:
            self.literal += data
            if len(self.literal) > _LITERAL_KEEP:
                self.literal = None

    def _string(self, chunk: bytes, position: int) -> int:
        if self.escaped:  # the character after a backslash belongs to the literal, whatever it is
            self.escaped = False
            self._keep(chunk[position : position + 1])
            return position + 1
        found = _IN_STRING.search(chunk, position)
        if found is None:
            self._keep(chunk[position:])
            return len(chunk)
        stop = found.start()
        self._keep(chunk[position:stop])
        if chunk[stop : stop + 1] == b"\\":
            self.escaped = True
            self._keep(b"\\")
            return stop + 1
        self.in_string = False
        self._close_literal(None if self.literal is None else bytes(self.literal))
        return stop + 1

    def _close_literal(self, literal: bytes | None) -> None:
        if self.depth == 1 and self.want_name:
            self.name, self.want_name = literal, False
        elif self.depth == 1 and self.name == b"action" and literal == b"submit":
            self.verdict = True

    def _structure(self, chunk: bytes, position: int) -> int:
        found = (_TOP_LEVEL if self.depth == 0 else _STRUCTURE).search(chunk, position)
        if found is None:
            return len(chunk)
        stop = found.start()
        character = chunk[stop : stop + 1]
        if character == b'"':
            self.in_string, self.literal = True, bytearray()
        elif character in (b"{", b"["):
            self.depth += 1
            if self.depth == 1 and character == b"[":
                self.verdict = False  # the top-level value is an array
            elif self.depth == 1:
                self.want_name = True
        elif character in (b"}", b"]"):
            self.depth -= 1
        elif character == b"," and self.depth == 1:
            self.name, self.want_name = None, True
        elif self.depth == 0:
            self.verdict = False  # the top-level value is not an object
        return stop + 1


def _read_actions(stream: IO[bytes], inbox: queue.Queue, stop: threading.Event) -> None:
    """Reader thread: split the policy's stdout into bounded lines and hand them over one at a time."""

    def deliver(item: bytes | _Marker) -> bool:
        while not stop.is_set():
            try:
                inbox.put(item, timeout=0.1)
                return True
            except queue.Full:
                continue
        return False

    buffer = bytearray()
    scanner: SubmitScanner | None = None  # set while inside a line that already exceeded the bound
    total = 0
    while not stop.is_set():
        try:
            chunk = stream.read(_READ_CHUNK)
        except (OSError, ValueError):
            chunk = b""
        if not chunk:
            if scanner is not None:  # an oversized last line counts only if it was a submission
                scanner.feed(bytes(buffer))
                if scanner.finish():
                    deliver(_TOO_LARGE_SUBMIT)
            elif buffer:  # a last line without its newline is still an action
                deliver(_oversized(bytes(buffer)) if len(buffer) > MAX_LINE_BYTES else bytes(buffer))
            deliver(_EOF)
            return
        total += len(chunk)
        if total > MAX_EPISODE_BYTES:
            deliver(_FLOOD)
            return
        buffer += chunk
        while True:
            newline = buffer.find(b"\n")
            if newline < 0:
                if scanner is not None or len(buffer) > MAX_LINE_BYTES:
                    scanner = scanner or SubmitScanner()
                    scanner.feed(bytes(buffer))
                    buffer.clear()
                break
            line = bytes(buffer[:newline])
            del buffer[: newline + 1]
            item: bytes | _Marker = line
            if scanner is not None or len(line) > MAX_LINE_BYTES:
                scanner = scanner or SubmitScanner()
                scanner.feed(line)
                item, scanner = (_TOO_LARGE_SUBMIT if scanner.finish() else _TOO_LARGE), None
            if not deliver(item):
                return


def _watch_exit(process: subprocess.Popen, inbox: queue.Queue, stop: threading.Event) -> None:
    """Exit thread: report that the policy process has ended.

    End-of-file on its stdout is not enough: a child it started can keep the pipe open.
    """
    process.wait()
    while not stop.is_set():
        try:
            inbox.put(_EXITED, timeout=0.1)
            return
        except queue.Full:
            continue


def _write_messages(stream: IO[bytes], outbox: queue.Queue) -> None:
    """Writer thread: the only place that writes to the policy. It may block; nothing waits on it."""
    while True:
        data = outbox.get()
        if data is None:
            return
        view = memoryview(data)
        try:
            while view:
                written = stream.write(view)
                view = view[written or 0 :]
        except (OSError, ValueError):
            return


def _drain_stderr(stream: IO[bytes], head: bytearray) -> None:
    """Stderr thread: keep the first bytes for the evaluator's record, discard the rest."""
    while True:
        try:
            chunk = stream.read(_READ_CHUNK)
        except (OSError, ValueError):
            return
        if not chunk:
            return
        if len(head) < STDERR_KEEP_BYTES:
            head += chunk[: STDERR_KEEP_BYTES - len(head)]


def _oversized(line: bytes) -> _Marker:
    scanner = SubmitScanner()
    scanner.feed(line)
    return _TOO_LARGE_SUBMIT if scanner.finish() else _TOO_LARGE


def decode_action(item: bytes | _Marker) -> object:
    """Turn one received line into an action. Undecodable input becomes a bridge rejection.

    An oversized line that is a submission attempt is a malformed submission (PC-19), not an
    invalid inspection: the size bound must not let a policy dodge the -1 of a broken submit.
    """
    if item is _TOO_LARGE_SUBMIT:
        return dict(BROKEN_SUBMIT)
    if isinstance(item, _Marker):
        return {BRIDGE_REJECT: "action_too_large"}
    try:
        text = item.decode("utf-8")
    except UnicodeDecodeError:
        return {BRIDGE_REJECT: "invalid_action"}
    try:
        return canon.loads_strict(text, max_depth=MAX_ACTION_DEPTH)
    except ValueError:
        # Refused by the strict parser. If it is recognisably a submission attempt it takes the
        # submission branch and is malformed (PC-19); anything else is an invalid action.
        return dict(BROKEN_SUBMIT) if canon.is_submission_attempt(text) else {BRIDGE_REJECT: "invalid_action"}


def _kill_group(process: subprocess.Popen) -> None:
    """Kill the policy and anything it started. It was launched as the leader of its own group."""
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def _stop(
    process: subprocess.Popen,
    threads: Sequence[threading.Thread],
    stop: threading.Event,
    outbox: queue.Queue,
    cleanup: Sequence[str] | None,
) -> int | None:
    """End the policy process and every helper thread. Never blocks on the policy."""
    writer = threads[1]
    outbox.put(None)
    writer.join(timeout=0.5)  # let the final message out, unless the policy is not reading
    stop.set()
    for stream in (process.stdin,):
        try:
            if stream is not None:
                stream.close()  # end of input is the polite signal to exit
        except OSError:
            pass
    try:
        process.wait(timeout=0.5)
    except subprocess.TimeoutExpired:
        pass
    _kill_group(process)  # also removes children that outlived a policy which exited by itself
    exit_code = process.wait()
    if cleanup:  # a container can outlive its client: remove it by name, and never let that fail the run
        try:
            subprocess.run(list(cleanup), capture_output=True, check=False, timeout=30)
        except (OSError, subprocess.SubprocessError):
            pass
    for thread in threads:
        thread.join(timeout=1)
    for stream in (process.stdout, process.stderr):
        try:
            # Unbuffered pipes: closing cannot wait on a lock held by a thread still blocked in read.
            if stream is not None:
                stream.close()
        except OSError:
            pass
    return exit_code


def run_policy(
    env: AuditEnv,
    script: Path,
    args: Sequence[str],
    *,
    seed: int | None,
    config: Mapping[str, Any],
    confinement: Confinement,
) -> PolicyRun:
    """Run one episode with an out-of-process policy and return the evaluator's records."""
    argv, popen_kwargs = confinement.launch(script, args)
    observation, info = env.reset(seed, config)
    if env.seconds_left() is None:
        raise LifecycleError("a bridged episode needs a wall-time limit: an unresponsive policy would never end it")
    process = subprocess.Popen(
        argv,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0,  # raw pipes: no buffer lock for a reader and a closer to fight over
        start_new_session=True,  # its own process group, so the whole group can be killed
        **popen_kwargs,
    )
    assert process.stdin is not None and process.stdout is not None and process.stderr is not None
    inbox: queue.Queue = queue.Queue(maxsize=_INBOX_SIZE)
    outbox: queue.Queue = queue.Queue()  # at most one message per step, so bounded by the step budget
    stop = threading.Event()
    stderr_head = bytearray()
    threads = [
        threading.Thread(target=_read_actions, args=(process.stdout, inbox, stop), daemon=True),
        threading.Thread(target=_write_messages, args=(process.stdin, outbox), daemon=True),
        threading.Thread(target=_drain_stderr, args=(process.stderr, stderr_head), daemon=True),
        threading.Thread(target=_watch_exit, args=(process, inbox, stop), daemon=True),
    ]
    for thread in threads:
        thread.start()

    def send(message: Mapping[str, Any]) -> None:
        outbox.put(json.dumps(message, separators=(",", ":")).encode("ascii") + b"\n")

    try:
        send({"type": "reset", "observation": observation, "info": info})
        exited = False
        while not env.over:
            remaining = env.seconds_left() or 0.0
            try:
                item = inbox.get(timeout=min(remaining, _EXIT_GRACE_S) if exited else remaining)
            except queue.Empty:
                env.truncate("policy_exit" if exited and (env.seconds_left() or 0.0) > 0 else "wall_time")
                break
            if item is _EXITED:
                exited = True  # keep serving what it wrote before it went, then stop
            elif item is _EOF:
                env.truncate("policy_exit")
            elif item is _FLOOD:
                env.truncate("protocol_abuse")
            else:
                observation, reward, terminated, truncated, info = env.step(decode_action(item))
                send({"type": "step", "observation": observation, "reward": reward, "terminated": terminated,
                      "truncated": truncated, "info": info})  # fmt: skip
    finally:
        exit_code = _stop(process, threads, stop, outbox, confinement.cleanup_command(argv))
    process_record = {
        **confinement.describe(),
        "script": Path(script).name,
        "args": list(args),
        "exit_code": exit_code,
        "stderr_head": bytes(stderr_head).decode("utf-8", "replace"),
    }
    return PolicyRun(report=env.evaluator_report(), trajectory=env.trajectory(), process=process_record)
