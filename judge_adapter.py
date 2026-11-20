"""The jury adapter of the Genesis FinTech case: three entry points over this repository's environment.

    generate_episode(seed, config, output_dir) -> None
    make_env() -> JudgeEnv            # reset(seed, config) -> (observation, info)
                                      # step(action) -> (observation, reward, terminated, truncated, info)
    score_episode(episode_dir, findings, inspection_steps) -> dict

It is a thin translation layer, never a second environment: generation is `genesis_audit.shipped`, loading is
`genesis_audit.episodes.load_episode_dir`, the tools, budgets and clock are `genesis_audit.env.AuditEnv`, and
scoring is `genesis_audit.scoring.score_submission`. The adapter translates only the official envelope
{"name", "args"} into the core one {"action", "args"}, the core observations into {"result", "error",
"remaining_steps"}, and the reward and info into what the official closed mode allows (0.0 and {}).

Everything here belongs to the jury process. `score_episode`, `oracle_findings` and `JudgeEnv.evaluator_report`
read the closed truth and must never be reachable by a policy. The evaluator log is the Python logger
"judge_adapter" (and "genesis_audit.loader" for the episode loader); configure logging to keep it.

Reference: docs/ADAPTER.md.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

# The repository's own package, whether or not it is installed (repo root, container /app, or any cwd).
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from genesis_audit import ENV_VERSION, env, oracle, paths, shipped
from genesis_audit.episodes import LoadedEpisode, load_episode_dir
from genesis_audit.errors import POLICY_ERRORS, EpisodeError, LifecycleError
from genesis_audit.scoring import Score, score_submission
from genesis_audit.store import is_int

__all__ = [
    "ADAPTER_VERSION",
    "ENV_VERSION",
    "EPISODE_FILE_NAMES",
    "TASK",
    "PUBLIC_ERROR_CODES",
    "AdapterError",
    "JudgeEnv",
    "generate_episode",
    "make_env",
    "oracle_findings",
    "score_episode",
]

ADAPTER_VERSION = "genesis-judge-adapter/1.0.0"
LOG = logging.getLogger("judge_adapter")

MODES = ("closed", "train")
CONFIG_KEYS = ("mode", "episode_dir", "team_config")
VARIANT = "judge"  # recorded in provenance.json; generate_episode and train-mode generation use the same one
INTERNAL_EPISODE = "episode"  # the core needs a name; it is recorded in the evaluator report only
EPISODE_FILE_NAMES = ("manifest.json", "policy.json", "ledger.csv", "invoices.jsonl", "payments.jsonl", "fx.csv")

# Every error a policy can receive: the core's codes, with the envelope message in the official words, plus the
# one code the adapter adds for a submit that is not a valid findings.json structure.
INVALID_SUBMISSION = "invalid_submission"
PUBLIC_ERRORS: dict[str, str] = {
    **POLICY_ERRORS,
    "invalid_action": "action must be an object with exactly the keys 'name' and 'args'",
    INVALID_SUBMISSION: "submit did not carry a valid findings.json structure; the episode has ended",
}
PUBLIC_ERROR_CODES = tuple(sorted(PUBLIC_ERRORS))

# The core task text names the core envelope; the policy is told the official one instead.
_CORE_ENVELOPE = '{"action": name, "args": {...}}'
_OFFICIAL_ENVELOPE = '{"name": name, "args": {...}}'


class AdapterError(ValueError):
    """A jury-side usage error (bad seed, config or directory). Never shown to a policy."""


def _task_text() -> str:
    if _CORE_ENVELOPE not in env.TASK:
        raise RuntimeError("the core task text no longer names the core envelope; update the adapter")
    return env.TASK.replace(_CORE_ENVELOPE, _OFFICIAL_ENVELOPE)


TASK = _task_text()


# --------------------------------------------------------------------------------------------- generation


def _seed(seed: object) -> int:
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise AdapterError(f"seed must be a non-negative integer; got {seed!r}")
    return seed


def _generate(seed: object, config: Mapping[str, Any] | None) -> tuple[Any, Any, Any]:
    """The team generator for (seed, config): (public episode, truth, provenance). Config errors are refused."""
    number = _seed(seed)
    try:
        settings, inject = shipped.parse_config(config)
        return shipped.generate(number, settings, inject, secret=paths.evaluator_secret(), variant=VARIANT)
    except EpisodeError as exc:
        raise AdapterError(f"generator config refused: {exc}") from exc


def generate_episode(seed: int, config: dict, output_dir: str) -> None:
    """Write one generated episode as 8 flat files into output_dir (created if missing).

    config is {"generator": {...}, "inject": {...}} (both optional; schema docs/schemas/generator_config.schema.json).
    Nothing is written when the request is refused. The eight files are overwritten; other files are left alone.
    """
    public, truth, provenance = _generate(seed, config)
    public_files, private_files = shipped.books.render(public, truth, provenance)
    directory = Path(os.fspath(output_dir))
    directory.mkdir(parents=True, exist_ok=True)
    for name, text in {**public_files, **private_files}.items():
        (directory / name).write_bytes(text.encode("utf-8"))
    LOG.info(
        "generate_episode %s",
        json.dumps({"adapter_version": ADAPTER_VERSION, "env_version": ENV_VERSION, "seed": seed,
                    "config": config, "output_dir": str(directory),
                    "episode_id": public.manifest["episode_id"]}, default=repr),
    )  # fmt: skip


# ------------------------------------------------------------------------------------------------ loading


def _load(episode_dir: object) -> LoadedEpisode:
    """One flat episode directory, loaded as the jury path does (formats enforced, consistency warned)."""
    if not isinstance(episode_dir, str | os.PathLike):
        raise AdapterError(f"episode_dir must be a path string; got {type(episode_dir).__name__}")
    try:
        loaded = load_episode_dir(Path(os.fspath(episode_dir)), strict=False)
    except EpisodeError as exc:
        raise AdapterError(f"episode directory refused: {exc}") from exc
    if loaded.warnings:
        LOG.warning("episode %s loaded with %d warnings", loaded.public.manifest["episode_id"], len(loaded.warnings))
    return loaded


def _score(loaded: LoadedEpisode, findings: object, inspection_steps: int) -> Score:
    """Exactly the scoring the environment applies at the end of an episode (same universe and tolerance)."""
    manifest = loaded.public.manifest
    verification = score_submission(
        findings,
        loaded.truth,
        episode_id=manifest["episode_id"],
        limits=manifest["limits"],
        tolerance=loaded.tolerance(),
        universe=loaded.public.accessible_ids(),  # the env's universe (env._finish); keep the two equal
        inspection_steps=inspection_steps,
    )
    if verification.error is not None:
        LOG.warning("invalid submission (return -1) on %s: %s", manifest["episode_id"], verification.error)
    return verification.score


def score_episode(episode_dir: str, findings: dict, inspection_steps: int) -> dict:
    """{"tp","fp","fn","precision","recall","f1","return"} for a findings.json object; jury side only.

    An invalid structure gives return -1.0 and None for the other six; the reason goes to the evaluator log.
    """
    if isinstance(inspection_steps, bool) or not isinstance(inspection_steps, int) or inspection_steps < 0:
        raise AdapterError(f"inspection_steps must be a non-negative integer; got {inspection_steps!r}")
    return _score(_load(episode_dir), findings, inspection_steps).to_official()


def oracle_findings(episode_dir: str) -> dict:
    """The findings.json object built from the episode's truth.json. Benchmark oracle evaluation only.

    Per truth issue: type, affected_ids, claimed_amount_minor = expected_amount_minor, currency, and the smallest
    acceptable evidence set as evidence_ids; episode_id from the manifest.
    """
    loaded = _load(episode_dir)
    return {"episode_id": loaded.public.manifest["episode_id"], "findings": oracle.oracle_findings(loaded)}


# ----------------------------------------------------------------------------------------- the environment


def _core_action(action: object) -> object:
    """{"name", "args"} -> {"action", "args"}. Other shapes keep their brokenness.

    The two key names are swapped, so an object that is not exactly {"name", "args"} stays invalid for the core:
    {"action": "submit", ...} without "name" becomes an invalid action (not a submit), and a submit with extra
    keys stays a malformed submit. Non-objects pass through and are invalid actions.
    """
    if not isinstance(action, dict):
        return action
    swap = {"name": "action", "action": "name"}
    return {swap.get(key, key): value for key, value in action.items()}


def _public_error(error: Mapping[str, str]) -> dict[str, str]:
    code = error["code"]
    return {"code": code, "message": PUBLIC_ERRORS[code]}


class JudgeEnv:
    """The object make_env() returns. One episode at a time; every reset starts a fresh core environment."""

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._core: env.AuditEnv | None = None
        self._closed = True
        self._jury: dict[str, Any] = {}

    def reset(self, seed: int | None = None, config: dict | None = None) -> tuple[dict, dict]:
        """config = {"mode": "closed"|"train", "episode_dir": str, "team_config": {...}}.

        closed: loads exactly episode_dir (required), seed ignored. train: loads episode_dir when given, else
        generates from (seed, team_config). The 60 s window opens at the top of this call.
        """
        started_at = self._clock()
        self._core = None  # a refused reset leaves no live episode
        config = {} if config is None else config
        if not isinstance(config, Mapping):
            raise AdapterError("config must be an object with keys mode, episode_dir, team_config")
        unknown = sorted(set(config) - set(CONFIG_KEYS))
        if unknown:
            LOG.warning("reset: ignoring unknown config keys %s", unknown)
        mode = config.get("mode", "closed")
        if mode not in MODES:
            raise AdapterError(f"config.mode must be one of {list(MODES)}; got {mode!r}")
        episode_dir = config.get("episode_dir")
        if mode == "closed" and episode_dir is None:
            raise AdapterError("closed mode needs config.episode_dir; it never generates an episode")
        if episode_dir is not None:
            loaded = _load(episode_dir)
        else:
            public, truth, provenance = _generate(seed, config.get("team_config"))
            loaded = LoadedEpisode(public=public, truth=truth, provenance=provenance)
        core = env.AuditEnv.from_episode(loaded, secret=paths.evaluator_secret(), clock=self._clock)
        core_seed = seed if seed is None or is_int(seed) else None  # closed mode accepts and ignores any seed
        core_mode = "eval" if mode == "closed" else "train"
        observation, info = core.reset(core_seed, {"episode": INTERNAL_EPISODE, "mode": core_mode},
                                       started_at=started_at)  # fmt: skip
        self._core, self._closed = core, mode == "closed"
        self._jury = {"adapter_version": ADAPTER_VERSION, "env_version": ENV_VERSION, "seed": seed,
                      "config": config, "episode_id": observation["manifest"]["episode_id"]}  # fmt: skip
        LOG.info("reset %s", json.dumps(self._jury, default=repr, sort_keys=True))
        first = {
            "task": TASK,
            "manifest": observation["manifest"],
            "policy": observation["policy"],
            "remaining_steps": observation["steps_remaining"],
        }
        return first, ({} if self._closed else dict(info))

    def step(self, action: dict) -> tuple[dict, float, bool, bool, dict]:
        """One action {"name": ..., "args": {...}} -> (observation, reward, terminated, truncated, info)."""
        core = self._require()
        was_over = core.over
        observation, reward, terminated, truncated, _ = core.step(_core_action(action))
        result, error = self._translate(observation, ended_now=not was_over and core.over)
        visible = 0.0 if self._closed else float(reward)
        official = {"result": result, "error": error, "remaining_steps": observation["steps_remaining"]}
        return official, visible, bool(terminated), bool(truncated), {}

    def _translate(self, observation: Mapping[str, Any], *, ended_now: bool) -> tuple[Any, dict[str, str] | None]:
        if "error" in observation:
            return None, _public_error(observation["error"])
        if "records" in observation:
            return {"records": observation["records"], "next_cursor": observation["next_cursor"]}, None
        if "record" in observation:
            return observation["record"], None
        if "result" in observation:
            return observation["result"], None
        if ended_now:
            return self._ending()
        return None, None

    def _ending(self) -> tuple[Any, dict[str, str] | None]:
        """The episode ended on this step without a tool result: a submit, or the time limit."""
        report = self.evaluator_report()
        cause = report["termination_cause"]
        LOG.info("episode %s over: %s after %d inspection steps", report["episode_id"], cause,
                 report["inspection_steps"])  # fmt: skip
        if cause == "submitted":
            return {"accepted": True}, None
        if cause == "malformed_submission":
            LOG.warning("invalid submission (return -1): %s", report["validation_error"])
            return None, {"code": INVALID_SUBMISSION, "message": PUBLIC_ERRORS[INVALID_SUBMISSION]}
        return None, None  # wall time: truncated, empty findings

    def evaluator_report(self) -> dict[str, Any]:
        """Jury only, after the episode has ended: the core report (score, counts, matched pairs, cause, steps)
        plus adapter version, seed and the config reset was given."""
        report = self._require().evaluator_report()
        return {**report, "judge": dict(self._jury)}

    def _require(self) -> env.AuditEnv:
        if self._core is None:
            raise LifecycleError("reset() must succeed before step()")
        return self._core


def make_env() -> JudgeEnv:
    """A fresh environment object with reset(seed, config) and step(action)."""
    return JudgeEnv()
