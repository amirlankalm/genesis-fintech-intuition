"""The evaluator-only oracle.

It reads truth, so it can only ever run inside the evaluator. It answers one
question: do truth, matching and reward agree at the ceiling? It says nothing
about whether an investigator can find the answer. The fetching variant measures
the other half: that every piece of required evidence is reachable through the
real tools within the step budget.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .env import AuditEnv
from .episodes import LoadedEpisode
from .errors import EpisodeError
from .store import TABLES, PublicEpisode


def oracle_findings(loaded: LoadedEpisode) -> list[dict[str, Any]]:
    """The truth as a submission, citing the smallest acceptable evidence set of each issue."""
    findings = []
    for issue in sorted(loaded.truth, key=lambda item: item.issue_id):
        evidence = min(issue.acceptable_evidence_sets, key=lambda ids: (len(ids), sorted(ids)))
        findings.append({
            "type": issue.type,
            "affected_ids": sorted(issue.affected_ids),
            "claimed_amount_minor": issue.expected_amount_minor,
            "currency": issue.currency,
            "evidence_ids": sorted(evidence),
            "explanation": "Evaluator-only oracle.",
        })  # fmt: skip
    return findings


def fetch_action(public: PublicEpisode, evidence_id: str) -> dict[str, Any]:
    """The single tool call that returns one evidence record."""
    for table in TABLES:
        for record in public.tables[table]:
            if public.evidence_id(table, record) == evidence_id:
                if table in ("invoices", "payments"):
                    return {"action": "get_document", "args": {"doc_id": evidence_id}}
                return {"action": "get_record", "args": {"table": table, "id": evidence_id}}
    raise EpisodeError("evidence id is not reachable through any tool")


def run_oracle(env: AuditEnv, *, seed: int | None, config: Mapping[str, Any], fetch_evidence: bool) -> dict[str, Any]:
    """Play one episode as the oracle and return the evaluator report."""
    env.reset(seed, config)
    loaded = env.evaluator_view()
    findings = oracle_findings(loaded)
    if fetch_evidence:
        for evidence_id in sorted({evidence_id for finding in findings for evidence_id in finding["evidence_ids"]}):
            observation, _, terminated, truncated, _ = env.step(fetch_action(loaded.public, evidence_id))
            if terminated or truncated or "record" not in observation:
                raise EpisodeError("required evidence could not be fetched within the step budget")
    document = {"episode_id": loaded.public.manifest["episode_id"], "findings": findings}
    env.step({"action": "submit", "args": {"findings": document}})
    return env.evaluator_report()
