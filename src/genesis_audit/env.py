"""The audit environment: reset/step lifecycle, budgets, tool dispatch and logging.

JSON-compatible Gymnasium-style contract:

    reset(seed, config) -> (observation, info)
    step(action)        -> (observation, reward, terminated, truncated, info)

An AuditEnv object holds private truth and belongs to the evaluator. Sharing a
Python process with a policy gives that policy no confidentiality at all: the
boundary is the out-of-process bridge under an OS confinement backend, not this
class. Methods named evaluator_* must never be exposed to a policy.
"""

from __future__ import annotations

import json
import math
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from . import ENV_VERSION, canon
from .calculator import evaluate
from .episodes import DirectorySource, EpisodeSource, InMemorySource, LoadedEpisode
from .errors import LifecycleError, MalformedSubmission, PolicyVisibleError
from .matching import EVIDENCE_RULES, MatchResult, match
from .perturb import perturb
from .prng import DEV_SECRET
from .schemas import Finding, parse_action, parse_submission
from .scoring import Score
from .store import is_int

__all__ = ["BRIDGE_REJECT", "DEV_SECRET", "AuditEnv", "DirectorySource", "InMemorySource", "LoadedEpisode"]

TASK = (
    "You are auditing one synthetic company for one reporting period. Inspect records with the tools, then "
    'submit findings once. Each step is one JSON action {"action": name, "args": {...}}. Actions: '
    "list_records(table, cursor, limit), get_record(table, id), get_document(doc_id), calculator(expression), "
    'submit(findings). Tables: ledger, invoices, payments, fx. submit takes {"findings": {"episode_id": ..., '
    '"findings": [{type, affected_ids, claimed_amount_minor, currency, evidence_ids, explanation}]}} and ends '
    "the episode. Submit an empty findings list if the books are clean. The policy object defines how to "
    "express each finding. evidence_ids must be ids a tool returns a record or document for: a ledger row_id, "
    "a document doc_id, an invoice_id, a payment_id or an fx key (date|source|target); any other id there voids "
    "the finding. Every step, valid or not, uses one unit of the step budget."
)
BRIDGE_REJECT = "_bridge_reject"  # pseudo-action the bridge sends for input it could not decode
MAX_ACTION_BYTES = 262_144  # one action as UTF-8 JSON; the bridge applies the same bound to a line
MAX_ACTION_DEPTH = 16  # a legal submission is nested 6 deep
MAX_WALL_TIME_S = 86_400.0
MODES = ("train", "eval")
CONFIG_KEYS = frozenset({"episode", "mode", "max_steps", "wall_time_limit_s", "evidence_rule", "perturb"})
DEFAULT_WALL_TIME_S = 60.0
FORCED_CAUSES = ("wall_time", "policy_exit", "protocol_abuse")
Transition = tuple[dict[str, Any], float, bool, bool, dict[str, Any]]


@dataclass
class _EpisodeState:
    """Mutable per-episode state. Created fresh by every reset; never shared."""

    loaded: LoadedEpisode
    seed: int | None
    config: dict[str, Any]
    mode: str
    evidence_rule: str
    max_steps: int
    started_at: float
    deadline: float | None
    id_mapping: dict[str, str]
    steps_used: int = 0
    inspection_steps: int = 0
    observed: set[str] = field(default_factory=set)
    terminated: bool = False
    truncated: bool = False
    termination_cause: str | None = None
    findings: tuple[Finding, ...] = ()
    result: MatchResult | None = None
    score: Score | None = None
    validation_error: str | None = None
    actions_after_end: int = 0
    internal_errors: list[str] = field(default_factory=list)
    trajectory: list[dict[str, Any]] = field(default_factory=list)
    elapsed_s: float | None = None

    @property
    def over(self) -> bool:
        return self.terminated or self.truncated

    @property
    def steps_remaining(self) -> int:
        return self.max_steps - self.steps_used


def _jsonable(value: object) -> Any:
    """A plain-JSON deep copy. Raises ValueError for anything that is not JSON data."""
    try:
        return json.loads(json.dumps(value, allow_nan=False))
    except (TypeError, RecursionError) as error:
        raise ValueError("not JSON data") from error


BROKEN_SUBMIT = {"action": "submit", "args": None}  # what an unusable submission attempt is reduced to


def _normalize_action(action: object) -> Any:
    """Reduce whatever a caller passed to bounded JSON data, or to a rejection the step can report.

    An object whose `action` is "submit" stays a submission attempt even when the rest of it is
    not usable JSON or is too large (PC-19): it becomes a submit with no payload, which is malformed
    and ends the episode. Only the official structural limits decide that, never a byte count alone.
    """
    attempt = isinstance(action, dict) and action.get("action") == "submit"
    try:
        text = json.dumps(action, allow_nan=False, ensure_ascii=False)
        size = len(text.encode("utf-8"))
    except (TypeError, ValueError, RecursionError):
        return dict(BROKEN_SUBMIT) if attempt else None  # not JSON at all: an invalid action
    if size > MAX_ACTION_BYTES:
        return dict(BROKEN_SUBMIT) if attempt else {BRIDGE_REJECT: "action_too_large"}
    value = json.loads(text)
    if canon.exceeds_depth(value, MAX_ACTION_DEPTH):
        return dict(BROKEN_SUBMIT) if attempt else None
    return value


class AuditEnv:
    def __init__(
        self,
        source: EpisodeSource,
        *,
        secret: bytes = DEV_SECRET,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._source = source
        self._secret = secret
        self._clock = clock
        self._state: _EpisodeState | None = None

    @classmethod
    def from_episode(
        cls, loaded: LoadedEpisode, *, secret: bytes = DEV_SECRET, clock: Callable[[], float] = time.monotonic
    ) -> AuditEnv:
        """An environment over one already loaded episode (in memory). reset() still needs an 'episode' name,
        which is only recorded in the evaluator report."""
        return cls(InMemorySource(loaded), secret=secret, clock=clock)

    # ------------------------------------------------------------------ lifecycle

    def reset(
        self, seed: int | None = None, config: Mapping[str, Any] | None = None, *, started_at: float | None = None
    ) -> tuple[dict, dict]:
        """Start a new, isolated episode. `config` must name the episode to load.

        The wall-time window opens here, before the episode is loaded, or at `started_at` when the
        caller opened it earlier (for instance before generating the episode). `started_at` is a
        reading of this environment's clock and may not lie in the future.
        """
        opened = self._clock()
        self._state = None  # a failed reset must not leave the previous episode live
        if started_at is not None:
            numeric = isinstance(started_at, int | float) and not isinstance(started_at, bool)
            if not numeric or not math.isfinite(started_at) or started_at > opened:
                raise LifecycleError("started_at must be a finite reading of the environment's clock, not later")
            opened = started_at
        config = dict(config or {})
        if set(config) - CONFIG_KEYS or "episode" not in config:
            got = sorted(map(repr, config))
            raise LifecycleError(f"config needs 'episode' and allows only {sorted(CONFIG_KEYS)}; got {got}")
        if seed is not None and not is_int(seed):
            raise LifecycleError("seed must be an integer or None")
        mode = config.get("mode", "train")
        evidence_rule = config.get("evidence_rule", "accessible")
        wall_time = config.get("wall_time_limit_s", DEFAULT_WALL_TIME_S)
        if mode not in MODES or evidence_rule not in EVIDENCE_RULES:
            raise LifecycleError(f"mode must be one of {MODES} and evidence_rule one of {EVIDENCE_RULES}")
        if wall_time is not None:
            numeric = isinstance(wall_time, int | float) and not isinstance(wall_time, bool)
            if not numeric or not math.isfinite(wall_time) or not 0 < wall_time <= MAX_WALL_TIME_S:
                raise LifecycleError(f"wall_time_limit_s must be None or a finite number in (0, {MAX_WALL_TIME_S:.0f}]")
        loaded = self._source.load(config["episode"])
        mapping: dict[str, str] = {}
        options = config.get("perturb")
        if options is not None:
            valid = isinstance(options, dict) and set(options) == {"rename_ids", "shuffle_rows"}
            if not valid or not all(isinstance(flag, bool) for flag in options.values()) or seed is None:
                raise LifecycleError(
                    "perturb needs an integer seed and exactly the booleans rename_ids and shuffle_rows"
                )
            loaded, mapping = perturb(loaded, key=self._secret, seed=seed, **options)
        limit = loaded.public.manifest["limits"]["max_steps"]
        max_steps = config.get("max_steps", limit)
        if not is_int(max_steps) or not 1 <= max_steps <= limit:
            raise LifecycleError("max_steps must be a positive integer no larger than the manifest's limit")
        state = _EpisodeState(
            loaded=loaded, seed=seed, config=_jsonable(config), mode=mode, evidence_rule=evidence_rule,
            max_steps=max_steps, started_at=opened, deadline=None if wall_time is None else opened + wall_time,
            id_mapping=mapping,
        )  # fmt: skip
        self._state = state
        public = loaded.public
        observation = {
            "task": TASK,
            "manifest": _jsonable(public.manifest),
            "policy": _jsonable(public.policy),
            "steps_remaining": max_steps,
        }
        info = {} if mode == "eval" else {"env_version": ENV_VERSION, "mode": mode}
        self._record(state, "reset", None, observation, None, info)
        return _jsonable(observation), dict(info)

    def step(self, action: object) -> Transition:
        state = self._require_state()
        if state.over:
            state.actions_after_end += 1
            closed = self._closed_observation(state)
            closed["error"] = PolicyVisibleError("episode_over").to_observation()
            return closed, 0.0, state.terminated, state.truncated, {}
        if state.deadline is not None and self._clock() > state.deadline:
            return self.truncate("wall_time")  # too late: the action is not executed, even a submit
        action = _normalize_action(action)
        state.steps_used += 1
        try:
            if isinstance(action, dict) and set(action) == {BRIDGE_REJECT}:
                code = action[BRIDGE_REJECT]
                raise PolicyVisibleError(code if code == "action_too_large" else "invalid_action")
            name, args = parse_action(action)
        except PolicyVisibleError as error:
            return self._after_inspection(state, action, {"error": error.to_observation()})
        except MalformedSubmission as error:  # a submit attempt with a broken envelope
            return self._malformed(state, action, error)
        if name == "submit":
            return self._submit(state, action, args)  # scoring bugs must surface to the evaluator, not be masked
        try:
            observation = self._inspect(state, name, args)
        except PolicyVisibleError as error:
            observation = {"error": error.to_observation()}
        except Exception as exc:  # noqa: BLE001 - nothing internal may reach the policy
            state.internal_errors.append(f"{type(exc).__name__}: {exc}"[:500])
            observation = {"error": PolicyVisibleError("internal_error").to_observation()}
        return self._after_inspection(state, action, observation)

    def truncate(self, cause: str) -> Transition:
        """Evaluator-forced truncation: wall time, a policy that exited, or a flooded bridge."""
        state = self._require_state()
        if cause not in FORCED_CAUSES:
            raise LifecycleError(f"truncate cause must be one of {FORCED_CAUSES}")
        if not state.over:
            self._finish(state, findings=(), cause=cause, truncated=True)
            reward, info = self._visible_reward(state), self._info(state)
            self._record(state, "forced_truncation", None, self._closed_observation(state), reward, info)
        info = self._info(state)
        return self._closed_observation(state), self._visible_reward(state), state.terminated, state.truncated, info

    @property
    def over(self) -> bool:
        return self._require_state().over

    def seconds_left(self) -> float | None:
        """Wall time left in this episode, or None when no limit is set."""
        state = self._require_state()
        return None if state.deadline is None else max(0.0, state.deadline - self._clock())

    # ---------------------------------------------------------------------- tools

    def _inspect(self, state: _EpisodeState, name: str, args: Mapping[str, Any]) -> dict[str, Any]:
        public = state.loaded.public
        if name == "calculator":
            return {"result": evaluate(args["expression"])}
        if name == "list_records":
            records, next_cursor = public.list_page(args["table"], args.get("cursor"), args.get("limit"))
            table = args["table"]
            state.observed.update(
                i for r in records for i in (public.evidence_id(table, r), public.record_id(table, r))
            )
            return {"records": records, "next_cursor": next_cursor}
        if name == "get_record":
            table, record = public.get_record(args["table"], args["id"])
        else:
            table, record = public.get_document(args["doc_id"])
        state.observed.update((public.evidence_id(table, record), public.record_id(table, record)))
        return {"record": record}

    def _after_inspection(self, state: _EpisodeState, action: Any, observation: dict[str, Any]) -> Transition:
        state.inspection_steps += 1
        if state.steps_remaining == 0:
            # The last allowed step was spent on inspection: truncate with an empty final submission.
            self._finish(state, findings=(), cause="step_limit", truncated=True)
            observation["status"] = "episode_over"
        observation["steps_remaining"] = state.steps_remaining
        return self._emit(state, action, observation)

    def _submit(self, state: _EpisodeState, action: Any, args: object) -> Transition:
        manifest = state.loaded.public.manifest
        try:
            findings = parse_submission(args, manifest["episode_id"], manifest["limits"])
        except MalformedSubmission as error:
            return self._malformed(state, action, error)
        self._finish(state, findings=findings, cause="submitted", truncated=False)
        return self._emit(state, action, self._closed_observation(state))

    def _malformed(self, state: _EpisodeState, action: Any, error: MalformedSubmission) -> Transition:
        """A malformed final submission ends the episode at -1. The detail stays in the evaluator log."""
        state.validation_error = error.detail
        state.score = Score.for_malformed(state.inspection_steps)
        state.terminated, state.termination_cause = True, "malformed_submission"
        state.elapsed_s = self._clock() - state.started_at
        return self._emit(state, action, self._closed_observation(state))

    def _finish(self, state: _EpisodeState, *, findings: tuple[Finding, ...], cause: str, truncated: bool) -> None:
        public = state.loaded.public
        state.findings = findings
        state.result = result = match(
            findings,
            state.loaded.truth,
            tolerance=state.loaded.tolerance(),
            universe=public.accessible_ids(),  # the one universe: score_episode and validate_truth use it too
            observed=frozenset(state.observed) if state.evidence_rule == "observed" else None,
        )
        state.score = Score.from_counts(result.tp, result.fp, result.fn, state.inspection_steps)
        state.terminated, state.truncated, state.termination_cause = not truncated, truncated, cause
        state.elapsed_s = self._clock() - state.started_at

    # ------------------------------------------------------- what the policy sees

    def _visible_reward(self, state: _EpisodeState) -> float:
        """0 for inspection. At the end: the common reward in train mode, numeric 0 in eval (closed) mode."""
        if state.score is None or state.mode != "train":
            return 0.0
        return float(state.score.reward)

    @staticmethod
    def _info(state: _EpisodeState) -> dict[str, Any]:
        """Nothing: the true reward and every diagnostic stay with the evaluator."""
        return {}

    @staticmethod
    def _closed_observation(state: _EpisodeState) -> dict[str, Any]:
        return {"status": "episode_over", "steps_remaining": state.steps_remaining}

    def _emit(self, state: _EpisodeState, action: Any, observation: dict[str, Any]) -> Transition:
        reward, info = self._visible_reward(state), self._info(state)
        self._record(state, "step", action, observation, reward, info)
        return _jsonable(observation), reward, state.terminated, state.truncated, info

    @staticmethod
    def _record(
        state: _EpisodeState, event: str, action: Any, observation: dict[str, Any], reward: float | None, info: dict
    ) -> None:
        """Append one transition. `event` is reset, step or forced_truncation: a policy cannot forge it."""
        state.trajectory.append(
            {
                "episode_id": state.loaded.public.manifest["episode_id"],
                "step": len(state.trajectory),
                "event": event,
                "action": action,
                "observation": _jsonable(observation),
                "reward": reward,
                "terminated": state.terminated,
                "truncated": state.truncated,
                "info": dict(info),
            }
        )

    # ------------------------------------------------------------- evaluator side

    def trajectory(self) -> list[dict[str, Any]]:
        """Exactly what the policy saw and did, one record per transition. Safe to publish."""
        return _jsonable(self._require_state().trajectory)

    def evaluator_view(self) -> LoadedEpisode:
        """The loaded episode including truth. For the oracle and for checks; never for a policy."""
        return self._require_state().loaded

    def evaluator_id_mapping(self) -> dict[str, str]:
        """Old id -> new id for a perturbed episode. Evaluator-only."""
        return dict(self._require_state().id_mapping)

    def evaluator_report(self) -> dict[str, Any]:
        """Scoring detail for the evaluator. Never pass this to a policy during a run."""
        state = self._require_state()
        if not state.over:
            raise LifecycleError("the evaluator report exists only after the episode has ended")
        report: dict[str, Any] = {
            "env_version": ENV_VERSION,
            "episode_id": state.loaded.public.manifest["episode_id"],
            "seed": state.seed,
            "config": state.config,
            "mode": state.mode,
            "evidence_rule": state.evidence_rule,
            "termination_cause": state.termination_cause,
            "steps_used": state.steps_used,
            "inspection_steps": state.inspection_steps,
            "submitted": state.termination_cause in ("submitted", "malformed_submission"),
            "valid_submission": state.termination_cause == "submitted",
            "validation_error": state.validation_error,
            "actions_after_end": state.actions_after_end,
            "internal_errors": list(state.internal_errors),
            "trajectory_digest": canon.digest(state.trajectory),
            "nondeterministic": {"elapsed_s": state.elapsed_s},
        }
        if state.score is not None:
            report["score"] = state.score.to_json()
        if state.result is not None:
            result = state.result
            report["counts"] = {"tp": result.tp, "fp": result.fp, "fn": result.fn}
            report["findings"] = [
                {"index": v.index, "matched_issue_id": v.matched_issue_id, "reasons": list(v.reasons)}
                for v in result.verdicts
            ]
            report["unmatched_issue_ids"] = list(result.unmatched_issue_ids)
        return report

    def _require_state(self) -> _EpisodeState:
        if self._state is None:
            raise LifecycleError("reset() must be called before step()")
        return self._state
