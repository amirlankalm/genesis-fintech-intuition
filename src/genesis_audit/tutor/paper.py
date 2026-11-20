"""Prompt B: the public sheet of the paper-solvable episode. It never contains the answer key."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from ..money import format_minor
from ..store import FX_COLUMNS, LEDGER_COLUMNS, PublicEpisode


def _table(columns: Sequence[str], rows: Sequence[Mapping[str, Any]]) -> list[str]:
    lines = ["| " + " | ".join(columns) + " |", "|" + "---|" * len(columns)]
    for row in rows:
        lines.append("| " + " | ".join("" if row[c] is None else str(row[c]) for c in columns) + " |")
    return [*lines, ""]


def render_paper_episode(episode: PublicEpisode, name: str) -> str:
    manifest, policy = episode.manifest, episode.policy
    base = manifest["base_currency"]
    exponent = manifest["currencies"][base]["exponent"]
    convention = policy["finding_conventions"]
    skeleton = {
        "episode_id": manifest["episode_id"],
        "findings": [
            {
                "type": "<one of manifest.issue_types>",
                "affected_ids": ["<id>", "<id>"],
                "claimed_amount_minor": 0,
                "currency": base,
                "evidence_ids": ["<doc_id or row_id>"],
                "explanation": "<short supporting text>",
            }
        ],
    }
    out = [
        "# Prompt B - one episode you can solve on paper",
        "",
        "A teaching-only synthetic company. Every name, id and amount is invented. This page holds the public",
        "records only. The answer key is private and is used only when you submit.",
        "",
        "## Declared policies",
        "",
        "- **Currencies and exponents:** "
        + ", ".join(f"{code} = {spec['exponent']}" for code, spec in manifest["currencies"].items())
        + f". Base currency {base}; {format_minor(10**exponent, exponent, base)} is {10**exponent} minor units.",
        f"- **Timezone:** {manifest['timezone']}. Every timestamp carries its offset.",
        f"- **Period:** {manifest['period_start']} to {manifest['period_end']}.",
        f"- **FX date:** `{policy['fx']['date_policy']}`. {policy['fx']['note']}",
        f"- **Cutoff:** `{policy['cutoff']['policy']}`. {policy['cutoff']['note']}",
        f"- **Rounding:** `{manifest['rounding']['default']}`.",
        f"- **Allocation:** `{policy['allocation']['policy']}`. {policy['allocation']['note']}",
        f"- **Amount tolerance:** {manifest['amount_tolerance_minor'][base]} minor units, so amounts must be exact.",
        f"- **Issue types that may occur:** {', '.join(manifest['issue_types'])}. The books may also be clean.",
        "",
        "## Public records",
        "",
        "### ledger.csv",
        "",
        *_table(LEDGER_COLUMNS, episode.tables["ledger"]),
        "### invoices.jsonl",
        "",
        "```json",
        *[json.dumps(record) for record in episode.tables["invoices"]],
        "```",
        "",
        "### payments.jsonl",
        "",
        "```json",
        *[json.dumps(record) for record in episode.tables["payments"]],
        "```",
        "",
        "### fx.csv",
        "",
        *_table(FX_COLUMNS, episode.tables["fx"]),
        "## What a finding must contain",
        "",
    ]
    for kind, rules in convention.items():
        out += [f"For `{kind}`: {rules['meaning']}", ""]
        out += [f"- `{field}`: {rules[field]}" for field in ("affected_ids", "claimed_amount_minor", "evidence_ids")]
        out.append("")
    out += [
        "A finding counts only if the type, the affected ids, the amount, the currency and the complete evidence",
        "are all right. A correct amount with missing evidence is a false claim, not a near miss.",
        "",
        "## Solve it",
        "",
        "On paper: decide which findings, if any, the records support, and write them in this shape.",
        "Submit an empty `findings` list if you believe the books are clean.",
        "",
        "```json",
        json.dumps(skeleton, indent=2),
        "```",
        "",
        "Through the tools, requesting records yourself and being checked only when you submit:",
        "",
        "```",
        f"uv run python -m genesis_audit play --episode {name}",
        "```",
        "",
        "If you believe a decisive fact is missing from the public records, say which one. A fixture that",
        "cannot be decided from its public records is broken and gets repaired; a guess is not rewarded.",
        "",
    ]
    return "\n".join(out)
