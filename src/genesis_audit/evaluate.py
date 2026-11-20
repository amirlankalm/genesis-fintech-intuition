"""Measured evaluation of what exists: baselines, a result sheet, replay, paired checks, boundary probe.

Every number this module reports comes from a run it has just made. Nothing here
is a learning curve and nothing here trains a model.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from secrets import token_hex
from typing import Any

from . import ENV_VERSION, canon, families, paths, scoring, shipped, teaching
from .bridge import run_policy
from .env import AuditEnv
from .episodes import DirectorySource
from .errors import EpisodeError, LifecycleError
from .oracle import oracle_findings, run_oracle
from .sandbox import Confinement
from .tutor.group_math import flat_fraction

POLICY_DIR = paths.REPO_ROOT / "policies"
SCRIPTED: dict[str, tuple[str, tuple[str, ...]]] = {
    "always_abstain": ("always_abstain.py", ()),
    "never_acts": ("never_acts.py", ()),
    "random_inspector": ("random_inspector.py", ("7",)),
    "reconciliation_naive": ("reconciliation_naive.py", ()),
    "reconciliation": ("reconciliation.py", ()),
    "flag_all": ("flag_all.py", ()),
}
ORACLES: dict[str, bool] = {"oracle": False, "oracle_fetching": True}
SPLITS = ("teaching", "fixture", "train", "dev")
# Every shipped episode, in a fixed order, with its evaluator-side labels.
EPISODES: dict[str, dict[str, Any]] = {
    **{
        name: {
            "split": "teaching",
            "status": "faulty" if variant["injections"] else "clean",
            "families": [families.ALLOCATION] if variant["injections"] else [],
        }
        for name, variant in teaching.VARIANTS.items()
    },
    **{name: shipped.labels(name) for name in shipped.NAMES},
}
TEACHING = tuple(name for name, labels in EPISODES.items() if labels["split"] == "teaching")
GENERATED = tuple(name for name, labels in EPISODES.items() if labels["split"] in ("train", "dev"))
HAND_BUILT = ("teaching", "fixture")


def labels_of(name: str) -> dict[str, Any]:
    """Split, status and families of an episode: from the shipped catalogue, else from its private provenance."""
    if name in EPISODES:
        return EPISODES[name]
    try:
        provenance = json.loads((paths.PRIVATE_ROOT / name / "provenance.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        provenance = {}  # an episode with no readable provenance still appears, and fails the harness when loaded
    if not isinstance(provenance, dict):
        provenance = {}
    injections = provenance.get("injections", [])
    return {
        "split": provenance.get("split", "held_out"),
        "status": provenance.get("status", "faulty" if injections else "clean"),
        "families": provenance.get("families", sorted({injection["family"] for injection in injections})),
    }


def catalogue() -> dict[str, dict[str, Any]]:
    """Every episode under the episode root with its labels: shipped ones first, in their fixed order."""
    present = episode_names()
    ordered = [name for name in EPISODES if name in present] + [name for name in present if name not in EPISODES]
    return {name: labels_of(name) for name in ordered}


PROBE_NEEDLE_VARIABLE = "GENESIS_AUDIT_PROBE_NEEDLE"
# What a hostile policy must be unable to do under each backend. `search_private` looks for
# truth files around the policy's own directory, so it also catches a wrong mount.
PROBE_MUST_FAIL: dict[str, tuple[str, ...]] = {
    "seatbelt": ("read_truth", "stat_truth", "list_private", "search_private", "read_public_file", "read_source",
                 "write_file", "connect", "fork", "signal_evaluator", "read_evaluator_cmdline"),
    "setuid": ("read_truth", "stat_truth", "list_private", "search_private", "read_public_file", "read_source",
               "write_file", "signal_evaluator", "read_evaluator_cmdline", "read_evaluator_environ"),
    "docker": ("read_truth", "stat_truth", "list_private", "search_private", "read_public_file", "read_source",
               "write_file", "connect", "signal_evaluator", "read_evaluator_cmdline", "read_evaluator_environ"),
    "none": (),
}  # fmt: skip
# Measured, and not closable with the sandbox rules macOS offers: a same-user process can read the
# initial environment of any other. So nothing sensitive may be put in the evaluator's environment.
PROBE_KNOWN_GAPS: dict[str, tuple[str, ...]] = {"seatbelt": ("read_evaluator_environ",)}


@dataclass(frozen=True)
class RunRecord:
    policy: str
    episode: str
    seed: int | None
    config: dict[str, Any]
    report: dict[str, Any]
    trajectory: list[dict[str, Any]]
    process: dict[str, Any] | None  # None for the in-evaluator oracles


def new_env(secret: bytes | None = None) -> AuditEnv:
    """A fresh evaluator-side environment. Without a secret it uses the configured evaluator key."""
    key = secret if secret is not None else paths.evaluator_secret()
    return AuditEnv(DirectorySource(paths.PUBLIC_ROOT, paths.PRIVATE_ROOT), secret=key)


def run(policy: str, episode: str, *, confinement: Confinement, seed: int | None = None,
        extra_config: Mapping[str, Any] | None = None, secret: bytes | None = None) -> RunRecord:  # fmt: skip
    """Run one policy on one episode and keep everything the evaluator knows about it."""
    env = new_env(secret)
    config = {"episode": episode, **(extra_config or {})}
    if policy in ORACLES:
        report = run_oracle(env, seed=seed, config=config, fetch_evidence=ORACLES[policy])
        return RunRecord(policy, episode, seed, config, report, env.trajectory(), None)
    script, args = SCRIPTED[policy]
    result = run_policy(env, POLICY_DIR / script, args, seed=seed, config=config, confinement=confinement)
    return RunRecord(policy, episode, seed, config, result.report, result.trajectory, result.process)


def run_matrix(confinement: Confinement, names: Sequence[str] | None = None) -> list[RunRecord]:
    """Every policy on every episode under the episode root (or on `names`), in a fixed order."""
    episodes = list(catalogue()) if names is None else list(names)
    return [run(policy, episode, confinement=confinement) for policy in (*SCRIPTED, *ORACLES) for episode in episodes]


def sheet_row(record: RunRecord) -> dict[str, Any]:
    score = record.report["score"]
    return {
        "policy": record.policy,
        "episode": record.episode,
        "split": labels_of(record.episode)["split"],
        "status": labels_of(record.episode)["status"],
        "families": "+".join(labels_of(record.episode)["families"]) or "-",
        "tp": score.get("tp"),
        "fp": score.get("fp"),
        "fn": score.get("fn"),
        # shown only where defined; the draft scores an undefined precision or recall as 0
        "precision": score.get("precision") if (score.get("tp") or 0) + (score.get("fp") or 0) else None,
        "recall": score.get("recall") if (score.get("tp") or 0) + (score.get("fn") or 0) else None,
        "f1": score.get("f1"),
        "reward": score["reward"],
        "inspection_steps": record.report["inspection_steps"],
        "steps_used": record.report["steps_used"],
        "submitted": record.report["submitted"],
        "valid_submission": record.report["valid_submission"],
        "termination_cause": record.report["termination_cause"],
        "findings_submitted": len(record.report.get("findings", [])),
    }


def aggregates(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Per policy and split: mean episode F1 and pooled F1 answer different questions, so both are kept."""
    result = []
    groups = dict.fromkeys((row["policy"], row.get("split", "teaching")) for row in rows)
    for policy, split in sorted(groups, key=lambda group: (*SPLITS, group[1]).index(group[1])):
        mine = [row for row in rows if row["policy"] == policy and row.get("split", "teaching") == split]
        scored = [row for row in mine if row["f1"] is not None]
        tp, fp, fn = (sum(row[key] for row in scored) for key in ("tp", "fp", "fn"))
        clean = [row for row in mine if row["status"] == "clean"]
        result.append({
            "policy": policy,
            "split": split,
            "episodes": len(mine),
            "mean_episode_f1": sum(row["f1"] for row in scored) / len(scored) if scored else None,
            "pooled_f1": float(scoring.f1(tp, fp, fn)) if scored else None,
            "mean_reward": float(sum(Fraction(str(row["reward"])) for row in mine) / len(mine)),
            "clean_false_positive_rate": (
                sum(1 for row in clean if row["findings_submitted"] > 0) / len(clean) if clean else None
            ),
            "mean_inspection_steps": sum(row["inspection_steps"] for row in mine) / len(mine),
            "malformed_submissions": sum(1 for row in mine if row["submitted"] and not row["valid_submission"]),
            "no_submission": sum(1 for row in mine if not row["submitted"]),
        })  # fmt: skip
    return result


def family_rows(records: Sequence[RunRecord]) -> list[dict[str, Any]]:
    """Per policy and family over the generated episodes (not the hand-built ones): issues found, claims right."""
    counts: dict[tuple[str, str], dict[str, int]] = {}
    source = DirectorySource(paths.PUBLIC_ROOT, paths.PRIVATE_ROOT)
    kinds: dict[str, dict[str, str]] = {}
    for record in records:
        if labels_of(record.episode)["split"] in HAND_BUILT:
            continue
        if record.episode not in kinds:
            kinds[record.episode] = {issue.issue_id: issue.type for issue in source.load(record.episode).truth}
        truth = kinds[record.episode]
        verdicts = record.report.get("findings", [])
        action = record.trajectory[-1].get("action") or {}
        claimed = action.get("args", {}).get("findings", {}).get("findings", []) if verdicts else []
        matched = {verdict["matched_issue_id"] for verdict in verdicts} - {None}
        for family in families.FAMILIES:
            cell = counts.setdefault((record.policy, family), {"issues": 0, "found": 0, "claims": 0, "correct": 0})
            cell["issues"] += sum(1 for kind in truth.values() if kind == family)
            cell["found"] += sum(1 for issue_id in matched if truth[issue_id] == family)
            mine = [verdict for verdict, finding in zip(verdicts, claimed, strict=True) if finding["type"] == family]
            cell["claims"] += len(mine)
            cell["correct"] += sum(1 for verdict in mine if verdict["matched_issue_id"] is not None)
    return [
        {"policy": policy, "family": family, **cell,
         "recall": cell["found"] / cell["issues"] if cell["issues"] else None,
         "precision": cell["correct"] / cell["claims"] if cell["claims"] else None}
        for (policy, family), cell in counts.items()
    ]  # fmt: skip


def _cell(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def _table(columns: Sequence[str], rows: Sequence[Mapping[str, Any]]) -> list[str]:
    return [
        "| " + " | ".join(columns) + " |",
        "|" + "---|" * len(columns),
        *("| " + " | ".join(_cell(row[column]) for column in columns) + " |" for row in rows),
        "",
    ]


def render_results(rows: Sequence[Mapping[str, Any]], by_family: Sequence[Mapping[str, Any]] = ()) -> str:
    """The committed result sheet. Deterministic: no clock times, no machine names."""
    columns = ["policy", "episode", "split", "status", "families", "tp", "fp", "fn", "precision", "recall", "f1",
               "reward", "inspection_steps", "submitted", "termination_cause"]  # fmt: skip
    summary = ["policy", "split", "episodes", "mean_episode_f1", "pooled_f1", "mean_reward",
               "clean_false_positive_rate", "mean_inspection_steps", "malformed_submissions", "no_submission"]  # fmt: skip
    family_columns = ["policy", "family", "issues", "found", "recall", "claims", "correct", "precision"]
    lines = [
        "# Measured results",
        "",
        "Generated by `uv run python -m genesis_audit baselines --write-docs`. Every number below was measured by",
        f"that command on the {len({row['episode'] for row in rows})} episodes under the episode root. Environment",
        f"`{ENV_VERSION}`.",
        "",
        "Read this as a conformance run of an environment, not as evidence that any agent can audit. No model was",
        "trained or run: every policy is a script. Splits: `teaching` is four hand-built variants of one company",
        "(one family); `fixture` is seven hand-built variants of another (every family and two interactions);",
        "`train` and `dev` are ten generated companies each.",
        "",
        "- `oracle` and `oracle_fetching` read the truth. They are the reward ceiling and say nothing about agent",
        "  ability. `oracle` submits with no inspections; `oracle_fetching` first fetches every evidence record by id,",
        "  one call each, which shows that the evidence of every labelled issue is reachable within the step budget.",
        "- `always_abstain` and `never_acts` are the lazy references: right on clean books, wrong on faulty ones.",
        "- `reconciliation` reads no truth. It pages through every table and applies the four published rules.",
        "  Its reward is below 1 only by the inspection cost of reading the books.",
        "- `reconciliation_naive` applies the shortest rule that could work for each family and ignores the policy",
        "  text. It is kept as a shortcut probe: the valid look-alikes are what defeat it.",
        "- `flag_all` accuses candidates of every family up to the cap of 30 findings.",
        "- `random_inspector` makes a few random calls and guesses.",
        "",
        "## Per policy and split",
        "",
        *_table(summary, aggregates(rows)),
        "`mean_episode_f1` averages F1 over episodes; `pooled_f1` pools the counts first. `clean_false_positive_rate`",
        "is the share of clean episodes on which the policy claimed anything. A dash means undefined: precision",
        "with no findings, recall with no issues. F1 on clean books with no findings is 1 by the special case.",
        "",
        "## Per policy and family, over the generated episodes",
        "",
        *_table(family_columns, by_family),
        "`found` is true positives among the issues of that family; `claims` is findings submitted with that type and",
        "`correct` those that matched. The oracle rows are 1.0 by construction.",
        "",
        "## Per episode",
        "",
        *_table(columns, rows),
    ]
    return "\n".join(lines)


def splits_document() -> str:
    """episodes/splits.json: which shipped episode is in which split. Names are evaluator-side."""
    document = {split: [name for name, labels in EPISODES.items() if labels["split"] == split] for split in SPLITS}
    return json.dumps(document, indent=2) + "\n"


def trajectory_lines(records: Sequence[RunRecord]) -> list[str]:
    """trajectories.jsonl: one line per transition, exactly what each policy saw and did, tagged with its policy."""
    return [json.dumps({"policy": record.policy, **transition}, sort_keys=True)
            for record in records for transition in record.trajectory]  # fmt: skip


def digest_rows(records: Sequence[RunRecord]) -> list[dict[str, Any]]:
    """What another machine must reproduce exactly: one line per run, with the transition digest and exact reward."""
    return [
        {
            "policy": record.policy,
            "episode": record.episode,
            "trajectory_digest": record.report["trajectory_digest"],
            "reward_exact": record.report["score"]["reward_exact"],
            "steps_used": record.report["steps_used"],
        }
        for record in records
    ]


def replay(record: RunRecord, secret: bytes | None = None) -> dict[str, Any]:
    """Re-run a record's actions on a fresh environment and compare everything that was saved.

    Three things must agree: the digest of the saved trajectory itself, the digest the evaluator
    reported at the time, and the digest of the re-run. So an edited observation or reward in the
    saved log is caught, as well as an edited action or a forged score.
    """

    def stable(document: Mapping[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in document.items() if key != "nondeterministic"}

    try:
        env = new_env(secret)
        env.reset(record.seed, record.config)
        for transition in record.trajectory[1:]:
            if transition["event"] == "forced_truncation":
                env.truncate(record.report["termination_cause"])
            else:
                env.step(transition["action"])
        report = env.evaluator_report() if env.over else {"trajectory_digest": None, "score": None}
        digests = {canon.digest(record.trajectory), record.report["trajectory_digest"], report["trajectory_digest"]}
        # every field of the saved report must be what the re-run produces, not only the score
        match = len(digests) == 1 and stable(report) == stable(record.report)
    except (LifecycleError, EpisodeError, KeyError, TypeError, AttributeError, ValueError) as error:
        # A saved run that cannot even be re-run or compared (a missing field, a report that is not an object,
        # an impossible termination cause) is a mismatch with a name, never a crash.
        return {"policy": record.policy, "episode": record.episode, "match": False, "error": type(error).__name__}
    return {"policy": record.policy, "episode": record.episode, "match": match}


def load_records(directory: Path) -> list[RunRecord]:
    """Read back what `baselines` wrote: the public trajectories and the evaluator's reports."""
    reports = json.loads((directory / "evaluator" / "reports.json").read_text(encoding="utf-8"))
    by_run: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for line in (directory / "public" / "trajectories.jsonl").read_text(encoding="utf-8").splitlines():
        transition = json.loads(line)
        by_run.setdefault((transition.pop("policy"), transition["episode_id"]), []).append(transition)
    return [
        RunRecord(r["policy"], r["episode"], r["seed"], r["config"], r["report"],
                  by_run[(r["policy"], r["report"]["episode_id"])], r["process"])
        for r in reports
    ]  # fmt: skip


def episode_names() -> list[str]:
    """Every episode under the public root, not only the ones this module knows by name."""
    return sorted(entry.name for entry in paths.PUBLIC_ROOT.iterdir() if entry.is_dir())


def _economic_facts(env: AuditEnv) -> Counter:
    """Everything about the books that a harmless perturbation must preserve."""
    ledger = env.evaluator_view().public.tables["ledger"]
    return Counter((r["timestamp"], r["account"], r["debit_minor"], r["credit_minor"], r["currency"]) for r in ledger)


def paired_check(episode: str, seed: int, secret: bytes | None = None) -> dict[str, Any]:
    """Base episode versus its id-renamed, row-shuffled twin, as seen by the oracle."""
    perturbed_config = {"episode": episode, "perturb": {"rename_ids": True, "shuffle_rows": True}}
    base_env, twin_env = new_env(secret), new_env(secret)
    base = run_oracle(base_env, seed=None, config={"episode": episode}, fetch_evidence=True)
    twin = run_oracle(twin_env, seed=seed, config=perturbed_config, fetch_evidence=True)
    mapping = twin_env.evaluator_id_mapping()

    def canonical(findings: Iterable[Mapping[str, Any]], rename: Mapping[str, str]) -> list[tuple]:
        return sorted(
            (f["type"], tuple(sorted(rename.get(i, i) for i in f["affected_ids"])), f["claimed_amount_minor"],
             f["currency"], tuple(sorted(rename.get(i, i) for i in f["evidence_ids"])))
            for f in findings
        )  # fmt: skip

    base_view, twin_view = base_env.evaluator_view(), twin_env.evaluator_view()
    base_rows = [row["row_id"] for row in base_view.public.tables["ledger"]]
    twin_rows = [row["row_id"] for row in twin_view.public.tables["ledger"]]
    # Independent of the renaming code: derive truth again from the perturbed public records alone.
    rederived = sorted(
        (
            i["type"],
            tuple(i["affected_ids"]),
            i["expected_amount_minor"],
            i["currency"],
            tuple(i["acceptable_evidence_sets"][0]),
        )
        for i in families.detect(twin_view.public)
    )
    checks = {
        "truth_rederived_from_perturbed_records": rederived == canonical(oracle_findings(twin_view), {}),
        "findings_preserved_after_renaming": canonical(oracle_findings(base_view), mapping)
        == canonical(oracle_findings(twin_view), {}),
        "reward_equal": base["score"] == twin["score"],
        "economic_facts_equal": _economic_facts(base_env) == _economic_facts(twin_env),
        "every_id_renamed": bool(mapping) and all(old != new for old, new in mapping.items()),
        "row_order_changed": [mapping[row] for row in base_rows] != twin_rows,
        "episode_id_changed": base["episode_id"] != twin["episode_id"],
    }
    return {"episode": episode, "seed": seed, "ok": all(checks.values()), "checks": checks}


def perturbed_policy_check(policy: str, episode: str, seed: int, confinement: Confinement) -> dict[str, Any]:
    """A scripted (truth-blind) policy on the base episode and on its perturbed twin: counts and steps."""
    options = {"perturb": {"rename_ids": True, "shuffle_rows": True}}
    base = run(policy, episode, confinement=confinement).report
    twin = run(policy, episode, confinement=confinement, seed=seed, extra_config=options).report

    def summary(report: Mapping[str, Any]) -> tuple[Any, ...]:
        counts = report.get("counts", {})
        return counts.get("tp"), counts.get("fp"), counts.get("fn"), report["steps_used"]

    return {"policy": policy, "episode": episode, "seed": seed, "base": summary(base), "twin": summary(twin),
            "same": summary(base) == summary(twin)}  # fmt: skip


INVESTIGATOR = "reconciliation"
MEMORISER = POLICY_DIR / "hostile" / "memoriser.py"
UNSEEN_VARIANT = "teaching_b_p5"  # same company, an error whose amounts the memoriser never saw


def investigator_check(confinement: Confinement, seeds: Sequence[int] = tuple(range(1, 21)),
                       names: Sequence[str] | None = None) -> dict[str, Any]:  # fmt: skip
    """Is every episode solvable by a policy that reads no truth, and does a memoriser fail the control?

    The investigator must find every issue and claim nothing else (F1 = 1) on every episode and on its
    perturbed twins: all of `seeds` for the teaching episodes, the first for the others. Its reward is
    then 1 minus the cost of the calls it made, which grows with the size of the books. The memoriser,
    which only remembers two amounts, must do no better than abstaining on the variant it has not seen.
    Both run out of process under the given boundary.
    """
    options = {"perturb": {"rename_ids": True, "shuffle_rows": True}}
    worst, runs, missed = 1.0, 0, []
    episodes = list(catalogue()) if names is None else list(names)
    for episode in episodes:
        for seed in (None, *(seeds if episode in TEACHING else seeds[:1])):
            report = run(INVESTIGATOR, episode, confinement=confinement, seed=seed,
                         extra_config=options if seed is not None else None).report  # fmt: skip
            worst, runs = min(worst, report["score"]["reward"]), runs + 1
            cost = Fraction(2, 1000) * report["inspection_steps"]
            if report["score"].get("f1") != 1.0 or Fraction(report["score"]["reward_exact"]) != 1 - cost:
                missed.append((episode, seed))
    result: dict[str, Any] = {"runs": runs, "investigator_worst_reward": worst, "investigator_missed": missed,
                              "ok": not missed}  # fmt: skip
    if UNSEEN_VARIANT in episodes:  # the control needs the teaching company the memoriser was written for
        config = {"episode": UNSEEN_VARIANT}
        memoriser = run_policy(new_env(), MEMORISER, (), seed=None, config=config, confinement=confinement).report
        abstain = run("always_abstain", UNSEEN_VARIANT, confinement=confinement).report
        result["memoriser_on_unseen_variant"] = memoriser["score"]["reward"]
        result["abstain_on_unseen_variant"] = abstain["score"]["reward"]
        result["ok"] = result["ok"] and memoriser["score"]["reward"] <= abstain["score"]["reward"]
    return result


def random_sweep(seeds: Sequence[int], confinement: Confinement, group_size: int = 4,
                 episodes: Sequence[str] = TEACHING) -> dict[str, Any]:  # fmt: skip
    """The random inspector over many of its own seeds: reward spread and the share of flat groups.

    A flat group (every rollout the same reward) gives a group-relative trainer no reward advantage.
    This measures how often that would happen here; it trains nothing.
    """
    script = POLICY_DIR / SCRIPTED["random_inspector"][0]
    result: dict[str, Any] = {"seeds": [seeds[0], seeds[-1]], "group_size": group_size, "episodes": {}}
    for episode in episodes:
        rewards, claimed = [], 0
        for seed in seeds:
            done = run_policy(
                new_env(), script, (str(seed),), seed=None, config={"episode": episode}, confinement=confinement
            )
            rewards.append(done.report["score"]["reward"])
            claimed += bool(done.report.get("findings"))
        groups = [rewards[i : i + group_size] for i in range(0, len(rewards) - group_size + 1, group_size)]
        result["episodes"][episode] = {
            "rollouts": len(rewards),
            "reward_histogram": {f"{value:.3f}": count for value, count in sorted(Counter(rewards).items())},
            "share_of_rollouts_with_any_finding": claimed / len(rewards),
            "groups": len(groups),
            "flat_fraction": flat_fraction(groups),
        }
    return result


def scale_measurements(confinement: Confinement) -> dict[str, Any]:
    """Reading cost, time and memory on every episode under the root, and building the largest one.

    Step counts are properties of the episodes and reproduce exactly. Seconds and bytes are
    measurements of this machine: they are reported, and compared with the draft's envelope
    (60 seconds per episode, 4 GB), never with a stored number.
    """
    import platform
    import resource
    import time
    import tracemalloc

    source = DirectorySource(paths.PUBLIC_ROOT, paths.PRIVATE_ROOT)
    episodes: dict[str, Any] = {}
    for name in catalogue():
        started = time.perf_counter()
        loaded = source.load(name)
        load_seconds = time.perf_counter() - started
        public = loaded.public
        page = public.page_limit()
        solver = run(INVESTIGATOR, name, confinement=confinement)
        fetcher = run("oracle_fetching", name, confinement=confinement)
        episodes[name] = {
            **public.manifest["counts"],
            "issues": len(loaded.truth),
            "pages": {table: max(1, -(-len(rows) // page)) for table, rows in public.tables.items()},
            "steps_to_read_everything": families.scan_steps(public),
            "solver_steps": solver.report["steps_used"],
            "solver_f1": solver.report["score"].get("f1"),
            "solver_reward": solver.report["score"]["reward"],
            "evidence_fetches_for_every_issue": fetcher.report["inspection_steps"],
            "every_issue_reachable_within_budget": fetcher.report["score"].get("f1") == 1.0,
            "load_and_validate_seconds": round(load_seconds, 4),
            "solver_episode_seconds": round(solver.report["nondeterministic"]["elapsed_s"], 4),
        }
    largest = max(episodes, key=lambda name: episodes[name]["ledger_rows"])
    build: dict[str, Any] = {}
    if largest in shipped.GENERATED:
        company, inject = shipped.GENERATED[largest]
        tracemalloc.start()
        started = time.perf_counter()
        shipped.generate(company["seed"], company["config"], inject, secret=paths.evaluator_secret(), variant=largest)
        build = {
            "seconds": round(time.perf_counter() - started, 4),
            "peak_python_bytes": tracemalloc.get_traced_memory()[1],
        }
        tracemalloc.stop()
    scale = 1 if sys.platform == "darwin" else 1024  # ru_maxrss is bytes on macOS and kilobytes on Linux
    usage = {who: resource.getrusage(which).ru_maxrss * scale
             for who, which in (("evaluator", resource.RUSAGE_SELF), ("largest_policy_process", resource.RUSAGE_CHILDREN))}  # fmt: skip
    slowest = max(entry["solver_episode_seconds"] for entry in episodes.values())
    return {
        "host": f"{platform.system()} {platform.machine()}, Python {platform.python_version()}",
        "backend": confinement.backend,
        "envelope": {"seconds_per_episode": 60, "memory_bytes": 4 * 2**30, "max_steps": 100},
        "largest_episode": largest,
        "build_largest_from_seed": build,
        "peak_resident_bytes": usage,
        "slowest_solver_episode_seconds": slowest,
        "most_steps_to_read_everything": max(entry["steps_to_read_everything"] for entry in episodes.values()),
        "within_envelope": slowest < 60
        and max(usage.values()) < 4 * 2**30
        and all(
            entry["every_issue_reachable_within_budget"] and entry["solver_f1"] == 1.0 for entry in episodes.values()
        ),
        "episodes": episodes,
    }


CLOCK_AND_MEMORY = ("host", "backend", "build_largest_from_seed", "peak_resident_bytes", "slowest_solver_episode_seconds",
                    "load_and_validate_seconds", "solver_episode_seconds")  # fmt: skip


def scale_facts(document: Any) -> Any:
    """A scale report without its clock and memory readings: what must be the same on every machine."""
    if isinstance(document, dict):
        return {key: scale_facts(value) for key, value in document.items() if key not in CLOCK_AND_MEMORY}
    return document


def sweep_agrees(document: Any, confinement: Confinement, seeds: int = 12) -> bool:
    """Is a stored random-inspector sweep consistent with a fresh run of its first seeds on each episode?"""
    try:
        first, last = document["seeds"]
        episodes = document["episodes"]
        if first != 0 or set(episodes) != set(TEACHING) or any(e["rollouts"] != last + 1 for e in episodes.values()):
            return False
        fresh = random_sweep(range(seeds), confinement, group_size=document["group_size"])["episodes"]
        return all(
            sum(episodes[name]["reward_histogram"].values()) == last + 1
            and all(count <= episodes[name]["reward_histogram"].get(reward, 0)
                    for reward, count in fresh[name]["reward_histogram"].items())
            for name in episodes
        )  # fmt: skip
    except (KeyError, TypeError, ValueError, AttributeError, EpisodeError):
        return False  # a file of another shape, or a root without the teaching episodes


def probe_in_process(
    confinement: Confinement, needle_argument: str = "", needle_environment: str = ""
) -> dict[str, Any]:
    """Launch the hostile probe from this process. `held` is true when everything that must fail did fail."""
    names = episode_names()
    if not names:  # nothing to aim at: a probe that looks for files that are not there proves nothing
        return {"backend": confinement.backend, "held": False, "error": "no episode under the episode root to probe"}
    truth = paths.PRIVATE_ROOT / names[0] / "truth.json"
    public = paths.PUBLIC_ROOT / names[0] / "ledger.csv"
    source = paths.REPO_ROOT / "src" / "genesis_audit" / "teaching.py"
    absent = [str(path) for path in (truth, public, source) if not path.is_file()]
    if absent:
        return {"backend": confinement.backend, "held": False, "error": f"probe targets do not exist: {absent}"}
    with socket.socket() as server, tempfile.TemporaryDirectory() as scratch:
        server.bind(("127.0.0.1", 0))
        server.listen(4)
        target = Path(scratch) / "probe.txt"
        args = [str(truth), str(public), str(target), str(server.getsockname()[1]), str(os.getpid()), str(source),
                needle_argument, needle_environment]  # fmt: skip
        argv, popen_kwargs = confinement.launch(POLICY_DIR / "boundary_probe.py", args)
        done = subprocess.run(argv, capture_output=True, text=True, timeout=120, check=False, **popen_kwargs)
        wrote = target.exists()
    try:
        attempts = json.loads(done.stdout)
    except ValueError:
        return {"backend": confinement.backend, "held": False, "error": done.stderr.strip()[:300]}
    must_fail = PROBE_MUST_FAIL[confinement.backend]
    return {
        "backend": confinement.backend,
        # With no boundary nothing is required to fail, and nothing is protected: that never counts as holding.
        "held": bool(must_fail)
        and all(attempts[name].startswith("denied") for name in must_fail)
        and not (wrote and "write_file" in must_fail),
        "attempts": attempts,
        "must_fail": list(must_fail),
        "known_gaps": [name for name in PROBE_KNOWN_GAPS.get(confinement.backend, ()) if attempts[name] == "ok"],
    }


def probe_boundary(confinement: Confinement) -> dict[str, Any]:
    """Run the hostile probe from a fresh evaluator process started through the CLI.

    A fresh process is what makes two of the attempts meaningful: its command line and its
    environment each carry a random needle, and the probe must not be able to find them. The
    child uses the CLI's own boundary configuration for the named backend.
    """
    needle_argument, needle_environment = (f"needle-{kind}-{token_hex(8)}" for kind in ("arg", "env"))
    argv = [
        sys.executable,
        "-m",
        "genesis_audit",
        "probe-child",
        "--confine",
        confinement.backend,
        "--needle",
        needle_argument,
    ]
    environment = {**os.environ, PROBE_NEEDLE_VARIABLE: needle_environment}
    done = subprocess.run(argv, capture_output=True, text=True, env=environment, timeout=180, check=False)
    try:
        return json.loads(done.stdout)
    except ValueError:
        return {"backend": confinement.backend, "held": False, "error": (done.stderr or done.stdout).strip()[-300:]}


def leaked_tokens(records: Sequence[RunRecord]) -> list[str]:
    """Private strings found in anything a policy saw. Must be empty."""
    private = {str(paths.PRIVATE_ROOT), "truth.json", "provenance", "canary-"}
    for name in dict.fromkeys(record.episode for record in records):
        document = json.loads((paths.PRIVATE_ROOT / name / "truth.json").read_text(encoding="utf-8"))
        private.update(issue["issue_id"] for issue in document["issues"])
        provenance = json.loads((paths.PRIVATE_ROOT / name / "provenance.json").read_text(encoding="utf-8"))
        private.update(value for value in (provenance.get("canary"),) if value)
    found: set[str] = set()
    for record in records:
        visible = json.dumps([{k: t[k] for k in ("observation", "reward", "info")} for t in record.trajectory])
        found.update(token for token in private if token in visible)
    return sorted(found)
