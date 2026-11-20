"""Driving judge_adapter's env the way the jury's harness does: official envelope only."""

from __future__ import annotations

import json
import math
from typing import Any

from jury_data import fx_key

import judge_adapter


def act(name: str, **args: Any) -> dict[str, Any]:
    return {"name": name, "args": args}


def is_json_value(value: Any) -> bool:
    """Strict JSON compatibility: dict with str keys, list, str, int, float (finite), bool, None."""
    if value is None or isinstance(value, (str, bool)):
        return True
    if isinstance(value, int):
        return True
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, list):
        return all(is_json_value(v) for v in value)
    if isinstance(value, dict):
        return all(isinstance(k, str) and is_json_value(v) for k, v in value.items())
    return False


def roundtrips(value: Any) -> bool:
    return is_json_value(value) and json.loads(json.dumps(value, allow_nan=False)) == value


class Run:
    """One env with a transcript. steps counts every step call; inspection = steps before the first submit."""

    def __init__(self, env: Any | None = None):
        self.env = env if env is not None else judge_adapter.make_env()
        self.transcript: list[tuple] = []
        self.first_obs: dict | None = None
        self.reset_info: dict | None = None
        self.steps = 0
        self.inspection_steps: int | None = None

    def reset(self, episode_dir: str, seed: int = 0, mode: str = "closed", **extra: Any) -> dict:
        cfg = {"mode": mode, "episode_dir": episode_dir, "team_config": {}}
        cfg.update(extra)
        obs, info = self.env.reset(seed, cfg)
        self.first_obs, self.reset_info = obs, info
        self.transcript = [("reset", obs, info)]
        self.steps = 0
        self.inspection_steps = None
        return obs

    def step(self, action: dict) -> tuple:
        if isinstance(action, dict) and action.get("name") == "submit" and self.inspection_steps is None:
            self.inspection_steps = self.steps
        out = self.env.step(action)
        self.steps += 1
        self.transcript.append((action, *out))
        return out

    def observations(self) -> list:
        return [self.first_obs] + [t[1] for t in self.transcript[1:]]


def list_all(run: Run, table: str, limit: int = 50) -> tuple[list[dict], list[list[dict]]]:
    records: list[dict] = []
    pages: list[list[dict]] = []
    cursor = None
    while True:
        obs, *_ = run.step(act("list_records", table=table, cursor=cursor, limit=limit))
        assert obs["error"] is None, f"list_records {table} failed: {obs['error']}"
        page = obs["result"]["records"]
        pages.append(page)
        records.extend(page)
        cursor = obs["result"]["next_cursor"]
        if cursor is None:
            return records, pages


def public_view(episode_dir: str) -> tuple[dict[str, list[dict]], Run]:
    run = Run()
    run.reset(episode_dir)
    view = {t: list_all(run, t)[0] for t in ("ledger", "invoices", "payments", "fx")}
    return view, run


def fetch_evidence(run: Run, ident: str, doc_ids: set[str], row_ids: set[str], fx_keys: set[str]) -> tuple:
    if ident in doc_ids:
        a = act("get_document", doc_id=ident)
    elif ident in row_ids:
        a = act("get_record", table="ledger", id=ident)
    elif ident in fx_keys:
        a = act("get_record", table="fx", id=ident)
    else:
        return None, f"{ident} is no ledger row, document or fx key of the published data"
    obs, *_ = run.step(a)
    return obs, None


def id_sets(ep: dict) -> tuple[set[str], set[str], set[str]]:
    return (
        {d["doc_id"] for d in ep["invoices"] + ep["payments"]},
        {r["row_id"] for r in ep["ledger"]},
        {fx_key(r) for r in ep["fx"]},
    )


def oracle_from_truth(truth: dict, episode_id: str | None = None) -> dict:
    """The jury's own oracle (ADAPTER.md section 7): one finding per truth issue, smallest evidence set."""
    findings = []
    for issue in truth["issues"]:
        ev = min(issue["acceptable_evidence_sets"], key=lambda s: (len(s), sorted(s)))
        findings.append(
            {
                "type": issue["type"],
                "affected_ids": list(issue["affected_ids"]),
                "claimed_amount_minor": issue["expected_amount_minor"],
                "currency": issue["currency"],
                "evidence_ids": list(ev),
                "explanation": "jury oracle",
            }
        )
    doc: dict[str, Any] = {"findings": findings}
    if episode_id is not None:
        doc["episode_id"] = episode_id
    return doc


def canonical_findings(doc: dict) -> list:
    return sorted(
        (
            f["type"],
            tuple(sorted(set(f["affected_ids"]))),
            f["claimed_amount_minor"],
            f["currency"],
            tuple(sorted(set(f["evidence_ids"]))),
        )
        for f in doc["findings"]
    )
