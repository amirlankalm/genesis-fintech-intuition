"""Jury fixtures. Everything is built through judge_adapter.generate_episode plus the jury's own files."""

from __future__ import annotations

import copy
import os
import sys
import tempfile
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

# Hidden-seed practice (ADAPTER.md section 2): ids are keyed by the evaluator secret the jury holds.
# The secret is set only while the jury's tests run and restored afterwards, so it cannot leak into other tests.
_secret_dir = tempfile.mkdtemp(prefix="jury-secret-")
_secret_file = os.path.join(_secret_dir, "secret.bin")
with open(_secret_file, "wb") as _fh:
    _fh.write(b"genesis-jury-secret-2026-11-20-not-the-team-dev-key")


@pytest.fixture(scope="package", autouse=True)
def jury_secret():
    previous = os.environ.get("GENESIS_AUDIT_SECRET_FILE")
    os.environ["GENESIS_AUDIT_SECRET_FILE"] = _secret_file
    yield _secret_file
    if previous is None:
        os.environ.pop("GENESIS_AUDIT_SECRET_FILE", None)
    else:
        os.environ["GENESIS_AUDIT_SECRET_FILE"] = previous


from jury_cases import D_CASES, SEED_BASE, generate_with_seed_search  # noqa: E402
from jury_checks import _digest  # noqa: E402
from jury_data import choose_unknown_id, read_episode, write_episode  # noqa: E402

import judge_adapter  # noqa: E402


@pytest.fixture(scope="package")
def jury_root(tmp_path_factory, jury_secret) -> Path:
    return tmp_path_factory.mktemp("jury")


def _gen(root: Path, name: str, seed: int, config: dict) -> dict:
    d = str(root / name)
    Path(d).parent.mkdir(parents=True, exist_ok=True)
    used, _ = generate_with_seed_search(seed, config, d)
    return {"dir": d, "seed": used, "config": config, "ep": read_episode(d)}


@pytest.fixture(scope="package")
def fx_C(jury_root) -> dict:
    """C: clean, R1 = an existing ledger row, D1 = an existing invoice document."""
    c = _gen(jury_root, "C", 7_320_101, {"generator": {"invoices": 24, "ledger_rows": 260}})
    ep = c["ep"]
    c["R1"] = ep["ledger"][17]["row_id"]
    c["D1"] = ep["invoices"][5]["doc_id"]
    c["U"] = choose_unknown_id(ep, "U")
    return c


@pytest.fixture(scope="package")
def fx_E(jury_root) -> dict:
    """E: one declared error with a full accessible evidence set."""
    e = _gen(jury_root, "E", 7_320_201, {"generator": {"ledger_rows": 240, "invoices": 20}, "inject": {"cutoff": 1}})
    e["U"] = choose_unknown_id(e["ep"], "U")
    return e


@pytest.fixture(scope="package")
def fx_L(jury_root) -> dict:
    """L: ledger of >= 101 rows (and invoices >= 101 documents) to walk three or more pages."""
    l_ = _gen(jury_root, "L", 7_320_301, {"generator": {"invoices": 110, "ledger_rows": 640}})
    assert len(l_["ep"]["ledger"]) >= 101 and len(l_["ep"]["invoices"]) >= 101
    return l_


@pytest.fixture(scope="package")
def d_episodes(jury_root) -> dict:
    out = {}
    for i, (name, case) in enumerate(D_CASES.items()):
        g = _gen(jury_root / "D", name, SEED_BASE + 100 * (i + 1), case["config"])
        g["case"] = case
        g["digest"] = _digest(g["dir"])
        out[name] = g
    return out


# ------------------------------------------------------------------------------------------- Block 3
@pytest.fixture(scope="package")
def b3(jury_root) -> dict:
    """The shared matcher fixture: generated company, the jury's own truth.json, tau = 0 in the manifest."""
    base = _gen(jury_root, "B3_base", 7_320_401, {"generator": {"base_currency": "KZT", "foreign_currencies": ["USD"]}})
    ep = base["ep"]
    kzt = [d for d in ep["invoices"] if d["currency"] == "KZT"]
    R = [d["invoice_id"] for d in kzt[:5]]
    docs = {d["invoice_id"]: d["doc_id"] for d in kzt[:5]}
    rev = {
        r["invoice_id"]: r["row_id"]
        for r in ep["ledger"]
        if r["invoice_id"] in docs and r["payment_id"] is None and r["account"] == "revenue"
    }
    U = choose_unknown_id(ep, "U")
    fx = {"R": R, "docs": docs, "rev": rev, "U": U, "dirs": {}}

    def issue(iid: str, typ: str, affected: list, amount: int, sets: list) -> dict:
        return {
            "issue_id": iid,
            "type": typ,
            "affected_ids": affected,
            "expected_amount_minor": amount,
            "currency": "KZT",
            "acceptable_evidence_sets": sets,
        }

    def make(name: str, issues: list, tau: int = 0, shrink: bool = False) -> str:
        e = copy.deepcopy(ep)
        e["truth"] = {"issues": issues}
        e["manifest"]["amount_tolerance_minor"] = dict(e["manifest"]["amount_tolerance_minor"], KZT=tau)
        if shrink:  # five records: R1..R5 with their own postings only
            keep = set(R)
            e["invoices"] = [d for d in e["invoices"] if d["invoice_id"] in keep]
            e["ledger"] = [r for r in e["ledger"] if r["invoice_id"] in keep and r["payment_id"] is None]
            e["payments"] = []
            e["fx"] = e["fx"][:1]
            e["manifest"]["counts"] = {"ledger_rows": len(e["ledger"]), "documents": len(e["invoices"]), "fx_rates": 1}
        e["provenance"] = None
        d = str(jury_root / f"B3_{name}")
        write_episode(d, e)
        fx["dirs"][name] = d
        return d

    R1, R2, R3 = R[0], R[1], R[2]
    D1, D2 = docs[R1], rev[R1]
    fx.update(R1=R1, R2=R2, R3=R3, D1=D1, D2=D2)
    A = issue("A", "cutoff", [R1], 10000, [[D1, D2]])
    B = issue("B", "cutoff", [R2], 20000, [[docs[R2], rev[R2]]])
    make("A", [A])
    make("empty", [])
    make("AB", [A, B])
    make("five", [A], shrink=True)
    # M01-M12: A has affected {R1, R2}, evidence {D1, D2}; D3 an existing extra document
    MD1, MD2, MD3 = docs[R1], docs[R2], docs[R3]
    fx.update(MD1=MD1, MD2=MD2, MD3=MD3)
    MA = issue("A", "duplicate_invoice", [R1, R2], 10000, [[MD1, MD2]])
    make("M", [MA])
    make("M_tau1", [MA], tau=1)
    make("M10", [MA, issue("B", "duplicate_invoice", [R1, R2], 10000, [[MD3]])])
    make("M11", [MA, issue("B", "duplicate_invoice", [R1, R2], 10000, [[MD1, MD2]])])
    fx["ep"] = ep
    return fx


@pytest.fixture
def adapter():
    return judge_adapter
