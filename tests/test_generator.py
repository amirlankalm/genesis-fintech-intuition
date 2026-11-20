"""The seeded generator: determinism, the size envelope, twins, valid look-alikes, shortcuts, splits and scale."""

from __future__ import annotations

import hashlib
import json
import re
import time
import tracemalloc
from collections import Counter
from datetime import timedelta
from typing import Any

import pytest

from genesis_audit import books, evaluate, families, paths, shipped, world
from genesis_audit.env import AuditEnv
from genesis_audit.episodes import LoadedEpisode
from genesis_audit.errors import EpisodeError
from genesis_audit.families import when
from genesis_audit.prng import DEV_SECRET

OTHER_SECRET = b"another-evaluator-key-0123456789"
SMALL = {"invoices": 24, "ledger_rows": 220}
ONE_OF_EACH = {"duplicate_invoice": 1, "payment_allocation": 1, "fx_mismatch": 1, "cutoff": 1}
ID_TEMPLATE = re.compile(r"[LDIPE][A-HJKMNP-Z2-9]{6}")


def digest(files: tuple[dict[str, str], dict[str, str]]) -> str:
    return hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()


@pytest.fixture(scope="module")
def generated() -> dict[str, Any]:
    """Every generated episode, loaded once: public records, truth and private provenance."""
    source = evaluate.DirectorySource(paths.PUBLIC_ROOT, paths.PRIVATE_ROOT)
    return {
        name: (
            source.load(name),
            json.loads((paths.PRIVATE_ROOT / name / "provenance.json").read_text(encoding="utf-8")),
        )
        for name in evaluate.GENERATED
    }


# ------------------------------------------------------------------------------- determinism


def test_same_seed_config_and_key_give_the_same_bytes() -> None:
    """D3, D5: no clock, no global generator, no dependence on dict or set order."""
    first = books.render(*shipped.generate(31, SMALL, ONE_OF_EACH))
    assert first == books.render(*shipped.generate(31, dict(reversed(list(SMALL.items()))), dict(ONE_OF_EACH)))
    # Pinned: another machine or Python version must produce exactly these files. Re-pinned on 20 Nov 2026 for
    # policy case-draft-2: only policy.json differs from the case-draft-1 pin (660166b3...42960dc).
    assert digest(first) == "f7bd5a42a8f61108f778188b170873c636794b298c41c52011c760bf44eb054b"
    assert digest(books.render(*shipped.generate(32, SMALL, ONE_OF_EACH))) != digest(first)
    assert digest(books.render(*shipped.generate(31, {**SMALL, "invoices": 25}, ONE_OF_EACH))) != digest(first)


def test_the_generator_uses_no_clock_and_no_global_randomness() -> None:
    for module in (world, books, families, shipped):
        source = (paths.REPO_ROOT / "src" / "genesis_audit" / f"{module.__name__.rsplit('.', 1)[1]}.py").read_text()
        assert "import random" not in source and "from random" not in source and "time.time" not in source
        assert ".now(" not in source and "os.urandom" not in source and "secrets" not in source


def test_without_the_key_the_records_say_nothing_about_the_seed() -> None:
    """D4: another key gives another company, so a seed cannot be confirmed by regenerating with the public key."""
    public, _, _ = shipped.generate(31, SMALL, ONE_OF_EACH)
    other, _, _ = shipped.generate(31, SMALL, ONE_OF_EACH, secret=OTHER_SECRET)
    assert public.manifest["episode_id"] != other.manifest["episode_id"]
    ids = {row["row_id"] for row in public.tables["ledger"]}
    assert not ids & {row["row_id"] for row in other.tables["ledger"]}
    assert [i["total_minor"] for i in public.tables["invoices"]] != [i["total_minor"] for i in other.tables["invoices"]]
    visible = json.dumps([public.manifest, public.tables["ledger"][:50], public.tables["invoices"]])
    assert "31" not in re.findall(r"seed\W+\d+", visible) and "seed" not in visible and "inject" not in visible


def test_settings_are_validated() -> None:
    bad = [{"colour": "red"}, {"timezone": "Europe/Berlin"}, {"period": "October"}, {"period": "2026-13"},
           {"invoices": 5}, {"ledger_rows": 5000}, {"foreign_currencies": []}, {"foreign_currencies": ["KZT"]},
           {"base_currency": "XXX"}, {"head_days": 1}, {"invoices": True}]  # fmt: skip
    for config in bad:
        with pytest.raises(EpisodeError):
            world.generate_world(1, config, DEV_SECRET)
    for seed in (-1, True, "7"):
        with pytest.raises(EpisodeError):
            world.generate_world(seed, {}, DEV_SECRET)  # type: ignore[arg-type]
    company = world.generate_world(1, {}, DEV_SECRET)
    for inject in ({"refunds": 1}, {"cutoff": -1}, {"interactions": ["unheard_of"]}, {"fx_mismatch": True}):
        with pytest.raises(EpisodeError):
            world.plan_errors(company, inject, DEV_SECRET)
    assert world.period_bounds("2026-Q1") == ((2026, 1, 1), (2026, 3, 31)) and world.period_bounds("2028-02")[1] == (
        2028,
        2,
        29,
    )


def test_the_size_envelope_of_the_draft_is_enforced() -> None:
    """[S1]: 200 to 2,000 ledger rows, 20 to 200 documents, 0 to 12 issues. Outside it the episode is refused."""
    with pytest.raises(EpisodeError, match="ledger_rows = 45 is outside the case envelope"):
        books.build(shipped.FIXTURE_WORLD, [], envelope=True)  # the hand fixture is far too small to be a case episode
    largest = {"invoices": 110, "ledger_rows": 2000}
    clean = [shipped.generate(seed, largest, {})[0].manifest["counts"] for seed in range(60, 84)]
    assert all(c["ledger_rows"] <= 2000 and c["documents"] <= 200 for c in clean)
    refused, faulty = 0, []
    for seed in range(
        60, 84
    ):  # errors that add records at the largest size: inside the envelope, or refused with a reason
        try:
            faulty.append(shipped.generate(seed, largest, {"duplicate_invoice": 2})[0].manifest["counts"])
            assert faulty[-1]["ledger_rows"] <= 2000 and faulty[-1]["documents"] <= 200
        except EpisodeError as refusal:
            refused += 1
            assert "outside the case envelope" in str(refusal)
    assert refused < 12  # a company at the very edge may be refused; most have room
    # Found by the adversarial review: clean companies used to stop at a fixed 1,974 rows and 188 documents, so
    # any count above either was a faulty company for certain. Now no count separates them: clean companies go
    # past the old row wall, and the ranges of clean and faulty counts overlap almost entirely.
    assert max(c["ledger_rows"] for c in clean) > 1974
    for count in ("ledger_rows", "documents"):
        assert max(c[count] for c in clean) >= sorted(c[count] for c in faulty)[len(faulty) // 2], count
        assert len({c[count] for c in clean}) > 8, count  # no wall: many different counts at the top
    smallest = shipped.generate(60, {"invoices": 12, "ledger_rows": 200}, {})[0].manifest["counts"]
    assert 200 <= smallest["ledger_rows"] <= 260 and smallest["documents"] >= 20
    with pytest.raises(EpisodeError, match="issues = 13 is outside the case envelope"):
        shipped.generate(
            5, {"invoices": 60, "ledger_rows": 700}, {"duplicate_invoice": 5, "cutoff": 5, "payment_allocation": 3}
        )
    with pytest.raises(EpisodeError, match="left to"):  # more errors of a family than the company has places for
        shipped.generate(5, SMALL, {"fx_mismatch": 40})


@pytest.mark.parametrize("seed", range(300, 324))
def test_any_seed_builds_a_valid_company_or_is_refused_cleanly(seed: int) -> None:
    """B6: across seeds and settings the build either passes every check or refuses with a reason."""
    bases = ["KZT", "USD", "EUR", "JPY", "GBP", "KWD"]
    config = {
        "base_currency": bases[seed % 6], "foreign_currencies": [bases[(seed + 1) % 6], bases[(seed + 3) % 6]][: 1 + seed % 2],
        "timezone": list(world.ZONES)[seed % len(world.ZONES)], "period": ["2026-10", "2026-Q3", "2027-02", "2026-12"][seed % 4],
        "invoices": 20 + (seed * 7) % 80, "ledger_rows": 230 + (seed * 131) % 1500,
    }  # fmt: skip
    inject = {"duplicate_invoice": seed % 3, "payment_allocation": seed % 2, "fx_mismatch": (seed + 1) % 2,
              "cutoff": seed % 4 % 3, "interactions": [world.INTERACTIONS[seed % 3]] if seed % 4 == 0 else []}  # fmt: skip
    try:
        public, truth, provenance = shipped.generate(seed, config, inject, secret=OTHER_SECRET)
    except EpisodeError as refusal:
        assert "left to" in str(refusal) or "envelope" in str(refusal) or "nothing left" in str(refusal), refusal
        return
    clean, clean_truth, _ = shipped.generate(seed, config, {}, secret=OTHER_SECRET)
    assert clean_truth == () and families.detect(clean) == []
    lacking = [
        kind for kind, count in _look_alikes(LoadedEpisode(public=clean, truth=clean_truth)).items() if not count
    ]
    assert not lacking, lacking  # B8: whatever the seed and size, the clean company holds every valid look-alike
    wanted = sum(v for k, v in inject.items() if k != "interactions") + 2 * len(inject["interactions"])
    assert len(truth) == wanted == len(provenance["injections"])
    restored = books.undo(public.tables, provenance["injections"])
    assert restored["ledger"] == sorted(map(dict, clean.tables["ledger"]), key=lambda r: r["row_id"])
    assert restored["invoices"] == sorted(map(dict, clean.tables["invoices"]), key=lambda r: r["invoice_id"])
    assert families.scan_steps(public) + 1 <= 100


# ------------------------------------------------------------------- the shipped episodes


def test_shipped_episodes_are_inside_the_envelope_and_vary(generated) -> None:
    sizes = {name: loaded.public.manifest["counts"] for name, (loaded, _) in generated.items()}
    assert all(200 <= c["ledger_rows"] <= 2000 and 20 <= c["documents"] <= 200 for c in sizes.values())
    assert min(c["ledger_rows"] for c in sizes.values()) < 260 and max(c["ledger_rows"] for c in sizes.values()) >= 1950
    issues = [len(loaded.truth) for loaded, _ in generated.values()]
    assert min(issues) == 0 and max(issues) == 12
    manifests = [loaded.public.manifest for loaded, _ in generated.values()]
    assert len({m["base_currency"] for m in manifests}) >= 5 and len({m["timezone"] for m in manifests}) >= 6
    assert {spec["exponent"] for m in manifests for spec in m["currencies"].values()} == {0, 2, 3}
    assert len({m["period_start"][:7] for m in manifests}) >= 10  # many different periods
    assert len({m["episode_id"] for m in manifests}) == 20


def test_splits_are_disjoint_and_twins_stay_together(generated) -> None:
    """D7: ten train, ten dev, no seed in both, twin pairs in one split, the mix the draft proposes."""
    splits = json.loads((paths.REPO_ROOT / "episodes" / "splits.json").read_text(encoding="utf-8"))
    assert [len(splits[name]) for name in ("teaching", "fixture", "train", "dev")] == [4, 7, 10, 10]
    seeds = {split: {generated[name][1]["generator"]["seed"] for name in splits[split]} for split in ("train", "dev")}
    assert not seeds["train"] & seeds["dev"]
    for name, (_, provenance) in generated.items():
        assert provenance["split"] == evaluate.EPISODES[name]["split"] == name.split("_")[0]
        assert provenance["status"] == evaluate.EPISODES[name]["status"]
    companies: dict[str, set[str]] = {}
    for _name, (_, provenance) in generated.items():
        companies.setdefault(json.dumps(provenance["generator"]["seed"]), set()).add(provenance["split"])
    assert all(len(found) == 1 for found in companies.values())  # one company never appears in two splits
    assert sum(len(found) for found in companies.values()) == 18  # twenty episodes, eighteen companies: two twin pairs
    status = Counter(evaluate.EPISODES[name]["status"] for name in generated)
    assert status == {"clean": 5, "interaction": 5, "faulty": 10}
    bases = {
        split: {generated[name][0].public.manifest["base_currency"] for name in splits[split]}
        for split in ("train", "dev")
    }
    assert bases["dev"] - bases["train"]  # dev shows base currencies train never does
    for family in families.FAMILIES:  # every family alone or combined in both splits
        for split in ("train", "dev"):
            assert any(family in evaluate.EPISODES[name]["families"] for name in splits[split])


@pytest.mark.parametrize(("clean_name", "faulty_name"), [("train_01", "train_02"), ("dev_03", "dev_04")])
def test_twins_differ_only_in_what_the_errors_touch(clean_name: str, faulty_name: str, generated) -> None:
    """B10: a clean company and the same company with errors share everything but the mutated records."""
    (clean, _), (faulty, provenance) = generated[clean_name], generated[faulty_name]
    touched = {change.get("id") or change["record"].get("row_id") or change["record"]["invoice_id"]
               for injection in provenance["injections"] for change in injection["changes"]}  # fmt: skip
    for table, key in (("ledger", "row_id"), ("invoices", "invoice_id"), ("payments", "payment_id")):
        before = {record[key]: record for record in clean.public.tables[table]}
        after = {record[key]: record for record in faulty.public.tables[table]}
        differing = {name for name in set(before) | set(after) if before.get(name) != after.get(name)}
        assert differing <= touched, (table, differing - touched)
    assert clean.public.tables["fx"] == faulty.public.tables["fx"] and clean.public.policy == faulty.public.policy
    same = {key: value for key, value in clean.public.manifest.items() if key not in ("episode_id", "counts")}
    assert same == {key: value for key, value in faulty.public.manifest.items() if key not in ("episode_id", "counts")}
    assert clean.truth == () and len(faulty.truth) == len(provenance["injections"])


def _look_alikes(loaded: Any) -> dict[str, int]:
    """Valid records that share the surface feature of an error, counted by kind."""
    public = loaded.public
    indexed = families.index(public)
    invoices, payments, ledger = public.tables["invoices"], public.tables["payments"], public.tables["ledger"]
    flagged = {tuple(sorted(issue.affected_ids)) for issue in loaded.truth}
    names = indexed.names
    allocated = {
        (r["payment_id"], r["invoice_id"]) for r in ledger if r["account"] == names["receivable"] and r["payment_id"]
    }
    same_total = Counter((i["entity_id"], i["currency"], i["total_minor"]) for i in invoices)
    translated = [
        p for p in payments if indexed.invoice_currency(p) != p["currency"]
    ]  # every receipt in another currency
    crossing = [p for p in translated if (p["payment_id"],) not in flagged]
    start, end = indexed.start, indexed.end
    lags = [(when(indexed.by_invoice[i["invoice_id"]][0]["timestamp"]) - when(i["issued_at"])) for i in invoices
            if (i["invoice_id"],) not in flagged]  # fmt: skip
    return {
        "receipt_names_an_invoice_but_has_no_allocation": sum(
            1 for p in payments for ref in p["invoice_refs"]
            if (p["payment_id"], ref) not in allocated and tuple(sorted((ref, p["payment_id"]))) not in flagged),
        "unapplied_credit": sum(1 for r in ledger if r["account"] == names["unapplied"] and r["credit_minor"]),
        "refund": sum(1 for r in ledger if r["account"] == names["unapplied"] and r["debit_minor"]),
        "invoice_settled_by_several_receipts": sum(1 for n in Counter(r for p in payments for r in p["invoice_refs"]).values() if n > 1),
        "same_customer_same_total": sum(n for n in same_total.values() if n > 1),
        "valid_receipt_in_another_currency": len(crossing),
        "printed_date_is_not_the_local_date": sum(1 for p in crossing if p["timestamp"][:10] != indexed.local_date(p["timestamp"])),
        "valid_invoice_within_a_day_of_a_boundary": sum(
            1 for i in invoices if (i["invoice_id"],) not in flagged
            and min(abs(when(i["issued_at"]) - start), abs(when(i["issued_at"]) - end)) <= timedelta(days=1)),
        "valid_posting_days_late": sum(1 for lag in lags if lag >= timedelta(days=1)),
        "translation_that_multiplies": sum(1 for p in translated if indexed.rate_row(p)["source_currency"] == p["currency"]),
        "translation_that_divides": sum(1 for p in translated if indexed.rate_row(p)["source_currency"] != p["currency"]),
        "receipt_naming_no_invoice": sum(1 for p in payments if not p["invoice_refs"]),
        "identical_invoices_to_two_customers": sum(
            1 for a in invoices for b in invoices if a["invoice_id"] < b["invoice_id"] and a["entity_id"] != b["entity_id"]
            and (when(a["issued_at"]), a["line_items"]) == (when(b["issued_at"]), b["line_items"])),
        "one_customer_one_instant_not_a_duplicate": sum(
            1 for a in invoices for b in invoices if a["invoice_id"] < b["invoice_id"] and a["entity_id"] == b["entity_id"]
            and when(a["issued_at"]) == when(b["issued_at"]) and tuple(sorted((a["invoice_id"], b["invoice_id"]))) not in flagged),
        "valid_posting_before_the_invoice_date": sum(1 for lag in lags if lag < timedelta(0)),
    }  # fmt: skip


def test_every_company_holds_valid_look_alikes_of_every_family(generated) -> None:
    """B8: clean or faulty, each company carries the valid twin of each error, so no error stands out by its shape."""
    counted = {name: _look_alikes(loaded) for name, (loaded, _) in generated.items()}
    for name, kinds in counted.items():
        missing = [kind for kind, count in kinds.items() if count == 0]
        assert not missing, (name, missing)  # every kind in every company, the smallest included
        for needed in ("unapplied_credit", "same_customer_same_total", "valid_receipt_in_another_currency",
                       "valid_invoice_within_a_day_of_a_boundary"):  # fmt: skip
            assert kinds[needed] > 0, (name, needed)
    clean = [name for name in counted if evaluate.EPISODES[name]["status"] == "clean"]
    assert all(sum(counted[name].values()) > 20 for name in clean)  # clean books are full of things that look wrong


def test_no_surface_feature_marks_an_error(generated) -> None:
    """B10: ids, templates, positions, currencies and timestamp formats carry no label."""
    policies = {json.dumps(loaded.public.policy, sort_keys=True) for loaded, _ in generated.values()}
    assert len(policies) == 1  # one policy document for clean and faulty companies alike
    relative_positions = []
    for name, (loaded, provenance) in generated.items():
        public = loaded.public
        ledger = public.tables["ledger"]
        assert public.manifest["issue_types"] == list(families.FAMILIES), name  # never says which families are present
        ids = [r["row_id"] for r in ledger] + [
            r[k] for t in ("invoices", "payments") for r in public.tables[t] for k in ("doc_id",)
        ]
        ids += [r["invoice_id"] for r in public.tables["invoices"]] + [
            r["payment_id"] for r in public.tables["payments"]
        ]
        assert all(ID_TEMPLATE.fullmatch(value) for value in ids), name
        assert all(r["timestamp"][17:19] == "00" for r in ledger), name  # no second-level tell on any row
        assert [when(r["timestamp"]) for r in ledger] == sorted(when(r["timestamp"]) for r in ledger)  # time order
        order = {r["row_id"]: position / len(ledger) for position, r in enumerate(ledger)}
        for issue in loaded.truth:
            relative_positions += [order[e] for e in next(iter(issue.acceptable_evidence_sets)) if e in order]
        accounts_of_errors = {change["record"]["account"] for injection in provenance["injections"]
                              for change in injection["changes"] if change["table"] == "ledger" and "record" in change}  # fmt: skip
        assert accounts_of_errors <= set(families.ACCOUNTS.values())
    assert min(relative_positions) < 0.2 and max(relative_positions) > 0.8  # errors sit all along the ledger
    assert 0.25 < sum(relative_positions) / len(relative_positions) < 0.75
    by_status: dict[str, set[str]] = {"clean": set(), "faulty": set()}
    for _name, (loaded, _) in generated.items():
        by_status["clean" if not loaded.truth else "faulty"].add(loaded.public.manifest["base_currency"])
    assert by_status["clean"] <= by_status["faulty"]  # no base currency is only ever clean


def test_shortcut_baselines_stay_low_on_generated_episodes() -> None:
    """B10: random and flag-all score near the floor; the printed-value shortcut does not pass for a solver."""
    confinement = evaluate.Confinement("none")
    rows = [evaluate.sheet_row(evaluate.run(policy, name, confinement=confinement))
            for policy in ("random_inspector", "flag_all", "reconciliation_naive") for name in evaluate.GENERATED]  # fmt: skip
    summary = {entry["policy"]: entry for entry in evaluate.aggregates([{**row, "split": "generated"} for row in rows])}
    assert summary["random_inspector"]["mean_reward"] == -1.0
    assert summary["flag_all"]["mean_reward"] < -0.9 and summary["flag_all"]["pooled_f1"] < 0.05
    assert summary["reconciliation_naive"]["mean_reward"] < -0.7 and summary["reconciliation_naive"]["pooled_f1"] < 0.2
    assert (
        summary["reconciliation_naive"]["clean_false_positive_rate"] == 1.0
    )  # the look-alikes fool it on every clean company


# ------------------------------------------------------------------------------------- scale


def test_the_largest_episode_fits_the_budget_and_the_envelope(source) -> None:
    """A9: 2,000 rows are readable in full within 100 steps, quickly and in little memory."""
    tracemalloc.start()
    started = time.perf_counter()
    env = AuditEnv(source)
    observation, _ = env.reset(config={"episode": "train_10"})
    assert observation["manifest"]["counts"]["ledger_rows"] >= 1950
    seen, steps = 0, 0
    for table in ("ledger", "invoices", "payments", "fx"):
        cursor = None
        while True:
            observation, reward, terminated, truncated, _ = env.step(
                {"action": "list_records", "args": {"table": table, "cursor": cursor, "limit": 50}})  # fmt: skip
            steps += 1
            assert len(observation["records"]) <= 50 and reward == 0.0 and not terminated and not truncated
            seen += len(observation["records"])
            cursor = observation["next_cursor"]
            if cursor is None:
                break
    counts = (
        observation["manifest"]["counts"]
        if "manifest" in observation
        else env.evaluator_view().public.manifest["counts"]
    )
    assert seen == counts["ledger_rows"] + counts["documents"] + counts["fx_rates"]
    assert steps == families.scan_steps(env.evaluator_view().public) == 47 and observation["steps_remaining"] == 53
    elapsed = time.perf_counter() - started
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert elapsed < 20 and peak < 400 * 2**20  # far inside 60 seconds and 4 GB; exact numbers are in docs/measurements


# ------------------------------------------------ shortcuts the independent checker's author found


def _posting_lags(loaded: Any) -> dict[str, timedelta]:
    indexed = families.index(loaded.public)
    return {i["invoice_id"]: when(families.revenue_row(indexed, i["invoice_id"])["timestamp"]) - when(i["issued_at"])
            for i in loaded.public.tables["invoices"]}  # fmt: skip


def test_the_row_count_does_not_say_whether_the_books_are_clean(generated) -> None:
    """Found by the blind checker: clean books used to land on round row counts and faulty ones did not."""
    last_digit = {"clean": set(), "faulty": set()}
    for loaded, _ in generated.values():
        last_digit["clean" if not loaded.truth else "faulty"].add(loaded.public.manifest["counts"]["ledger_rows"] % 10)
    assert len(last_digit["clean"]) >= 4 and len(last_digit["clean"] & last_digit["faulty"]) >= 3
    counts = [shipped.generate(seed, SMALL, {})[0].manifest["counts"]["ledger_rows"] for seed in range(40, 52)]
    assert len({count % 10 for count in counts}) >= 5 and len(set(counts)) >= 6  # one target, many row counts


def test_a_cutoff_error_has_a_lag_clean_postings_also_have(generated) -> None:
    """Found by the blind checker: half the cutoff errors used to be further from issued_at than any clean posting."""
    clean_lags, error_lags, boundaries = [], [], Counter()
    for loaded, _ in generated.values():
        indexed = families.index(loaded.public)
        flagged = {next(iter(issue.affected_ids)) for issue in loaded.truth if issue.type == "cutoff"}
        for invoice_id, lag in _posting_lags(loaded).items():
            (error_lags if invoice_id in flagged else clean_lags).append(lag)
        for invoice_id in flagged:
            row = families.revenue_row(indexed, invoice_id)
            sides = {indexed.side(row["timestamp"]), indexed.side(indexed.invoices[invoice_id]["issued_at"])}
            boundaries["start" if "before" in sides else "end"] += 1
    assert len(error_lags) == 12
    late, early = timedelta(minutes=world.LATE_LAG), -timedelta(minutes=world.EARLY_LAG)
    assert all(
        early <= lag <= late for lag in error_lags
    )  # the checker's rule "over 6 days late or 3 early" finds none
    assert all(early <= lag <= late for lag in clean_lags)  # and clean postings fill the same range
    days = timedelta(days=1)
    beyond = [lag for lag in clean_lags if lag < min(error_lags) + days or lag > max(error_lags) - days]
    assert len(beyond) > 20  # many clean postings are as far from their invoice date as the most extreme error
    assert (
        sum(1 for lag in clean_lags if lag > timedelta(days=1)) > 40
        and sum(1 for lag in clean_lags if lag < timedelta(0)) > 40
    )
    assert boundaries["start"] >= 3 and boundaries["end"] >= 3  # errors at both ends of the period


def test_two_of_the_five_duplicate_fields_are_not_enough(generated) -> None:
    """Found by the blind checker: "same customer and same issued_at" used to find every duplicate and nothing else."""
    rewritten = 0
    for name, (loaded, _) in generated.items():
        invoices = loaded.public.tables["invoices"]
        groups: dict[tuple[str, Any], list[Any]] = {}
        for invoice in invoices:
            groups.setdefault((invoice["entity_id"], when(invoice["issued_at"])), []).append(invoice)
        shortcut = {tuple(sorted(i["invoice_id"] for i in group)) for group in groups.values() if len(group) > 1}
        truth = {tuple(sorted(issue.affected_ids)) for issue in loaded.truth if issue.type == "duplicate_invoice"}
        assert all(any(set(pair) <= set(group) for group in shortcut) for pair in truth), name
        assert len(shortcut - truth) >= 1, name  # the shortcut also flags valid pairs, in every company
        by_id = {invoice["invoice_id"]: invoice for invoice in invoices}
        rewritten += sum(1 for group in truth if len({by_id[i]["issued_at"] for i in group}) > 1)
    assert rewritten >= 2  # some copies are written at another offset: comparing strings would miss them


def test_allocation_needs_the_open_balance_rule(generated) -> None:
    """Found by the blind checker: an order-free rule used to reproduce every allocation issue. It must not."""
    false_pairs, missed = 0, 0
    for loaded, _ in generated.values():
        public = loaded.public
        indexed = families.index(public)
        credited = Counter()
        for row in public.tables["ledger"]:
            if row["account"] == indexed.names["receivable"] and row["payment_id"]:
                credited[row["invoice_id"]] += row["credit_minor"]
        shortcut = {}
        for payment in public.tables["payments"]:
            unapplied = sum(r["credit_minor"] for r in indexed.rows(payment["payment_id"], "unapplied", "credit_minor"))
            for ref in payment["invoice_refs"]:
                gap = indexed.invoices[ref]["total_minor"] - credited[ref]
                if unapplied and gap > 0:
                    shortcut[tuple(sorted((ref, payment["payment_id"])))] = min(unapplied, gap)
        truth = {tuple(sorted(issue.affected_ids)): issue.expected_amount_minor
                 for issue in loaded.truth if issue.type == "payment_allocation"}  # fmt: skip
        false_pairs += sum(1 for pair, amount in shortcut.items() if truth.get(pair) != amount)
        missed += sum(1 for pair in truth if pair not in shortcut)
    assert false_pairs >= 3, (false_pairs, missed)


def test_some_fx_errors_are_the_printed_date_mistake(generated) -> None:
    sources = [injection["error"]["rate_source"] for _, provenance in generated.values()
               for injection in provenance["injections"] if injection["family"] == "fx_mismatch"]  # fmt: skip
    printed = sum(1 for loaded, provenance in generated.values() for injection in provenance["injections"]
                  if injection["family"] == "fx_mismatch" and injection["error"]["rate_source"] == next(
                      p["timestamp"][:10] for p in loaded.public.tables["payments"]
                      if p["payment_id"] == injection["error"]["payment_id"]))  # fmt: skip
    assert len(sources) == 12 and printed >= 2 and "mistyped" in sources


def test_every_company_has_the_cutoff_look_alike_the_spec_promises(generated) -> None:
    """Found by the blind checker: three companies had no invoice whose printed date is on another side than its instant."""
    for name, (loaded, _) in generated.items():
        indexed = families.index(loaded.public)
        first, last = loaded.public.manifest["period_start"][:10], loaded.public.manifest["period_end"][:10]

        def printed_side(timestamp: str, first: str = first, last: str = last) -> str:
            return "before" if timestamp[:10] < first else "after" if timestamp[:10] > last else "in"

        flagged = {next(iter(issue.affected_ids)) for issue in loaded.truth if issue.type == "cutoff"}
        misleading = [i for i in loaded.public.tables["invoices"] if i["invoice_id"] not in flagged
                      and printed_side(i["issued_at"]) != indexed.side(i["issued_at"])]  # fmt: skip
        assert misleading, name
