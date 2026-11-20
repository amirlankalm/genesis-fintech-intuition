"""Block 2 of the official checks: the twenty closed episodes D01-D20, each built through the documented config.

For every scenario class the jury's request (`SCENARIOS`, the table the README publishes) is generated for three
seeds and three companies, and each episode is held to the per-episode conditions 1-6 of the official text:
the clean state behind the provenance has no issue, the injection is the requested one (type, count and the
sub-kind the books show), truth agrees with tools/independent_checker.py, an acceptable evidence set exists, cites
only public ids and is enough to recompute the amount, and the formats of section 03 hold.
"""

from __future__ import annotations

import functools
import json
import re
import subprocess
import sys
from collections import Counter
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest

from genesis_audit import books, families, paths, shipped, world
from genesis_audit.errors import EpisodeError
from genesis_audit.families import when
from genesis_audit.store import PublicEpisode, fx_key
from genesis_audit.truth import TruthIssue

X1, X2 = world.INTERACTION_1, world.INTERACTION_2
SEEDS = (1001, 1002, 1003)
# Hidden values the jury might choose: other currencies, zones, periods and sizes for each seed.
COMPANIES: tuple[dict[str, Any], ...] = (
    {"base_currency": "KZT", "foreign_currencies": ["USD"], "timezone": "Asia/Almaty", "period": "2026-10",
     "invoices": 30, "ledger_rows": 320},
    {"base_currency": "EUR", "foreign_currencies": ["GBP", "JPY"], "timezone": "America/Bogota", "period": "2027-Q2",
     "invoices": 60, "ledger_rows": 700},
    {"base_currency": "USD", "foreign_currencies": ["KWD"], "timezone": "Asia/Kolkata", "period": "2025-03",
     "invoices": 24, "ledger_rows": 240},
)  # fmt: skip
CLEAN = {"inject": {}}
# Check id -> the config passed to generate_episode(seed, config, output_dir). Company settings go under
# "generator"; the jury adds its own hidden ones there.
SCENARIOS: dict[str, dict[str, Any]] = {
    "D01": CLEAN, "D02": CLEAN, "D03": CLEAN, "D04": CLEAN, "D05": CLEAN,
    "D06": {"inject": {"duplicate_invoice": 1}},
    "D07": {"inject": {"duplicate_invoice": 1}},
    "D08": {"inject": {"duplicate_invoice": 1}},
    "D09": {"inject": {"payment_allocation_missing": 1}},
    "D10": {"inject": {"payment_allocation_partial": 1}},
    "D11": {"inject": {"payment_allocation_missing": 1}},
    "D12": {"inject": {"fx_mismatch_date": 1}},
    "D13": {"inject": {"fx_mismatch_rate": 1}},
    "D14": {"inject": {"cutoff": 1}},
    "D15": {"inject": {"cutoff": 1}},
    "D16": {"inject": {"interactions": [{"name": X1, "allocation": "partial", "receipt_currency": "foreign"}]}},
    "D17": {"inject": {"interactions": [{"name": X1, "boundary": "start", "allocation": "missing",
                                         "receipt_currency": "same"}]}},
    "D18": {"generator": {"tail_days": 12},
            "inject": {"interactions": [{"name": X1, "boundary": "end", "allocation": "partial"}]}},
    "D19": {"inject": {"interactions": [{"name": X2, "boundary": "end", "copy_offset": "other"}]}},
    "D20": {"inject": {"interactions": [{"name": X2, "boundary": "start", "copy_offset": "same"}]}},
}  # fmt: skip
TYPES: dict[str, dict[str, int]] = {
    **{check: {} for check in ("D01", "D02", "D03", "D04", "D05")},
    **{check: {"duplicate_invoice": 1} for check in ("D06", "D07", "D08")},
    **{check: {"payment_allocation": 1} for check in ("D09", "D10", "D11")},
    **{check: {"fx_mismatch": 1} for check in ("D12", "D13")},
    **{check: {"cutoff": 1} for check in ("D14", "D15")},
    **{check: {"cutoff": 1, "payment_allocation": 1} for check in ("D16", "D17", "D18")},
    **{check: {"duplicate_invoice": 1, "cutoff": 1} for check in ("D19", "D20")},
}
# What the books must show for the parameters each request names.
SUBKINDS: dict[str, dict[str, str]] = {
    "D09": {"allocation": "missing"},
    "D10": {"allocation": "partial"},
    "D11": {"allocation": "missing"},
    "D12": {"fx_error": "date"},
    "D13": {"fx_error": "rate"},
    "D16": {"allocation": "partial", "receipt_currency": "foreign"},
    "D17": {"boundary": "start", "allocation": "missing", "receipt_currency": "same"},
    "D18": {"boundary": "end", "allocation": "partial"},
    "D19": {"boundary": "end", "copy_offset": "other"},
    "D20": {"boundary": "start", "copy_offset": "same"},
}
TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}$")
RATE = re.compile(r"^\d+\.\d+$")
DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
PUBLIC_FILES = ("manifest.json", "policy.json", "ledger.csv", "invoices.jsonl", "payments.jsonl", "fx.csv")
PRIVATE_FILES = ("truth.json", "provenance.json")


def config_for(check: str, seed: int) -> dict[str, Any]:
    recipe = SCENARIOS[check]
    company = COMPANIES[SEEDS.index(seed)]
    return {"generator": {**company, **recipe.get("generator", {})}, "inject": recipe["inject"]}


@functools.cache
def episode(check: str, seed: int) -> tuple[PublicEpisode, tuple[TruthIssue, ...], dict[str, Any]]:
    settings, inject = shipped.parse_config(config_for(check, seed))
    return shipped.generate(seed, settings, inject, variant=check.lower())


@pytest.fixture(scope="module")
def written(tmp_path_factory: pytest.TempPathFactory) -> Any:
    """Writes one episode's eight files flat, as generate_episode does, and returns the directory."""
    root = tmp_path_factory.mktemp("scenarios")

    @functools.cache
    def write(check: str, seed: int) -> Path:
        directory = root / f"{check}-{seed}"
        directory.mkdir()
        files = shipped.generate_files(seed, config_for(check, seed), variant=check.lower())
        assert sorted(files) == sorted(PUBLIC_FILES + PRIVATE_FILES)
        for filename, text in files.items():
            (directory / filename).write_text(text, encoding="utf-8")
        return directory

    return write


def run_checker(directory: Path) -> dict[str, Any]:
    """tools/independent_checker.py, which shares no code with the package, on public and private halves."""
    public, private = directory / "public", directory / "private"
    for half, names in ((public, PUBLIC_FILES), (private, PRIVATE_FILES)):
        half.mkdir(exist_ok=True)
        for name in names:
            (half / name).write_text((directory / name).read_text(encoding="utf-8"), encoding="utf-8")
    checker = str(paths.REPO_ROOT / "tools" / "independent_checker.py")
    done = subprocess.run([sys.executable, "-I", "-S", "-B", checker, "--public", str(public), "--private",
                           str(private)], capture_output=True, text=True, check=False)  # fmt: skip
    report: dict[str, Any] = json.loads(done.stdout)
    assert done.returncode == 0, [check for check in report["identities"] if not check["ok"]]
    return report


# ------------------------------------------------------------------------------- reading the books


def public_ids(public: PublicEpisode) -> set[str]:
    """Every id a tool returns a record for: ledger rows, documents, invoice and payment ids, FX keys."""
    tables = public.tables
    return ({row["row_id"] for row in tables["ledger"]} | {i["doc_id"] for i in tables["invoices"]}
            | {i["invoice_id"] for i in tables["invoices"]} | {p["doc_id"] for p in tables["payments"]}
            | {p["payment_id"] for p in tables["payments"]} | {fx_key(row) for row in tables["fx"]})  # fmt: skip


def by_doc(public: PublicEpisode) -> dict[str, dict[str, Any]]:
    return {record["doc_id"]: dict(record) for table in ("invoices", "payments") for record in public.tables[table]}


def ledger_rows(public: PublicEpisode) -> dict[str, dict[str, Any]]:
    return {row["row_id"]: dict(row) for row in public.tables["ledger"]}


def translated(public: PublicEpisode, payment: dict[str, Any], row: dict[str, Any], target: str) -> int:
    """The receipt translated at one FX row, in exact fractions, rounded once half up (policy.fx)."""
    exponents = {code: spec["exponent"] for code, spec in public.manifest["currencies"].items()}
    major = Fraction(payment["amount_minor"], 10 ** exponents[payment["currency"]])
    rate = Fraction(row["rate"])
    value = (major * rate if row["source_currency"] == payment["currency"] else major / rate) * 10 ** exponents[target]
    return int(value + Fraction(1, 2)) if value >= 0 else -int(-value + Fraction(1, 2))


def pair_rows(public: PublicEpisode, payment: dict[str, Any], target: str) -> list[dict[str, Any]]:
    pair = {payment["currency"], target}
    return [dict(r) for r in public.tables["fx"] if {r["source_currency"], r["target_currency"]} == pair]


def received(public: PublicEpisode, payment: dict[str, Any], invoice: dict[str, Any]) -> int:
    """What the receipt brings: its amount, or the recorded translation (its fx_clearing debit, a public row)."""
    if payment["currency"] == invoice["currency"]:
        return int(payment["amount_minor"])
    names = families.account_names(public.policy)
    (debit,) = [r for r in public.tables["ledger"] if r["payment_id"] == payment["payment_id"]
                and r["account"] == names["fx_clearing"] and r["debit_minor"]]  # fmt: skip
    return int(debit["debit_minor"])


def boundary_crossed(public: PublicEpisode, issued_at: str, posted_at: str) -> str:
    indexed = families.index(public)
    sides = {indexed.side(issued_at), indexed.side(posted_at)}
    assert len(sides) == 2 and sides != {"before", "after"}
    return "start" if "before" in sides else "end"


def observed(public: PublicEpisode, truth: tuple[TruthIssue, ...]) -> dict[str, str]:
    """The sub-kinds the public books show, read from the records the truth names."""
    invoices = {i["invoice_id"]: dict(i) for i in public.tables["invoices"]}
    payments = {p["payment_id"]: dict(p) for p in public.tables["payments"]}
    names = families.account_names(public.policy)
    seen: dict[str, str] = {}
    for issue in truth:
        if issue.type == "payment_allocation":
            (invoice_id,) = issue.affected_ids & set(invoices)
            (payment_id,) = issue.affected_ids & set(payments)
            rows = [r for r in public.tables["ledger"] if r["account"] == names["receivable"]
                    and r["invoice_id"] == invoice_id and r["payment_id"] == payment_id]  # fmt: skip
            assert invoice_id in payments[payment_id]["invoice_refs"]  # the receipt names the open invoice
            applied = sum(int(r["credit_minor"]) - int(r["debit_minor"]) for r in rows)
            assert not rows or applied > 0  # partial: more than nothing applied (less than required: truth > 0)
            seen["allocation"] = "partial" if rows else "missing"
            same = payments[payment_id]["currency"] == invoices[invoice_id]["currency"]
            seen["receipt_currency"] = "same" if same else "foreign"
        elif issue.type == "cutoff":
            (invoice_id,) = issue.affected_ids
            revenue = families.revenue_row(families.index(public), invoice_id)
            seen["boundary"] = boundary_crossed(public, invoices[invoice_id]["issued_at"], revenue["timestamp"])
        elif issue.type == "duplicate_invoice":
            offsets = {invoices[i]["issued_at"][-6:] for i in issue.affected_ids}
            seen["copy_offset"] = "same" if len(offsets) == 1 else "other"
        elif issue.type == "fx_mismatch":
            (payment_id,) = issue.affected_ids
            payment = payments[payment_id]
            target = invoices[payment["invoice_refs"][0]]["currency"]
            recorded = received(public, payment, invoices[payment["invoice_refs"][0]])
            on_table = {translated(public, payment, row, target) for row in pair_rows(public, payment, target)}
            seen["fx_error"] = "date" if recorded in on_table else "rate"
    return seen


# ------------------------------------------------------------------------------- condition 4: evidence


def recompute_from_evidence(public: PublicEpisode, issue: TruthIssue, evidence: frozenset[str]) -> int:
    """The issue's amount worked out from the records in one acceptable set alone, no other row (condition 4,
    strict). Asserts the set holds the records the rule needs: for a receipt in another currency than the
    invoice, that is its fx_clearing debit (policy case-draft-2)."""
    docs, rows = by_doc(public), ledger_rows(public)
    cited_docs = [docs[i] for i in evidence if i in docs]
    if issue.type == "duplicate_invoice":
        group = [d for d in cited_docs if d.get("invoice_id") in issue.affected_ids]
        assert {d["invoice_id"] for d in group} == set(issue.affected_ids)
        keys = {(d["entity_id"], d["currency"], when(d["issued_at"]), when(d["due_at"]), json.dumps(d["line_items"]))
                for d in group}  # fmt: skip
        assert len(keys) == 1  # one obligation, recorded more than once
        return int(group[0]["total_minor"]) * (len(group) - 1)
    if issue.type == "cutoff":
        (invoice,) = [d for d in cited_docs if d.get("invoice_id") in issue.affected_ids]
        names = families.account_names(public.policy)
        (revenue,) = [rows[i] for i in evidence if i in rows and rows[i]["account"] == names["revenue"]]
        boundary_crossed(public, invoice["issued_at"], revenue["timestamp"])
        return int(invoice["total_minor"])
    if issue.type == "fx_mismatch":
        (payment,) = [d for d in cited_docs if d.get("payment_id") in issue.affected_ids]
        (rate,) = [dict(r) for r in public.tables["fx"] if fx_key(r) in evidence]
        (debit,) = [rows[i] for i in evidence if i in rows]
        required = translated(public, payment, rate, debit["currency"])
        return abs(int(debit["debit_minor"]) - required)
    (invoice,) = [d for d in cited_docs if d.get("invoice_id") in issue.affected_ids]
    (payment,) = [d for d in cited_docs if d.get("payment_id") in issue.affected_ids]
    return allocation_from_set(public, invoice, payment, evidence)


def allocation_from_set(
    public: PublicEpisode, invoice: dict[str, Any], payment: dict[str, Any], evidence: frozenset[str]
) -> int:
    """Required minus recorded, read off the cited records only: the two documents, the receivable rows carrying
    both ids and, across currencies, the receipt's fx_clearing debit (what it brings in the invoice currency)."""
    names, rows = families.account_names(public.policy), ledger_rows(public)
    cited = [rows[i] for i in evidence if i in rows]
    both = (invoice["invoice_id"], payment["payment_id"])
    applied = [r for r in cited if r["account"] == names["receivable"] and (r["invoice_id"], r["payment_id"]) == both]
    clearing = [r for r in cited if r["account"] == names["fx_clearing"] and r["payment_id"] == payment["payment_id"]
                and r["debit_minor"] and r["currency"] == invoice["currency"]]  # fmt: skip
    assert len(cited) == len(applied) + len(clearing)  # nothing else is cited, and nothing else is read
    if payment["currency"] == invoice["currency"]:
        assert not clearing  # a same-currency receipt brings its own amount: no translation row
        brings = int(payment["amount_minor"])
    else:
        (translation,) = clearing  # the recorded translation is in the set itself
        brings = int(translation["debit_minor"])
    assert payment["invoice_refs"][0] == invoice["invoice_id"]  # first in the receipt's refs, read off the document
    return min(brings, int(invoice["total_minor"])) - sum(int(r["credit_minor"]) for r in applied)


# ------------------------------------------------------------------------------- condition 5: formats


def assert_section_03_formats(public: PublicEpisode, files: dict[str, str]) -> None:
    manifest = public.manifest
    assert TIMESTAMP.match(manifest["period_start"]) and TIMESTAMP.match(manifest["period_end"])
    assert manifest["period_start"][-6:] == world.ZONES[manifest["timezone"]]
    stamps = [r["timestamp"] for r in public.tables["ledger"]] + [p["timestamp"] for p in public.tables["payments"]]
    stamps += [i[name] for i in public.tables["invoices"] for name in ("issued_at", "due_at")]
    assert all(TIMESTAMP.match(stamp) for stamp in stamps)
    money = [r[name] for r in public.tables["ledger"] for name in ("debit_minor", "credit_minor")]
    money += [p["amount_minor"] for p in public.tables["payments"]] + [
        i["total_minor"] for i in public.tables["invoices"]
    ]
    money += [line[name] for i in public.tables["invoices"] for line in i["line_items"]
              for name in ("quantity", "unit_price_minor", "amount_minor")]  # fmt: skip
    assert all(type(value) is int for value in money)
    assert all(RATE.match(r["rate"]) and DAY.match(r["date"]) for r in public.tables["fx"])
    invoice_ids = {i["invoice_id"] for i in public.tables["invoices"]}
    payment_ids = {p["payment_id"] for p in public.tables["payments"]}
    for row in public.tables["ledger"]:  # an absent link is an explicit null, never a guessed or empty id
        assert row["invoice_id"] is None or row["invoice_id"] in invoice_ids
        assert row["payment_id"] is None or row["payment_id"] in payment_ids
        assert row["entity_id"] is None or (isinstance(row["entity_id"], str) and row["entity_id"])
    assert all(set(p["invoice_refs"]) <= invoice_ids for p in public.tables["payments"])
    header, *lines = files["ledger.csv"].splitlines()
    nulls = sum(line.count(",,") + line.endswith(",") for line in lines)
    assert header.startswith("row_id,") and nulls > 0  # null written as an empty cell, read back as JSON null


# ------------------------------------------------------------------------------- D01-D20


@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("check", sorted(SCENARIOS))
def test_d01_to_d20_episode_meets_conditions_1_to_6(check: str, seed: int, written: Any) -> None:
    public, truth, provenance = episode(check, seed)
    directory = written(check, seed)
    files = {name: (directory / name).read_text(encoding="utf-8") for name in PUBLIC_FILES + PRIVATE_FILES}
    # 3: exactly the requested types and counts; a clean company has none.
    assert Counter(issue.type for issue in truth) == Counter(TYPES[check])
    assert json.loads(files["truth.json"])["issues"] == [issue.to_json() for issue in truth]
    assert provenance["generator"]["inject"] == world.normal_inject(SCENARIOS[check]["inject"])
    # 2: the sub-kind asked for is what the public books show.
    seen = observed(public, truth)
    assert {name: seen[name] for name in SUBKINDS.get(check, {})} == SUBKINDS.get(check, {})
    # 1: undoing the recorded changes gives the clean twin, and the published rules find nothing in it.
    settings, _ = shipped.parse_config(config_for(check, seed))
    twin, twin_truth, _ = shipped.generate(seed, settings, {})
    restored = books.undo(public.tables, provenance["injections"])
    for table, key in (("ledger", "row_id"), ("invoices", "invoice_id")):
        assert restored[table] == sorted(map(dict, twin.tables[table]), key=lambda r: r[key]), table
    assert twin_truth == () and families.detect(twin) == []
    # 2, 3: a checker that shares no code re-derives truth from the records and undoes provenance on its own.
    report = run_checker(directory)
    assert report["ok"] is True and report["truth_comparison"]["matches"] is True
    assert report["pre_injection"]["derived_issue_count"] == 0 and report["pre_injection"]["identities_ok"] is True
    # 4: an acceptable set exists, cites only ids the tools return, and is enough to recompute the amount.
    ids = public_ids(public)
    for issue in truth:
        assert issue.acceptable_evidence_sets and all(s and s <= ids for s in issue.acceptable_evidence_sets)
        assert recompute_from_evidence(public, issue, issue.acceptable_evidence_sets[0]) == issue.expected_amount_minor
        assert issue.currency in public.manifest["currencies"] and set(issue.affected_ids) <= ids
    # 5, 6: section 03 formats; the books load and satisfy every structural identity.
    assert_section_03_formats(public, files)
    families.validate_books(public)


@pytest.mark.parametrize("check", sorted(SCENARIOS))
def test_d01_to_d20_parameters_change_with_the_seed(check: str) -> None:
    """Not only values repeat: each seed gives another company, other ids and other amounts."""
    built = [episode(check, seed) for seed in SEEDS]
    assert len({public.manifest["episode_id"] for public, _, _ in built}) == len(SEEDS)
    assert len({public.manifest["base_currency"] for public, _, _ in built}) == len(SEEDS)
    if TYPES[check]:
        signatures = {tuple(sorted((i.type, tuple(sorted(i.affected_ids)), i.expected_amount_minor) for i in truth))
                      for _, truth, _ in built}  # fmt: skip
        assert len(signatures) == len(SEEDS)


@pytest.mark.parametrize("check", [check for check in sorted(SCENARIOS) if TYPES[check]])
def test_d06_to_d20_one_company_other_seeds_give_other_ids_amounts_and_documents(check: str) -> None:
    """D06-D08 and the rest with the company held fixed: the seed alone changes ids, amounts and documents.

    The test above lets the company change with the seed, so there a different currency is by construction.
    """
    company = {**COMPANIES[1], **SCENARIOS[check].get("generator", {})}
    built = [shipped.generate(seed, company, SCENARIOS[check]["inject"]) for seed in (2101, 2102, 2103)]
    affected = [frozenset().union(*(i.affected_ids for i in truth)) for _, truth, _ in built]
    assert all(not a & b for n, a in enumerate(affected) for b in affected[n + 1 :])
    amounts = {tuple(sorted(i.expected_amount_minor for i in truth)) for _, truth, _ in built}
    assert len(amounts) > 1
    documents = [frozenset(e for i in truth for s in i.acceptable_evidence_sets for e in s) for _, truth, _ in built]
    assert all(not a & b for n, a in enumerate(documents) for b in documents[n + 1 :])


def test_d16_to_d18_a_left_out_receipt_currency_is_drawn_from_the_seed() -> None:
    """D18 names boundary and allocation only: the receipt's currency must still vary with the seed.

    Before the review, any parameter switched on a same-currency preference, so a left-out receipt_currency
    was always "same" (60/60 seeds) while the docs said it was drawn.
    """
    company = {**COMPANIES[1], "tail_days": 12}
    shown: Counter[str] = Counter()
    for seed in range(300, 316):
        try:
            public, truth, _ = shipped.generate(seed, company, SCENARIOS["D18"]["inject"])
        except EpisodeError as refusal:
            assert "left" in str(refusal), refusal
            continue
        seen = observed(public, truth)
        assert (seen["boundary"], seen["allocation"]) == ("end", "partial")
        shown[seen["receipt_currency"]] += 1
    assert shown["same"] >= 3 and shown["foreign"] >= 3, shown


def test_d02_every_clean_company_holds_a_correctly_split_payment() -> None:
    for seed in SEEDS:
        public, truth, _ = episode("D02", seed)
        invoices = {i["invoice_id"]: i for i in public.tables["invoices"]}
        parts: dict[str, list[int]] = {}
        for p in public.tables["payments"]:
            if len(p["invoice_refs"]) == 1 and p["currency"] == invoices[p["invoice_refs"][0]]["currency"]:
                parts.setdefault(p["invoice_refs"][0], []).append(p["amount_minor"])
        split = [i for i, amounts in parts.items() if len(amounts) > 1 and sum(amounts) == invoices[i]["total_minor"]]
        assert split and truth == ()


def test_d03_every_clean_company_holds_a_correct_refund() -> None:
    for seed in SEEDS:
        public, truth, _ = episode("D03", seed)
        names = families.account_names(public.policy)
        refunds = [r for r in public.tables["ledger"] if r["account"] == names["unapplied"] and r["debit_minor"]]
        assert len(refunds) >= 2 and truth == ()


def test_d04_every_clean_company_holds_legitimate_repeated_amounts() -> None:
    for seed in SEEDS:
        public, truth, _ = episode("D04", seed)
        repeated = Counter((i["entity_id"], i["currency"], i["total_minor"]) for i in public.tables["invoices"])
        assert sum(n for n in repeated.values() if n > 1) >= 4 and truth == ()
        assert families.detect_duplicates(families.index(public)) == []


def test_d05_every_clean_company_holds_currency_and_period_boundary_look_alikes() -> None:
    for seed in SEEDS:
        public, truth, _ = episode("D05", seed)
        indexed = families.index(public)
        start, end = indexed.start, indexed.end
        near = [i for i in public.tables["invoices"]
                if min(abs(when(i["issued_at"]) - start), abs(when(i["issued_at"]) - end)).total_seconds() < 86_400]  # fmt: skip
        crossing = [
            p for p in public.tables["payments"] if p["invoice_refs"] and indexed.invoice_currency(p) != p["currency"]
        ]
        misprinted = [p for p in crossing if p["timestamp"][:10] != indexed.local_date(p["timestamp"])]
        assert near and crossing and misprinted and truth == ()


def test_d09_to_d11_missing_and_partial_allocation_are_requested_not_drawn() -> None:
    """D09-D11 need at least one missing and one partial case: each is its own inject key, never a coin toss."""
    for seed in range(40, 52):
        company = {"invoices": 12 + seed % 3 * 20, "ledger_rows": 240}
        for key, kind in (("payment_allocation_missing", "missing"), ("payment_allocation_partial", "partial")):
            public, truth, provenance = shipped.generate(seed, company, {key: 1})
            assert observed(public, truth)["allocation"] == kind and [i.type for i in truth] == ["payment_allocation"]
            applied = provenance["injections"][0]["error"]["applied_minor"]
            assert (applied == 0) == (kind == "missing")
    both = shipped.generate(7, {}, {"payment_allocation_missing": 2, "payment_allocation_partial": 1})
    kinds = Counter(observed(both[0], (issue,))["allocation"] for issue in both[1])
    assert kinds == {"missing": 2, "partial": 1}


def test_d12_d13_wrong_date_and_wrong_rate_are_requested_not_drawn() -> None:
    for seed in range(40, 52):
        company = {"invoices": 24 + seed % 3 * 20, "ledger_rows": 300}
        for key, kind in (("fx_mismatch_date", "date"), ("fx_mismatch_rate", "rate")):
            public, truth, provenance = shipped.generate(seed, company, {key: 1})
            assert observed(public, truth)["fx_error"] == kind and [i.type for i in truth] == ["fx_mismatch"]
            source = provenance["injections"][0]["error"]["rate_source"]
            assert (source == "mistyped") == (kind == "rate")


def test_d16_to_d18_interaction_1_changes_its_parameters_and_d16_is_the_case_example() -> None:
    """D16-D18: one scenario, three different parameter sets; D16 is the case's own partial foreign payment."""
    shown = {check: tuple(sorted(observed(*episode(check, seed)[:2]).items())) for check in ("D16", "D17", "D18")
             for seed in SEEDS[:1]}  # fmt: skip
    assert len(set(shown.values())) == 3
    for seed in SEEDS:
        public, truth, _ = episode("D16", seed)
        seen = observed(public, truth)
        assert (seen["allocation"], seen["receipt_currency"]) == ("partial", "foreign")
        (cutoff,) = [i for i in truth if i.type == "cutoff"]
        (allocation,) = [i for i in truth if i.type == "payment_allocation"]
        assert cutoff.affected_ids < allocation.affected_ids  # one invoice: misdated, and its receipt under-applied


def test_d16_to_d20_use_exactly_the_two_documented_interactions() -> None:
    assert world.DOCUMENTED_INTERACTIONS == ("cutoff_and_allocation", "duplicate_then_cutoff")
    for check in ("D16", "D17", "D18", "D19", "D20"):
        (entry,) = SCENARIOS[check]["inject"]["interactions"]
        expected = X1 if check <= "D18" else X2
        assert entry["name"] == expected and provenance_status(check) == "interaction"
    for check in ("D19", "D20"):
        for seed in SEEDS:
            public, truth, _ = episode(check, seed)
            (duplicate,) = [i for i in truth if i.type == "duplicate_invoice"]
            (cutoff,) = [i for i in truth if i.type == "cutoff"]
            assert cutoff.affected_ids < duplicate.affected_ids  # the copy is the record posted on the wrong side


def provenance_status(check: str) -> str:
    status: str = episode(check, SEEDS[0])[2]["status"]
    return status


def test_every_interaction_parameter_is_honoured() -> None:
    """Every value of every parameter is built and shown by the books; a roomy company never refuses one.

    (It used to `continue` on a refusal, so a value refused every time would still have passed.)
    """
    company = {"invoices": 60, "ledger_rows": 700, "tail_days": 12}
    for name, parameters in world.SCENARIO_PARAMETERS.items():
        for parameter, values in parameters.items():
            for value, seed in ((value, seed) for value in values for seed in (5, 6)):
                entry = {"name": name, parameter: value}
                public, truth, _ = shipped.generate(seed, company, {"interactions": [entry]})
                assert observed(public, truth)[parameter] == value, (entry, seed)


# ------------------------------------------------------------------------------- the config and its schema


def test_gen_config_schema_documents_exactly_what_the_parser_accepts() -> None:
    schema = json.loads((paths.REPO_ROOT / "docs" / "schemas" / "generator_config.schema.json").read_text())
    assert set(schema["properties"]) == set(shipped.CONFIG_SECTIONS) and schema["additionalProperties"] is False
    company = schema["properties"]["generator"]["properties"]
    assert set(company) == set(world.DEFAULT_CONFIG)
    assert {name: spec["default"] for name, spec in company.items()} == dict(world.DEFAULT_CONFIG)
    assert (
        set(company["base_currency"]["enum"])
        == set(world.EXPONENTS)
        == set(company["foreign_currencies"]["items"]["enum"])
    )
    assert set(company["timezone"]["enum"]) == set(world.ZONES)
    for name in ("invoices", "ledger_rows", "head_days", "tail_days"):
        low, high = company[name]["minimum"], company[name]["maximum"]
        assert world.validate_config({name: low})[name] == low and world.validate_config({name: high})[name] == high
        for outside in (low - 1, high + 1):
            with pytest.raises(EpisodeError, match=name):
                world.validate_config({name: outside})
    inject = schema["properties"]["inject"]["properties"]
    assert set(inject) == {*world.COUNT_KEYS, "interactions"}
    variants = inject["interactions"]["items"]["oneOf"]
    assert set(variants[0]["enum"]) == set(world.INTERACTIONS)
    documented = {v["properties"]["name"]["const"]: {k: tuple(p["enum"]) for k, p in v["properties"].items() if k != "name"}
                  for v in variants[1:]}  # fmt: skip
    assert documented == {name: dict(params) for name, params in world.SCENARIO_PARAMETERS.items()}
    assert [v["properties"]["name"]["const"] for v in variants[1:3]] == list(world.DOCUMENTED_INTERACTIONS)


@pytest.mark.parametrize(
    ("config", "message"),
    [
        ({"company": {}}, "unknown generator config keys"),
        ({"generator": {"colour": "red"}}, "unknown generator settings"),
        ({"inject": {"allocation_mode": "missing"}}, "inject takes"),
        ({"inject": {"interactions": [{"name": X1, "boundary": "middle"}]}}, "takes parameters"),
        ({"inject": {"interactions": [{"boundary": "start"}]}}, "object with a 'name'"),
        ({"inject": {"interactions": "cutoff_and_allocation"}}, "must be a list"),
        ({"inject": []}, "config.inject must be an object"),
        ([], "must be an object"),
    ],
)
def test_gen_config_refusals_are_clear(config: Any, message: str) -> None:
    with pytest.raises(EpisodeError, match=message):
        shipped.generate_files(1, config)


@pytest.mark.parametrize(
    ("inject", "message"),
    [
        ({"bogus": 1}, "inject takes"),
        ({"cutoff": -1}, "non-negative integer count"),
        ({"cutoff": True}, "non-negative integer count"),
        ({"cutoff": 13}, "issues = 13 is outside the case envelope 0..12"),
        ({"cutoff": 7, "interactions": [X1, X2, X1]}, "issues = 13 is outside the case envelope 0..12"),
    ],
)
def test_gen_config_parse_config_refuses_bad_inject_before_generating(inject: dict[str, Any], message: str) -> None:
    """parse_config (the train-mode team_config path too) checks inject in full, not only at generation."""
    with pytest.raises(EpisodeError, match=message):
        shipped.parse_config({"inject": inject})
    assert shipped.parse_config({"inject": {"cutoff": 6, "interactions": [X1, X2, X1]}})[1]["cutoff"] == 6


def test_gen_config_counts_are_checked_and_impossible_requests_refused() -> None:
    for inject in ({"payment_allocation_partial": True}, {"fx_mismatch_rate": -1}, {"fx_mismatch_date": 1.0}):
        with pytest.raises(EpisodeError, match="non-negative integer count"):
            shipped.generate(1, {}, inject)
    with pytest.raises(EpisodeError, match="left to mistranslate at a rate on no table row"):
        shipped.generate(1, {"invoices": 12, "ledger_rows": 200}, {"fx_mismatch_rate": 12})
    with pytest.raises(EpisodeError, match="outside the case envelope"):
        shipped.generate(1, {"invoices": 110, "ledger_rows": 2000}, {"payment_allocation_missing": 13})


def test_gen_config_without_parameters_keeps_the_old_spelling_and_episode() -> None:
    """Shipped episodes and recorded settings stay valid: a bare name and {"name": ...} are one request."""
    assert world.normal_inject({"interactions": [{"name": X1}], "payment_allocation_missing": 0}) == {
        "interactions": [X1]
    }
    plain = books.render(*shipped.generate(9, {"invoices": 24, "ledger_rows": 220}, {"interactions": [X1]}))
    named = books.render(*shipped.generate(9, {"invoices": 24, "ledger_rows": 220}, {"interactions": [{"name": X1}]}))
    assert plain == named
    recorded = shipped.generate(
        9, {}, {"interactions": [{"receipt_currency": "same", "name": X1, "boundary": "start"}]}
    )
    entry = recorded[2]["generator"]["inject"]["interactions"][0]
    assert list(entry) == ["name", "boundary", "receipt_currency"]


def test_gen_formats_asia_almaty_is_refused_where_its_offset_was_not_plus_five() -> None:
    """Asia/Almaty moved from UTC+06:00 to UTC+05:00 on 2024-03-01; an earlier window would print a wrong offset."""
    for period, head_days in (("2023-10", 6), ("2024-02", 3), ("2024-03", 3)):
        with pytest.raises(EpisodeError, match="Asia/Almaty is UTC\\+05:00 only from 2024-03-01"):
            world.validate_config({"period": period, "head_days": head_days})
    assert world.validate_config({"period": "2024-03", "head_days": 3, "timezone": "Asia/Tokyo"})
    assert world.validate_config({"period": "2024-04", "head_days": 6})["timezone"] == "Asia/Almaty"


@pytest.mark.parametrize("check", ["D09", "D13", "D16", "D18", "D19"])
def test_gen_recorded_settings_regenerate_requested_sub_kinds_and_parameters(check: str) -> None:
    """provenance.generator, fed back to the generator, gives the same eight files for the new keys too."""
    files = shipped.generate_files(SEEDS[1], config_for(check, SEEDS[1]))
    recorded = json.loads(files["provenance.json"])["generator"]
    again = shipped.generate_files(recorded["seed"], {"generator": recorded["config"], "inject": recorded["inject"]})
    assert again == files
