from __future__ import annotations

import json

import pytest
from helpers import CLEAN, EVIDENCE, FAULTY, finding

from genesis_audit import cli, paths, teaching
from genesis_audit.errors import EpisodeError
from genesis_audit.store import load_public
from genesis_audit.truth import load_truth, parse_truth, validate_truth


@pytest.mark.parametrize("name", sorted(teaching.VARIANTS))
def test_committed_files_are_exactly_what_the_builder_produces(name: str) -> None:
    public, private = teaching.render(name)
    for root, files in ((paths.PUBLIC_ROOT, public), (paths.PRIVATE_ROOT, private)):
        for filename, text in files.items():
            assert (root / name / filename).read_text(encoding="utf-8") == text, f"{name}/{filename} drifted"


def test_fits_the_paper_limits_of_prompt_b() -> None:
    public = load_public(paths.PUBLIC_ROOT / FAULTY)
    assert len(public.tables["ledger"]) <= 12
    assert len(public.tables["invoices"]) <= 3 and len(public.tables["payments"]) <= 4


def test_truth_is_the_hand_calculation() -> None:
    public = load_public(paths.PUBLIC_ROOT / FAULTY)
    (issue,) = load_truth(paths.PRIVATE_ROOT / FAULTY / "truth.json", public)
    key = finding()
    assert issue.type == key["type"] and issue.affected_ids == frozenset(key["affected_ids"])
    assert (issue.expected_amount_minor, issue.currency) == (key["claimed_amount_minor"], key["currency"])
    assert issue.acceptable_evidence_sets == (frozenset(EVIDENCE),)


def test_truth_is_recomputable_from_public_records_alone() -> None:
    for name, expected in ((FAULTY, 1), (CLEAN, 0)):
        public = load_public(paths.PUBLIC_ROOT / name)
        derived = teaching.detect_allocation_issues(public)
        truth = load_truth(paths.PRIVATE_ROOT / name / "truth.json", public)
        assert len(derived) == len(truth) == expected
        for found, issue in zip(derived, truth, strict=True):
            assert {k: v for k, v in issue.to_json().items() if k != "issue_id"} == found


def test_books_balance_before_and_after_the_injection() -> None:
    clean_rows = teaching.derive_clean_ledger(teaching.LATENT)
    teaching.check_identities(clean_rows, teaching.LATENT)
    for name in (FAULTY, CLEAN):
        rows = list(load_public(paths.PUBLIC_ROOT / name).tables["ledger"])
        teaching.check_identities(rows, teaching.LATENT)
        assert sum(r["debit_minor"] for r in rows) == sum(r["credit_minor"] for r in rows) == 1_030_000


def test_identity_check_catches_unbalanced_and_misposted_books() -> None:
    rows = teaching.derive_clean_ledger(teaching.LATENT)
    bank = next(i for i, row in enumerate(rows) if row["row_id"] == "L19")
    with pytest.raises(EpisodeError, match="debits"):
        teaching.check_identities([{**rows[0], "debit_minor": 1}, *rows[1:]], teaching.LATENT)
    swapped = [*rows[:bank], {**rows[bank], "debit_minor": 0, "credit_minor": 0}, *rows[bank + 1 :]]
    with pytest.raises(EpisodeError):
        teaching.check_identities(swapped, teaching.LATENT)


def test_provenance_reverts_to_the_clean_twin() -> None:
    provenance = json.loads((paths.PRIVATE_ROOT / FAULTY / "provenance.json").read_text())
    rows = {row["row_id"]: dict(row) for row in load_public(paths.PUBLIC_ROOT / FAULTY).tables["ledger"]}
    (injection,) = provenance["injections"]
    for change in injection["changes"]:
        if change["op"] == "insert":
            del rows[change["row"]["row_id"]]
        else:
            assert rows[change["row_id"]][change["field"]] == change["after"]
            rows[change["row_id"]][change["field"]] = change["before"]
    clean = {row["row_id"]: dict(row) for row in load_public(paths.PUBLIC_ROOT / CLEAN).tables["ledger"]}
    assert rows == clean
    assert json.loads((paths.PRIVATE_ROOT / CLEAN / "provenance.json").read_text())["injections"] == []


def test_error_is_not_given_away_by_position_ids_or_names() -> None:
    faulty, clean = (load_public(paths.PUBLIC_ROOT / name) for name in (FAULTY, CLEAN))
    order = [row["row_id"] for row in faulty.tables["ledger"]]
    touched = {"L11", "L13"}  # the two rows the mutation changed
    assert all(0 < order.index(row_id) < len(order) - 1 for row_id in touched)
    assert not touched & {min(order), max(order)}  # neither the smallest nor the largest id
    public_text = "".join((paths.PUBLIC_ROOT / FAULTY / f).read_text() for f in teaching.render(FAULTY)[0])
    for giveaway in ("clean", "faulty", "error", "inject", "truth", "teaching_b", "canary"):
        assert giveaway not in public_text.lower()
    # the decoy shares the suspicious feature (an unapplied row), and so does the clean twin
    for episode in (faulty, clean):
        unapplied = [row["payment_id"] for row in episode.tables["ledger"] if row["account"] == "unapplied_receipts"]
        assert unapplied == ["P9", "P5"]


def test_twins_differ_at_reset_only_in_episode_id() -> None:
    """Review E, row 32: nothing in the manifest, the policy or the id set may separate clean from faulty."""
    faulty, clean = (load_public(paths.PUBLIC_ROOT / name) for name in (FAULTY, CLEAN))
    assert {**faulty.manifest, "episode_id": ""} == {**clean.manifest, "episode_id": ""}
    assert faulty.manifest["episode_id"] != clean.manifest["episode_id"] and faulty.policy == clean.policy
    assert faulty.id_universe() == clean.id_universe()
    for table in ("invoices", "payments", "fx"):
        assert faulty.tables[table] == clean.tables[table]
    differing = [(a["row_id"], a["credit_minor"], b["credit_minor"])
                 for a, b in zip(faulty.tables["ledger"], clean.tables["ledger"], strict=True) if a != b]  # fmt: skip
    assert differing == [("L11", 150_000, 250_000), ("L13", 110_000, 10_000)]  # two amounts, and nothing else


def test_truth_that_needs_an_inaccessible_fact_is_refused() -> None:
    public = load_public(paths.PUBLIC_ROOT / FAULTY)
    document = json.loads((paths.PRIVATE_ROOT / FAULTY / "truth.json").read_text())
    document["issues"][0]["acceptable_evidence_sets"] = [["D31", "D44", "L11", "bank-statement-not-published"]]
    with pytest.raises(EpisodeError, match="not in public records"):
        validate_truth(parse_truth(document), public)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda d: d["issues"][0].pop("currency"), "keys"),
        (lambda d: d["issues"][0].update(type="fx_mismatch"), "not declared"),
        (lambda d: d["issues"][0].update(currency="EUR"), "undeclared currency"),
        (lambda d: d["issues"][0].update(expected_amount_minor=1.5), "integer"),
        (lambda d: d["issues"][0].update(affected_ids=[]), "non-empty"),
        (lambda d: d["issues"][0].update(acceptable_evidence_sets=[]), "non-empty"),
        (lambda d: d["issues"].append(dict(d["issues"][0])), "unique"),
        (lambda d: d.update(note="x"), "exactly the key"),
    ],
)
def test_malformed_truth_is_refused(mutate, message: str) -> None:
    public = load_public(paths.PUBLIC_ROOT / FAULTY)
    document = json.loads((paths.PRIVATE_ROOT / FAULTY / "truth.json").read_text())
    mutate(document)
    with pytest.raises(EpisodeError, match=message):
        validate_truth(parse_truth(document), public)


def test_injection_guards() -> None:
    rows = teaching.derive_clean_ledger(teaching.LATENT)
    for bad in ({"invoice_id": "I7", "payment_id": "P9", "applied_minor": 250_000},
                {"invoice_id": "I7", "payment_id": "P9", "applied_minor": 0},
                {"invoice_id": "I7", "payment_id": "P9", "applied_minor": True},
                {"invoice_id": "I7", "payment_id": "P2", "applied_minor": 1}):  # fmt: skip
        with pytest.raises(EpisodeError):
            teaching.inject_partial_allocation(rows, teaching.LATENT, **bad)
    before = [dict(row) for row in rows]
    latent = {**teaching.LATENT, "row_ids": {**teaching.LATENT["row_ids"], "pay:P2:unapplied": "L30"}}
    mutated, change = teaching.inject_partial_allocation(
        rows, latent, invoice_id="I3", payment_id="P2", applied_minor=1
    )
    assert rows == before and len(mutated) == len(rows) + 1  # the input is not modified; P2 had no unapplied row
    assert [c["op"] for c in change["changes"]] == ["update", "insert"]


def test_public_sheet_matches_and_holds_no_answer() -> None:
    page = (cli.DOCS_TUTORING / "B_paper_episode.md").read_text(encoding="utf-8")
    assert page == cli.tutor_page("B")
    assert '"claimed_amount_minor": 0' in page  # the template carries a placeholder, not the amount
    for secret in ("truth-", "inj-", "canary", 'I7", "P9'):
        assert secret not in page


def run_play(monkeypatch, capsys, lines: list[str]) -> tuple[int, str]:
    import io

    monkeypatch.setattr("sys.stdin", io.StringIO("".join(line + "\n" for line in lines)))
    status = cli.main(["play", "--episode", FAULTY])
    return status, capsys.readouterr().out


def test_play_checks_only_on_submit(monkeypatch, capsys, tmp_path) -> None:
    answer = tmp_path / "findings.json"
    answer.write_text(json.dumps({"episode_id": "ep-4c1f09", "findings": [finding()]}))
    status, out = run_play(
        monkeypatch, capsys, ["list payments", "doc D44", "get ledger L11", "bogus", f"submit {answer}"]
    )
    before, _, after = out.partition("Episode over.")
    assert status == 0 and '"tp": 1' in after and '"fp": 0' in after
    for leak in ("truth-", '"tp"', "matched", "fn"):
        assert leak not in before


def test_play_can_be_left_without_scoring(monkeypatch, capsys) -> None:
    status, out = run_play(monkeypatch, capsys, ["list ledger 5", "submit /no/such/file.json", "quit"])
    assert status == 1 and "nothing was scored" in out and "Could not read that" in out and '"tp"' not in out
    status, out = run_play(
        monkeypatch, capsys, ["raw not-json", 'raw {"action": "get_document", "args": {"doc_id": "D31"}}']
    )
    assert status == 1 and "Robotics workshop session" in out


# --- The first tests asked for by the adversarial review (docs/review/E_adversarial_review.md, section 6) ---


def mirror(issue) -> dict:
    """The finding that restates a truth issue exactly."""
    return {
        "type": issue.type,
        "affected_ids": sorted(issue.affected_ids),
        "claimed_amount_minor": issue.expected_amount_minor,
        "currency": issue.currency,
        "evidence_ids": sorted(issue.acceptable_evidence_sets[0]),
        "explanation": "",
    }


@pytest.mark.parametrize("name", [FAULTY, CLEAN])
def test_every_truth_issue_is_matchable_by_a_well_formed_finding(name: str) -> None:
    from genesis_audit.matching import match
    from genesis_audit.schemas import parse_submission

    public = load_public(paths.PUBLIC_ROOT / name)
    truth = load_truth(paths.PRIVATE_ROOT / name / "truth.json", public)
    document = {"episode_id": public.manifest["episode_id"], "findings": [mirror(issue) for issue in truth]}
    findings = parse_submission({"findings": document}, public.manifest["episode_id"], public.manifest["limits"])
    result = match(
        findings, truth, tolerance=public.manifest["amount_tolerance_minor"], universe=public.evidence_universe()
    )
    assert (result.tp, result.fp, result.fn) == (len(truth), 0, 0)


UNMATCHABLE = [
    (lambda i, pub: i.update(acceptable_evidence_sets=[sorted(pub.evidence_universe())[:11]]), "evidence"),
    (lambda i, pub: i.update(affected_ids=sorted(pub.id_universe())[:21]), "affected"),
    (lambda i, pub: i.update(affected_ids=["I7", "P404"]), "affected"),
    (lambda i, pub: i.update(expected_amount_minor=2**53), "amount"),
    (lambda i, pub: i.update(currency=["KZT"]), "currency"),
    (lambda i, pub: i.update(type=7), "type"),
]


@pytest.mark.parametrize(("mutate", "message"), UNMATCHABLE)
def test_truth_that_no_well_formed_finding_can_match_is_refused(mutate, message: str) -> None:
    public = load_public(paths.PUBLIC_ROOT / FAULTY)
    document = json.loads((paths.PRIVATE_ROOT / FAULTY / "truth.json").read_text())
    mutate(document["issues"][0], public)
    if message == "type":
        public = type(public)(
            {**public.manifest, "issue_types": [document["issues"][0]["type"]]}, public.policy, public.tables
        )
    if message == "currency" and isinstance(document["issues"][0]["currency"], str):
        manifest = {**public.manifest, "currencies": {**public.manifest["currencies"], "USDT": {"exponent": 2}},
                    "amount_tolerance_minor": {**public.manifest["amount_tolerance_minor"], "USDT": 0}}  # fmt: skip
        public = type(public)(manifest, public.policy, public.tables)
    with pytest.raises(EpisodeError, match=message):
        validate_truth(parse_truth(document), public)


def test_truth_with_any_declared_type_or_currency_string_is_matchable() -> None:
    """Findings carry any type/currency string (official conventions 4-5), so such a truth is expressible."""
    from genesis_audit.matching import match
    from genesis_audit.schemas import parse_submission

    public = load_public(paths.PUBLIC_ROOT / FAULTY)
    document = json.loads((paths.PRIVATE_ROOT / FAULTY / "truth.json").read_text())
    document["issues"][0].update(type="Payment-Allocation", currency="USDT")
    manifest = {**public.manifest, "issue_types": ["Payment-Allocation"],
                "currencies": {**public.manifest["currencies"], "USDT": {"exponent": 2}},
                "amount_tolerance_minor": {**public.manifest["amount_tolerance_minor"], "USDT": 0}}  # fmt: skip
    public = type(public)(manifest, public.policy, public.tables)
    truth = parse_truth(document)
    validate_truth(truth, public)
    claim = {"episode_id": manifest["episode_id"], "findings": [mirror(truth[0])]}
    findings = parse_submission({"findings": claim}, manifest["episode_id"], manifest["limits"])
    result = match(findings, truth, tolerance=manifest["amount_tolerance_minor"], universe=public.evidence_universe())
    assert (result.tp, result.fp, result.fn) == (1, 0, 0)


def test_two_issues_with_the_same_scored_fields_are_refused() -> None:
    public = load_public(paths.PUBLIC_ROOT / FAULTY)
    document = json.loads((paths.PRIVATE_ROOT / FAULTY / "truth.json").read_text())
    document["issues"].append({**document["issues"][0], "issue_id": "truth-000000000000", "expected_amount_minor": 5})
    with pytest.raises(EpisodeError, match="share"):
        validate_truth(parse_truth(document), public)


def test_a_receipt_spread_over_nine_invoices_still_has_evidence_within_the_cap() -> None:
    count = 9
    invoices = [
        {"doc_id": f"D{n}", "invoice_id": f"I{n}", "entity_id": "E1", "issued_at": f"2026-10-0{n}T10:00:00+05:00",
         "due_at": "2026-10-30T18:00:00+05:00", "currency": "KZT",
         "line_items": [{"description": "seat", "quantity": 1, "unit_price_minor": 1000, "amount_minor": 1000}]}
        for n in range(1, count + 1)
    ]  # fmt: skip
    payment = {"doc_id": "D90", "payment_id": "P1", "timestamp": "2026-10-20T09:00:00+05:00", "currency": "KZT",
               "amount_minor": 1000 * count, "invoice_refs": [f"I{n}" for n in range(1, count + 1)]}  # fmt: skip
    row_ids = {"pay:P1:bank": "L900", "pay:P1:unapplied": "L901"}
    for n in range(1, count + 1):
        row_ids.update(
            {f"issue:I{n}:receivable": f"L1{n}", f"issue:I{n}:revenue": f"L2{n}", f"pay:P1:receivable:I{n}": f"L3{n}"}
        )
    latent = {**teaching.LATENT, "invoices": invoices, "payments": [payment], "fx": [], "row_ids": row_ids}
    public, truth, _ = teaching.build_from(
        latent, "ep-nine", [{"invoice_id": "I5", "payment_id": "P1", "applied_minor": 400}]
    )
    (issue,) = truth
    assert issue.expected_amount_minor == 600 and issue.affected_ids == frozenset({"I5", "P1"})
    assert issue.acceptable_evidence_sets == (frozenset({"D5", "D90", "L35"}),)
    assert len(public.tables["ledger"]) == 2 * count + 1 + count + 1  # the insert path: an unapplied row was added


def test_issue_ids_are_not_a_function_of_the_scored_fields() -> None:
    import hashlib

    from genesis_audit import canon

    for name in (FAULTY, CLEAN):
        public = load_public(paths.PUBLIC_ROOT / name)
        for issue in load_truth(paths.PRIVATE_ROOT / name / "truth.json", public):
            scored = {
                k: v
                for k, v in issue.to_json().items()
                if k in ("type", "affected_ids", "expected_amount_minor", "currency")
            }
            assert "truth-" + hashlib.sha256(canon.dumps(scored).encode("ascii")).hexdigest()[:12] != issue.issue_id
    public_default, private_default = teaching.render(FAULTY)
    public_other, private_other = teaching.render(FAULTY, secret=b"another evaluator secret")
    assert public_default == public_other  # a secret never changes a public file
    default_ids = [issue["issue_id"] for issue in json.loads(private_default["truth.json"])["issues"]]
    other_ids = [issue["issue_id"] for issue in json.loads(private_other["truth.json"])["issues"]]
    assert default_ids and set(default_ids).isdisjoint(other_ids)
    assert (
        json.loads(private_default["provenance.json"])["canary"]
        != json.loads(private_other["provenance.json"])["canary"]
    )


def test_play_reads_policy_json_strictly(monkeypatch, capsys, tmp_path) -> None:
    duplicated = tmp_path / "duplicated.json"
    duplicated.write_text('{"episode_id": "ep-other", "episode_id": "ep-4c1f09", "findings": []}')
    lines = [
        "raw " + "[" * 200_000,
        'raw {"action": "get_document", "args": {"doc_id": NaN}}',
        f"submit {duplicated}",
        "quit",
    ]
    status, out = run_play(monkeypatch, capsys, lines)
    assert status == 1 and out.count("Could not read that") == 3
    assert "Episode over" not in out and "nothing was scored" in out


def test_detector_must_find_exactly_what_was_injected(monkeypatch) -> None:
    """Judge question 2: a count is not enough. The detector must report the injected pair and amount."""
    real = teaching.detect_allocation_issues

    def wrong_pair(episode):
        return [{**issue, "affected_ids": ["I3", "P9"]} for issue in real(episode)]

    def wrong_amount(episode):
        return [{**issue, "expected_amount_minor": issue["expected_amount_minor"] + 1} for issue in real(episode)]

    for fake in (wrong_pair, wrong_amount, lambda episode: []):
        monkeypatch.setattr(teaching, "detect_allocation_issues", fake)
        with pytest.raises(EpisodeError):
            teaching.build(FAULTY)


SINGLE_INJECTIONS = [
    ({"invoice_id": "I7", "payment_id": "P9", "applied_minor": 150_000}, ("I7", "P9", 100_000, {"D31", "D44", "L11"})),
    ({"invoice_id": "I3", "payment_id": "P5", "applied_minor": 60_000}, ("I3", "P5", 40_000, {"D12", "D36", "L23"})),
    ({"invoice_id": "I3", "payment_id": "P2", "applied_minor": 100_000}, ("I3", "P2", 50_000, {"D12", "D27", "L17"})),
]


@pytest.mark.parametrize(("injection", "expected"), SINGLE_INJECTIONS)
def test_every_single_injection_on_the_latent_is_found_and_matchable(injection: dict, expected: tuple) -> None:
    """Each key below is a hand calculation, not the detector's output.

    The P2 case is the one that needs the open-balance rule: after P2 is under-allocated, P5 must
    still be judged against what P2 was *required* to settle, so P5 raises no second issue.
    """
    latent = {**teaching.LATENT, "row_ids": {**teaching.LATENT["row_ids"], "pay:P2:unapplied": "L30"}}
    public, truth, provenance = teaching.build_from(latent, "ep-variant", [injection])
    (issue,) = truth
    invoice, payment, amount, evidence = expected
    assert issue.affected_ids == frozenset({invoice, payment}) and issue.expected_amount_minor == amount
    assert issue.acceptable_evidence_sets == (frozenset(evidence),)
    assert sum(r["debit_minor"] for r in public.tables["ledger"]) == sum(
        r["credit_minor"] for r in public.tables["ledger"]
    )
    assert provenance["injections"][0]["target"] == {"invoice_id": invoice, "payment_id": payment}


def test_receipts_with_an_undefined_order_are_refused() -> None:
    """Judge question 11c: a tie broken by payment_id would change truth when ids are renamed."""
    payments = [dict(p) for p in teaching.LATENT["payments"]]
    payments[2]["timestamp"] = payments[1]["timestamp"]  # P5 now arrives at the same instant as P2, both for I3
    latent = {**teaching.LATENT, "payments": payments}
    with pytest.raises(EpisodeError, match="order is undefined"):
        teaching.build_from(latent, "ep-tie", [])


def test_missing_row_id_in_a_latent_history_is_an_episode_error() -> None:
    rows = teaching.derive_clean_ledger(teaching.LATENT)
    with pytest.raises(EpisodeError, match="names no row id"):
        teaching.inject_partial_allocation(rows, teaching.LATENT, invoice_id="I3", payment_id="P2", applied_minor=1)


def test_balanced_duplicate_posting_passes_the_loader_and_fails_the_identity_checks(tmp_path) -> None:
    """Judge question 4. Balance is necessary, not sufficient: the loader cannot see a balanced duplicate.

    That is a stated limit of the loader, not a feature: a wrong truth file for such books is caught
    only by a check that knows the family, here the builder's identities and the independent checker.
    """
    import shutil

    target = tmp_path / "episode"
    shutil.copytree(paths.PUBLIC_ROOT / CLEAN, target)
    ledger = (target / "ledger.csv").read_text()
    ledger += "L40,2026-10-05T10:00:00+05:00,accounts_receivable,250000,0,KZT,E4,I7,\n"
    ledger += "L41,2026-10-05T10:00:00+05:00,revenue,0,250000,KZT,E4,I7,\n"
    (target / "ledger.csv").write_text(ledger)
    manifest = (target / "manifest.json").read_text().replace('"ledger_rows": 12', '"ledger_rows": 14')
    (target / "manifest.json").write_text(manifest)
    duplicated = load_public(target)  # accepted: debits still equal credits
    assert len(duplicated.tables["ledger"]) == 14
    with pytest.raises(EpisodeError, match="invoice I7"):
        teaching.check_identities(list(duplicated.tables["ledger"]), teaching.LATENT)


HAND_KEYS = {
    "teaching_b": [("I7", "P9", 100_000, {"D31", "D44", "L11"})],
    "teaching_b_p5": [("I3", "P5", 40_000, {"D12", "D36", "L23"})],
    "teaching_b_both": [("I3", "P5", 40_000, {"D12", "D36", "L23"}), ("I7", "P9", 100_000, {"D31", "D44", "L11"})],
    "teaching_b_clean": [],
}


@pytest.mark.parametrize("name", sorted(HAND_KEYS))
def test_every_shipped_truth_equals_its_hand_calculation(name: str) -> None:
    public = load_public(paths.PUBLIC_ROOT / name)
    truth = load_truth(paths.PRIVATE_ROOT / name / "truth.json", public)
    found = sorted(
        (*sorted(i.affected_ids), i.expected_amount_minor, tuple(sorted(i.acceptable_evidence_sets[0]))) for i in truth
    )
    assert found == sorted((inv, pay, amount, tuple(sorted(ev))) for inv, pay, amount, ev in HAND_KEYS[name])
    assert set(HAND_KEYS) == set(teaching.VARIANTS)


def test_all_variants_look_alike_at_reset() -> None:
    """Nothing in the manifest, the policy, the documents or the id set separates one variant from another."""
    episodes = [load_public(paths.PUBLIC_ROOT / name) for name in sorted(teaching.VARIANTS)]
    assert len({episode.manifest["episode_id"] for episode in episodes}) == len(episodes) == 4
    for episode in episodes[1:]:
        assert {**episode.manifest, "episode_id": ""} == {**episodes[0].manifest, "episode_id": ""}
        assert episode.policy == episodes[0].policy and episode.id_universe() == episodes[0].id_universe()
        assert all(episode.tables[table] == episodes[0].tables[table] for table in ("invoices", "payments", "fx"))


def variants_for_order_tests() -> list:
    latent = {**teaching.LATENT, "row_ids": {**teaching.LATENT["row_ids"], "pay:P2:unapplied": "L30"}}
    built = [teaching.build(name)[0] for name in sorted(teaching.VARIANTS)]
    p2 = {"invoice_id": "I3", "payment_id": "P2", "applied_minor": 100_000}
    return [*built, teaching.build_from(latent, "ep-p2", [p2])[0]]


def test_truth_does_not_depend_on_row_order() -> None:
    """Judge, fix 3: the same truth for 100 shuffles of every table, on every hand-built variant."""
    from genesis_audit.prng import KeyedStream
    from genesis_audit.store import PublicEpisode

    def canonical(episode) -> list:
        return sorted(json.dumps(issue, sort_keys=True) for issue in teaching.detect_allocation_issues(episode))

    for number, public in enumerate(variants_for_order_tests()):
        expected = canonical(public)
        stream = KeyedStream(b"order-test", f"variant-{number}")
        for _ in range(100):
            tables = {name: tuple(stream.shuffled(rows)) for name, rows in public.tables.items()}
            assert canonical(PublicEpisode(public.manifest, public.policy, tables)) == expected


def three_receipts_at_one_instant() -> dict:
    """The judge's case D1: P1 and P3 pay I1 at the same instant, with P2 (for I2) listed between them."""
    instant = "2026-10-20T09:00:00+05:00"
    item = [{"description": "seat", "quantity": 1, "unit_price_minor": 1000, "amount_minor": 1000}]
    invoices = [
        {"doc_id": f"D{n}", "invoice_id": f"I{n}", "entity_id": f"E{n}", "issued_at": f"2026-10-0{n}T10:00:00+05:00",
         "due_at": "2026-10-30T18:00:00+05:00", "currency": "KZT", "line_items": item}
        for n in (1, 2)
    ]  # fmt: skip
    payments = [
        {"doc_id": f"D9{n}", "payment_id": f"P{n}", "timestamp": instant, "currency": "KZT", "amount_minor": amount,
         "invoice_refs": [reference]}
        for n, amount, reference in ((1, 600, "I1"), (2, 500, "I2"), (3, 600, "I1"))
    ]  # fmt: skip
    ids = {f"issue:I{n}:{side}": f"L{n}{k}" for n in (1, 2) for k, side in enumerate(("receivable", "revenue"))}
    ids |= {f"pay:P{n}:{part}": f"L{n}{k}" for n in (1, 2, 3) for k, part in enumerate(("bank", "unapplied"), start=3)}
    ids |= {"pay:P1:receivable:I1": "L15", "pay:P2:receivable:I2": "L25", "pay:P3:receivable:I1": "L35"}
    return {**teaching.LATENT, "invoices": invoices, "payments": payments, "fx": [], "row_ids": ids}


def test_ties_that_are_not_adjacent_are_refused_when_built_and_when_loaded(tmp_path) -> None:
    from genesis_audit.store import PublicEpisode, receipt_order_conflicts, render_public, validate_public

    latent = three_receipts_at_one_instant()
    assert receipt_order_conflicts(latent["payments"]) == [("I1", "P1", "P3")]
    with pytest.raises(EpisodeError, match="order is undefined"):
        teaching.build_from(latent, "ep-tie3", [])
    rows = teaching.derive_clean_ledger(latent)
    keys = ("doc_id", "invoice_id", "entity_id", "issued_at", "due_at", "currency")
    invoices = tuple(
        {**{k: i[k] for k in keys}, "total_minor": 1000, "line_items": i["line_items"]} for i in latent["invoices"]
    )
    counts = {"ledger_rows": len(rows), "documents": 5, "fx_rates": 0}
    manifest = {**load_public(paths.PUBLIC_ROOT / FAULTY).manifest, "counts": counts}
    tables = {"ledger": tuple(rows), "invoices": invoices, "payments": tuple(latent["payments"]), "fx": ()}
    episode = PublicEpisode(manifest, teaching.POLICY, tables)
    with pytest.raises(EpisodeError, match="order is undefined"):
        validate_public(episode)
    for filename, text in render_public(episode).items():
        (tmp_path / filename).write_text(text)
    with pytest.raises(EpisodeError, match="order is undefined"):
        load_public(tmp_path)  # the same records written to disk must not load either
