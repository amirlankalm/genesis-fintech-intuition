"""Tests ensuring reset output does not reveal episode variant and no row-count rule separates clean from faulty."""

from __future__ import annotations

import json
from typing import Any

import pytest

from genesis_audit import paths
from genesis_audit.env import AuditEnv, DirectorySource


def _load_shipped_data() -> list[dict[str, Any]]:
    source = DirectorySource(paths.PUBLIC_ROOT, paths.PRIVATE_ROOT)
    episodes = sorted([p.name for p in paths.PUBLIC_ROOT.iterdir() if p.is_dir()])
    records = []
    for name in episodes:
        env = AuditEnv(source)
        obs, info = env.reset(0, {"episode": name, "mode": "eval"})
        truth_file = paths.PRIVATE_ROOT / name / "truth.json"
        truth = json.loads(truth_file.read_text()) if truth_file.exists() else {"issues": []}
        is_faulty = len(truth["issues"]) > 0
        c = obs["manifest"]["counts"]
        records.append(
            {
                "name": name,
                "obs": obs,
                "info": info,
                "ledger_rows": c["ledger_rows"],
                "documents": c["documents"],
                "fx_rates": c["fx_rates"],
                "is_faulty": is_faulty,
            }
        )
    return records


def test_reset_output_does_not_reveal_variant_or_clean_status() -> None:
    """A8/B10: reset observation and info contain no label, variant tag, or secret."""
    records = _load_shipped_data()
    assert len(records) == 31

    for rec in records:
        obs = rec["obs"]
        info = rec["info"]

        # In eval/closed mode, info is strictly empty
        assert info == {}, f"{rec['name']} leaked non-empty info at reset: {info}"

        # Manifest contains standard keys only
        manifest = obs["manifest"]
        assert "schema_version" in manifest
        assert "episode_id" in manifest
        assert manifest["episode_id"].startswith("ep-")
        # No label leaks in manifest
        assert "label" not in manifest
        assert "is_clean" not in manifest
        assert "variant" not in manifest
        assert "truth" not in manifest

        # Issue types are defined by policy scope (case episodes declare all 4, teaching declares 1);
        # clean and faulty share identical issue_types without revealing status.
        assert set(manifest["issue_types"]) in (
            {"duplicate_invoice", "payment_allocation", "fx_mismatch", "cutoff"},
            {"payment_allocation"},
        )

        # Step remaining is the standard max_steps
        assert obs["steps_remaining"] == 100


@pytest.mark.parametrize(
    ("clean_name", "clean_rows", "faulty_name", "faulty_rows"),
    [
        ("train_01", 208, "train_02", 209),
        ("dev_03", 445, "dev_04", 447),
    ],
)
def test_twin_pairs_reset_visible_row_counts_overlap_global_distribution(
    clean_name: str, clean_rows: int, faulty_name: str, faulty_rows: int
) -> None:
    """Paired clean/faulty twins show their row counts on reset (208/209 and 445/447),
    and their values sit well inside the overlapping clean and faulty global distributions."""
    records = _load_shipped_data()
    clean_distribution = {r["ledger_rows"] for r in records if not r["is_faulty"]}
    faulty_distribution = {r["ledger_rows"] for r in records if r["is_faulty"]}

    clean_rec = next(r for r in records if r["name"] == clean_name)
    faulty_rec = next(r for r in records if r["name"] == faulty_name)

    assert clean_rec["ledger_rows"] == clean_rows
    assert faulty_rec["ledger_rows"] == faulty_rows

    # Both values lie strictly within the clean and faulty range envelopes
    min_clean, max_clean = min(clean_distribution), max(clean_distribution)
    min_faulty, max_faulty = min(faulty_distribution), max(faulty_distribution)

    assert min_clean <= clean_rows <= max_clean
    assert min_clean <= faulty_rows <= max_clean
    assert min_faulty <= clean_rows <= max_faulty
    assert min_faulty <= faulty_rows <= max_faulty


def test_no_row_count_rule_separates_clean_from_faulty_across_shipped_episodes() -> None:
    """Fails if any simple row-count rule (threshold, parity, modulo, exact match)
    separates clean from faulty across all 31 shipped episodes."""
    records = _load_shipped_data()
    clean = [r for r in records if not r["is_faulty"]]
    faulty = [r for r in records if r["is_faulty"]]

    clean_rows = [r["ledger_rows"] for r in clean]
    faulty_rows = [r["ledger_rows"] for r in faulty]

    # 1. Clean and faulty count ranges overlap
    assert min(clean_rows) <= min(faulty_rows) <= max(clean_rows)
    assert min(faulty_rows) <= max(clean_rows) <= max(faulty_rows)

    # 2. Exact identical count collisions exist in both clean and faulty sets
    collisions = set(clean_rows) & set(faulty_rows)
    assert {12, 45} <= collisions, f"Expected 12 and 45 to collide, got: {collisions}"

    # Exact tuple collisions: (ledger_rows, documents, fx_rates)
    clean_tuples = {(r["ledger_rows"], r["documents"], r["fx_rates"]) for r in clean}
    faulty_tuples = {(r["ledger_rows"], r["documents"], r["fx_rates"]) for r in faulty}
    tuple_collisions = clean_tuples & faulty_tuples
    assert (12, 5, 3) in tuple_collisions
    assert (45, 17, 4) in tuple_collisions

    # 3. No threshold rule on ledger_rows separates clean from faulty
    all_rows = clean_rows + faulty_rows
    actual = [r["is_faulty"] for r in records]
    for t in range(min(all_rows) - 1, max(all_rows) + 2):
        pred_gt = [r["ledger_rows"] > t for r in records]
        pred_gte = [r["ledger_rows"] >= t for r in records]
        # Must not separate perfectly
        assert pred_gt != actual and [not p for p in pred_gt] != actual, f"Threshold > {t} separated clean from faulty!"
        assert pred_gte != actual and [not p for p in pred_gte] != actual, (
            f"Threshold >= {t} separated clean from faulty!"
        )

    # 4. No parity rule separates clean from faulty
    pred_even = [r["ledger_rows"] % 2 == 0 for r in records]
    assert pred_even != actual and [not p for p in pred_even] != actual, "Parity separated clean from faulty!"

    # 5. No modulo rule (k in 2..50) separates clean from faulty
    for k in range(2, 51):
        for rem in range(k):
            pred_mod = [r["ledger_rows"] % k == rem for r in records]
            assert pred_mod != actual and [not p for p in pred_mod] != actual, (
                f"Modulo {k}=={rem} separated clean from faulty!"
            )

    # 6. No threshold rule on documents or fx_rates separates clean from faulty
    for feat in ("documents", "fx_rates"):
        vals = [r[feat] for r in records]
        for t in range(min(vals) - 1, max(vals) + 2):
            pred_gt = [r[feat] > t for r in records]
            assert pred_gt != actual and [not p for p in pred_gt] != actual, (
                f"Threshold on {feat} > {t} separated clean from faulty!"
            )
