"""One evidence universe (official rule 3 and M03) and the allocation evidence of a cross-currency receipt
(Block 2, condition 4), as decided on 20 Nov 2026 and published as policy case-draft-2.

Rule 3: "Дополнительные существующие доступные доказательства допустимы"; an id that does not exist or is not
accessible makes the finding unmatched (FP). Accessible = every id a tool returns a record or document for: a
ledger row_id, a document doc_id, an invoice_id or payment_id (get_record takes them) and an fx key. The
environment, judge_adapter.score_episode and truth.validate_truth must draw the line in the same place.
"""

from __future__ import annotations

import dataclasses
import shutil
from typing import Any

import pytest

import judge_adapter
from genesis_audit import families, paths, shipped
from genesis_audit.env import AuditEnv
from genesis_audit.episodes import LoadedEpisode
from genesis_audit.errors import EpisodeError
from genesis_audit.oracle import oracle_findings
from genesis_audit.store import PublicEpisode
from genesis_audit.truth import TruthIssue, validate_truth

NAME = "fixture_x_fx_allocation"  # P31 (USD) under-applied to I08 (KZT), and P31 translated at the wrong rate
INVENTED = "L-NO-SUCH-ROW"


@pytest.fixture(scope="module")
def flat(tmp_path_factory: pytest.TempPathFactory) -> str:
    """The shipped episode as the jury holds it: one flat directory with the public files and truth.json."""
    directory = tmp_path_factory.mktemp("universe") / NAME
    directory.mkdir()
    for root in (paths.PUBLIC_ROOT, paths.PRIVATE_ROOT):
        for entry in (root / NAME).iterdir():
            shutil.copy(entry, directory / entry.name)
    return str(directory)


@pytest.fixture(scope="module")
def loaded() -> LoadedEpisode:
    from genesis_audit.env import DirectorySource

    return DirectorySource(paths.PUBLIC_ROOT, paths.PRIVATE_ROOT).load(NAME)


def candidates(public: PublicEpisode) -> dict[str, str]:
    """One id of every kind a finding might cite, keyed by kind."""
    tables = public.tables
    ledger, invoice, payment, rate = tables["ledger"][0], tables["invoices"][0], tables["payments"][0], tables["fx"][0]
    return {
        "row_id": ledger["row_id"],
        "doc_id": invoice["doc_id"],
        "invoice_id": invoice["invoice_id"],
        "payment_id": payment["payment_id"],
        "fx_key": public.record_id("fx", rate),
        "entity_id": invoice["entity_id"],
        "issue_id": "truth-000000000000",
        "invented": INVENTED,
    }


ACCESSIBLE = {"row_id", "doc_id", "invoice_id", "payment_id", "fx_key"}


def with_extra(document: list[dict[str, Any]], extra: str) -> list[dict[str, Any]]:
    """Every finding of the oracle, each citing one more id."""
    return [{**finding, "evidence_ids": [*finding["evidence_ids"], extra]} for finding in document]


def env_counts(findings: list[dict[str, Any]], episode_id: str) -> dict[str, int]:
    from genesis_audit.env import DirectorySource

    env = AuditEnv(DirectorySource(paths.PUBLIC_ROOT, paths.PRIVATE_ROOT))
    env.reset(config={"episode": NAME, "mode": "eval"})
    env.step({"action": "submit", "args": {"findings": {"episode_id": episode_id, "findings": findings}}})
    return env.evaluator_report()["counts"]


def adapter_counts(flat: str, findings: list[dict[str, Any]], episode_id: str) -> dict[str, int]:
    score = judge_adapter.score_episode(flat, {"episode_id": episode_id, "findings": findings}, 0)
    return {key: score[key] for key in ("tp", "fp", "fn")}


def truth_accepts(loaded: LoadedEpisode, extra: str) -> bool:
    """Whether validate_truth takes the truth with every acceptable set also requiring `extra`."""
    widened = tuple(
        dataclasses.replace(issue, acceptable_evidence_sets=tuple(s | {extra} for s in issue.acceptable_evidence_sets))
        for issue in loaded.truth
    )
    try:
        validate_truth(widened, loaded.public)
    except EpisodeError:
        return False
    return True


# ------------------------------------------------------------------------------------------- rule 3, M03


@pytest.mark.parametrize("kind", ["invoice_id", "payment_id"])
def test_m03_an_invoice_or_payment_id_cited_as_extra_evidence_keeps_the_tp(
    kind: str, flat: str, loaded: LoadedEpisode
) -> None:
    """M03 on a case episode: get_record returns these ids, so they are existing, accessible extra evidence."""
    episode_id = loaded.public.manifest["episode_id"]
    extra = {"invoice_id": "I08", "payment_id": "P31"}[kind]  # the very ids the findings are about
    assert extra in loaded.public.accessible_ids() and extra not in loaded.public.evidence_universe()
    findings = with_extra(oracle_findings(loaded), extra)
    perfect = {"tp": len(loaded.truth), "fp": 0, "fn": 0}
    assert env_counts(findings, episode_id) == adapter_counts(flat, findings, episode_id) == perfect


@pytest.mark.parametrize("kind", ["entity_id", "issue_id", "invented"])
def test_rule_3_an_id_no_tool_returns_still_voids_the_finding(kind: str, flat: str, loaded: LoadedEpisode) -> None:
    """An unknown or inaccessible evidence id makes the finding unmatched (FP + FN), not a structural error."""
    episode_id = loaded.public.manifest["episode_id"]
    extra = candidates(loaded.public)[kind]
    assert extra not in loaded.public.accessible_ids()
    findings = with_extra(oracle_findings(loaded), extra)
    count = len(loaded.truth)
    score = judge_adapter.score_episode(flat, {"episode_id": episode_id, "findings": findings}, 0)
    assert score["return"] == -1.0  # F1 = 0: matched, not refused (a refusal would give null counts)
    assert env_counts(findings, episode_id) == adapter_counts(flat, findings, episode_id)
    assert adapter_counts(flat, findings, episode_id) == {"tp": 0, "fp": count, "fn": count}


def test_rule_3_env_score_episode_and_validate_truth_draw_the_same_line(flat: str, loaded: LoadedEpisode) -> None:
    """For every kind of id: the env keeps the TP, score_episode keeps the TP and validate_truth accepts the id in
    an acceptable set, all three or none. The line is PublicEpisode.accessible_ids()."""
    episode_id, accessible = loaded.public.manifest["episode_id"], loaded.public.accessible_ids()
    perfect = {"tp": len(loaded.truth), "fp": 0, "fn": 0}
    verdicts = {}
    for kind, extra in candidates(loaded.public).items():
        findings = with_extra(oracle_findings(loaded), extra)
        env_tp = env_counts(findings, episode_id) == perfect
        adapter_tp = adapter_counts(flat, findings, episode_id) == perfect
        verdicts[kind] = (env_tp, adapter_tp, truth_accepts(loaded, extra), extra in accessible)
    assert verdicts == {kind: (kind in ACCESSIBLE,) * 4 for kind in verdicts}


def test_rule_3_accessible_ids_are_exactly_what_the_tools_return(loaded: LoadedEpisode) -> None:
    """Every accessible id is fetched by get_record or get_document; nothing else is in the universe."""
    public = loaded.public
    fetched = set()
    for table in ("ledger", "invoices", "payments", "fx"):
        for record in public.tables[table]:
            record_id = public.record_id(table, record)
            assert public.get_record(table, record_id)[1] == dict(record)
            fetched.add(record_id)
            if table in ("invoices", "payments"):
                assert public.get_document(record["doc_id"])[1] == dict(record)
                fetched.add(record["doc_id"])
    assert public.accessible_ids() == fetched


# ------------------------------------------------------------------------------- Block 2, condition 4


def allocation_issues(public: PublicEpisode, truth: tuple[TruthIssue, ...]) -> list[tuple[TruthIssue, bool, str]]:
    """(issue, the receipt is in another currency than the invoice, the receipt's fx_clearing debit row_id or '')."""
    invoices = {i["invoice_id"]: i for i in public.tables["invoices"]}
    payments = {p["payment_id"]: p for p in public.tables["payments"]}
    names = families.account_names(public.policy)
    found = []
    for issue in truth:
        if issue.type != families.ALLOCATION:
            continue
        (invoice_id,) = issue.affected_ids & set(invoices)
        (payment_id,) = issue.affected_ids & set(payments)
        debits = [r["row_id"] for r in public.tables["ledger"] if r["payment_id"] == payment_id
                  and r["account"] == names["fx_clearing"] and r["debit_minor"] > 0]  # fmt: skip
        foreign = payments[payment_id]["currency"] != invoices[invoice_id]["currency"]
        assert len(debits) == (1 if foreign else 0)
        found.append((issue, foreign, debits[0] if debits else ""))
    return found


def test_d16_condition_4_a_cross_currency_allocation_set_holds_the_fx_clearing_debit_and_same_currency_not() -> None:
    """D16 (the case's example: a partial payment in another currency) and D17 (same currency), three seeds each:
    the acceptable set holds the receipt's recorded translation exactly when the currencies differ."""
    from test_generator_scenarios import SEEDS, config_for

    seen = {True: 0, False: 0}
    for check in ("D16", "D17"):
        for seed in SEEDS:
            public, truth, _ = shipped.generate(seed, *shipped.parse_config(config_for(check, seed)))
            for issue, foreign, debit in allocation_issues(public, truth):
                (evidence,) = issue.acceptable_evidence_sets
                rows = {r["row_id"]: r for r in public.tables["ledger"]}
                clearing = {i for i in evidence if i in rows and rows[i]["account"] == "fx_clearing"}
                assert clearing == ({debit} if foreign else set())
                assert foreign == (check == "D16")
                seen[foreign] += 1
    assert seen == {True: 3, False: 3}


@pytest.mark.parametrize("name", shipped.NAMES)
def test_condition_4_every_shipped_allocation_set_follows_case_draft_2(name: str, source: Any) -> None:
    """Every shipped case episode is published under case-draft-2, and every allocation set cites the receipt's
    fx_clearing debit exactly when the receipt is in another currency than the invoice."""
    loaded = source.load(name)
    assert loaded.public.policy["policy_version"] == families.POLICY["policy_version"] == "case-draft-2"
    for issue, foreign, debit in allocation_issues(loaded.public, loaded.truth):
        (evidence,) = issue.acceptable_evidence_sets
        assert (debit in evidence) == foreign and (not foreign or debit)


def test_condition_4_the_old_policy_version_is_no_longer_published() -> None:
    """The rule text changed, so the version changed: case-draft-1 is refused, teaching-1 is unchanged."""
    assert set(families.CONTRACTS) == {"teaching-1", "case-draft-2"}
    convention = families.POLICY["finding_conventions"][families.ALLOCATION]["evidence_ids"]
    assert "fx_clearing debit" in convention and "invoice_id, a payment_id" in convention
    teaching = families.TEACHING_POLICY["finding_conventions"][families.ALLOCATION]["evidence_ids"]
    assert teaching.endswith("Further record ids may be added.")  # teaching-1 keeps its published text


def test_condition_4_the_reconciliation_policy_cites_what_the_convention_asks(flat: str) -> None:
    """policies/reconciliation.py through make_env (closed mode) on the interaction episode: the cross-currency
    allocation (P31 in USD, I08 in KZT) and the fx error are both TP, so its allocation evidence holds the
    receipt's fx_clearing debit; without that row the allocation finding would be an FP."""
    from baselines import reconciliation

    env = judge_adapter.make_env()
    observation, _ = env.reset(None, {"mode": "closed", "episode_dir": flat, "team_config": {}})
    reconciliation.run(env, observation)
    report = env.evaluator_report()
    assert report["termination_cause"] == "submitted"
    assert report["counts"] == {"tp": 2, "fp": 0, "fn": 0}


@pytest.mark.parametrize("name", ["train_07", "train_10"])
def test_condition_4_the_flag_all_attack_cites_the_convention_shape_across_currencies(name: str, tmp_path: Any) -> None:
    """policies/flag_all.py promises "the right shape of finding" for every family. On train_07 and train_10 its
    blind allocation accusation of the cross-currency receipt happens to carry the right amount, so it must stay a
    TP under case-draft-2: the accusation cites the receipt's fx_clearing debit. A stale shape would understate
    how strong the mass-flagging attack is (review of 20 Nov 2026)."""
    from baselines import flag_all

    directory = tmp_path / name
    directory.mkdir()
    for root in (paths.PUBLIC_ROOT, paths.PRIVATE_ROOT):
        for entry in (root / name).iterdir():
            shutil.copy(entry, directory / entry.name)
    loaded = judge_adapter._load(str(directory))
    (allocation,) = [issue for issue in loaded.truth if issue.type == families.ALLOCATION]
    env = judge_adapter.make_env()
    observation, _ = env.reset(None, {"mode": "closed", "episode_dir": str(directory)})
    flag_all.run(env, observation)
    report = env.evaluator_report()
    assert report["termination_cause"] == "submitted"
    assert allocation.issue_id not in report["unmatched_issue_ids"]
    assert report["counts"]["tp"] >= 1
