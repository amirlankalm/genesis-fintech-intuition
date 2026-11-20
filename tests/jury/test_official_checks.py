"""Jury conformance suite for the Genesis FinTech official check definitions (2026-11-20).

Spec: docs/reference/fintech-checks-2026-11-20.md. Transport: judge_adapter only (generate_episode, make_env,
score_episode; JudgeEnv(clock=...) and evaluator_report() are the adapter's documented jury-side hooks).

Block 1  C01-C20  contract and isolation, fixtures C, E, L, U
Block 2  D01-D20  closed episodes, each checked by the jury's own reconciliation (jury_recon.py)
Block 3  T01-T20  matcher and reward on hand-written truth fixtures; M01-M12 the open matcher examples
Block 4  P01-P20  paired permutation / id-renaming checks with the jury's own transformer (jury_transform.py)
"""

from __future__ import annotations

import json
import logging
import os
from decimal import Decimal
from fractions import Fraction
from zoneinfo import ZoneInfo

import pytest
from jury_cases import D_CASES
from jury_checks import check_d, check_formats, check_p
from jury_data import fx_key, read_episode
from jury_play import Run, act, list_all, oracle_from_truth, public_view, roundtrips
from jury_recon import parse_ts

import judge_adapter

TOL = 1e-9
SECRET_KEYS = {
    "issue_id",
    "acceptable_evidence_sets",
    "expected_amount_minor",
    "injections",
    "causal_note",
    "canary",
    "provenance",
    "truth",
    "seed",
    "issues",
}


def all_keys(value, out=None) -> set:
    out = set() if out is None else out
    if isinstance(value, dict):
        for k, v in value.items():
            out.add(k)
            all_keys(v, out)
    elif isinstance(value, list):
        for v in value:
            all_keys(v, out)
    return out


def all_strings(value, out=None) -> set:
    out = set() if out is None else out
    if isinstance(value, str):
        out.add(value)
    elif isinstance(value, dict):
        for v in value.values():
            all_strings(v, out)
    elif isinstance(value, list):
        for v in value:
            all_strings(v, out)
    return out


def secrets_of(ep: dict) -> set:
    s = {i["issue_id"] for i in ep["truth"]["issues"]}
    prov = ep.get("provenance") or {}
    if prov.get("canary"):
        s.add(prov["canary"])
    for inj in prov.get("injections", []):
        if inj.get("causal_note"):
            s.add(inj["causal_note"])
    return s


# ======================================================================================== Block 1
def test_C01_reset_pair_json(fx_C):
    env = judge_adapter.make_env()
    out = env.reset(0, {"mode": "closed", "episode_dir": fx_C["dir"], "team_config": {}})
    assert isinstance(out, tuple) and len(out) == 2, f"reset returned {type(out)} of length {len(out)}"
    obs, info = out
    assert isinstance(obs, dict) and isinstance(info, dict)
    assert roundtrips(obs) and roundtrips(info), "reset values are not JSON-compatible"
    for a in (
        act("list_records", table="ledger", cursor=None, limit=3),
        act("get_record", table="ledger", id=fx_C["R1"]),
        act("get_document", doc_id=fx_C["D1"]),
        act("calculator", expression="2/3"),
        act("get_record", table="ledger", id=fx_C["U"]),
        act("submit", findings={"findings": []}),
        act("list_records", table="fx", cursor=None),
    ):
        o, r, term, trunc, inf = env.step(a)
        assert roundtrips(o) and roundtrips(r) and roundtrips(inf), f"non-JSON exchange after {a['name']}"


def test_C02_first_observation(fx_C, fx_E):
    for fx in (fx_C, fx_E):
        env = judge_adapter.make_env()
        obs, info = env.reset(4815162342, {"mode": "closed", "episode_dir": fx["dir"], "team_config": {}})
        assert set(obs) == {"task", "manifest", "policy", "remaining_steps"}, sorted(obs)
        assert isinstance(obs["task"], str) and obs["task"]
        assert isinstance(obs["manifest"], dict) and isinstance(obs["policy"], dict) and obs["policy"]
        assert obs["remaining_steps"] == 100
        text = json.dumps([obs, info])
        assert "4815162342" not in text, "seed leaks into the first observation"
        assert not (all_keys([obs, info]) & SECRET_KEYS), all_keys([obs, info]) & SECRET_KEYS
        leaked = all_strings([obs, info]) & secrets_of(fx["ep"])
        assert not leaked, f"closed values in first observation: {leaked}"
    # train mode generated from (seed, team_config): still no seed / answer key
    env = judge_adapter.make_env()
    obs, info = env.reset(4815162342, {"mode": "train", "team_config": {"inject": {"cutoff": 1}}})
    assert "4815162342" not in json.dumps([obs, info])
    assert not (all_keys(obs) & SECRET_KEYS)


def test_C03_manifest_matches_data(fx_C):
    view, run = public_view(fx_C["dir"])
    m = run.first_obs["manifest"]
    for k in (
        "schema_version",
        "episode_id",
        "base_currency",
        "period_start",
        "period_end",
        "timezone",
        "counts",
        "rounding",
    ):
        assert k in m, f"manifest lacks {k}"
    assert m["episode_id"] == fx_C["ep"]["manifest"]["episode_id"]
    ps, pe = parse_ts(m["period_start"]), parse_ts(m["period_end"])
    assert ps < pe
    assert ZoneInfo(m["timezone"]).utcoffset(ps.replace(tzinfo=None)) == ps.utcoffset(), "timezone vs offset"
    c = m["counts"]
    assert c["ledger_rows"] == len(view["ledger"]), (c, len(view["ledger"]))
    assert c["documents"] == len(view["invoices"]) + len(view["payments"])
    assert c["fx_rates"] == len(view["fx"])
    assert m["base_currency"] in m["currencies"]
    used = {r["currency"] for r in view["ledger"]} | {d["currency"] for d in view["invoices"] + view["payments"]}
    assert used <= set(m["currencies"]), used - set(m["currencies"])
    assert isinstance(m["rounding"], dict) and m["rounding"]
    assert not check_formats(view, m)


def test_C04_step_contract(fx_C):
    run = Run()
    run.reset(fx_C["dir"])
    out = run.env.step(act("list_records", table="invoices", cursor=None, limit=10))
    assert isinstance(out, tuple) and len(out) == 5
    obs, reward, term, trunc, info = out
    assert type(term) is bool and type(trunc) is bool
    assert isinstance(reward, (int, float)) and not isinstance(reward, bool)
    assert roundtrips(obs) and roundtrips(info)
    assert obs["remaining_steps"] == 99 and isinstance(obs["result"]["records"], list)


def test_C05_pagination_complete(fx_L):
    run = Run()
    run.reset(fx_L["dir"])
    for table in ("ledger", "invoices"):
        records, pages = list_all(run, table, limit=50)
        assert len(pages) >= 3
        assert all(len(p) <= 50 for p in pages)
        file_rows = fx_L["ep"][table]
        key = "row_id" if table == "ledger" else "doc_id"
        ids = [r[key] for r in records]
        assert len(ids) == len(set(ids)), f"{table}: repeated records across pages"
        assert sorted(json.dumps(r, sort_keys=True) for r in records) == sorted(
            json.dumps(r, sort_keys=True) for r in file_rows
        ), f"{table}: some rows unreachable"


def test_C06_same_cursor_same_page(fx_L):
    run = Run()
    run.reset(fx_L["dir"])
    o1, *_ = run.step(act("list_records", table="ledger", cursor=None, limit=50))
    cur = o1["result"]["next_cursor"]
    a, *_ = run.step(act("list_records", table="ledger", cursor=cur, limit=50))
    run.step(act("get_record", table="ledger", id=fx_L["ep"]["ledger"][0]["row_id"]))
    b, *_ = run.step(act("list_records", table="ledger", cursor=cur, limit=50))
    assert a["result"] == b["result"], "the same cursor returned a different page"
    assert a["remaining_steps"] - 2 == b["remaining_steps"]


def test_C07_get_record_R1(fx_C):
    run = Run()
    run.reset(fx_C["dir"])
    ep = fx_C["ep"]
    want = next(r for r in ep["ledger"] if r["row_id"] == fx_C["R1"])
    obs, *_ = run.step(act("get_record", table="ledger", id=fx_C["R1"]))
    assert obs["error"] is None and obs["result"] == want, obs
    inv = ep["invoices"][2]
    obs, *_ = run.step(act("get_record", table="invoices", id=inv["invoice_id"]))
    assert obs["result"] == inv
    pay = ep["payments"][0]
    obs, *_ = run.step(act("get_record", table="payments", id=pay["payment_id"]))
    assert obs["result"] == pay
    fxr = ep["fx"][0]
    obs, *_ = run.step(act("get_record", table="fx", id=fx_key(fxr)))
    assert obs["result"] == fxr
    assert set(obs) == {"result", "error", "remaining_steps"}


def test_C08_get_document_D1_no_files(fx_C):
    run = Run()
    run.reset(fx_C["dir"])
    want = next(d for d in fx_C["ep"]["invoices"] if d["doc_id"] == fx_C["D1"])
    obs, *_ = run.step(act("get_document", doc_id=fx_C["D1"]))
    assert obs["error"] is None and obs["result"] == want
    for bad in (
        "truth.json",
        "../truth.json",
        "/etc/passwd",
        "invoices.jsonl",
        "provenance.json",
        os.path.join(fx_C["dir"], "truth.json"),
        "file:///etc/hosts",
        ".",
    ):
        obs, *_ = run.step(act("get_document", doc_id=bad))
        assert obs["result"] is None and obs["error"] is not None, f"get_document({bad!r}) returned {obs}"


def test_C09_calculator_decimal(fx_C):
    run = Run()
    run.reset(fx_C["dir"])
    obs, *_ = run.step(act("calculator", expression="0.1+0.2"))
    assert obs["error"] is None and Decimal(str(obs["result"])) == Decimal("0.3"), obs


def test_C10_calculator_no_code(fx_C, tmp_path):
    marker = tmp_path / "pwned"
    run = Run()
    run.reset(fx_C["dir"])
    exprs = [
        f"__import__('os').system('touch {marker}')",
        "open('/etc/passwd').read()",
        f"open('{fx_C['dir']}/truth.json').read()",
        "1+1; import os",
        "`cat /etc/passwd`",
        "$(cat truth.json)",
        "eval('1+1')",
        "(lambda: 1)()",
        "[].__class__",
        "2**10000000",
        "a+1",
        "http://example.com",
    ]
    for e in exprs:
        obs, *_ = run.step(act("calculator", expression=e))
        assert obs["error"] is not None and obs["result"] is None, f"calculator accepted {e!r}: {obs}"
        text = json.dumps(obs)
        assert "root:" not in text and "issues" not in text
    assert not marker.exists(), "calculator executed code"


def test_C11_get_record_unknown(fx_C):
    run = Run()
    run.reset(fx_C["dir"])
    rem = 100
    for table in ("ledger", "invoices", "payments", "fx"):
        obs, r, term, trunc, info = run.step(act("get_record", table=table, id=fx_C["U"]))
        rem -= 1
        assert obs["result"] is None and obs["error"] is not None and obs["remaining_steps"] == rem
        assert not term and not trunc
    obs, *_ = run.step(act("get_record", table="ledger", id=fx_C["R1"]))
    assert obs["error"] is None and obs["result"]["row_id"] == fx_C["R1"]


def test_C12_get_document_unknown(fx_C):
    run = Run()
    run.reset(fx_C["dir"])
    obs, r, term, trunc, info = run.step(act("get_document", doc_id=fx_C["U"]))
    assert obs["result"] is None and obs["error"] is not None and obs["remaining_steps"] == 99
    assert not term and not trunc
    doc_ids = {d["doc_id"] for d in fx_C["ep"]["invoices"] + fx_C["ep"]["payments"]}
    assert not (all_strings(obs) & doc_ids), "error discloses other documents"


def test_C13_unknown_action(fx_C):
    run = Run()
    run.reset(fx_C["dir"])
    for i, a in enumerate(
        (
            {"name": "rm_rf", "args": {}},
            {"name": "read_file", "args": {"path": "/etc/passwd"}},
            {"name": "sql", "args": {"query": "select * from truth"}},
        ),
        start=1,
    ):
        obs, r, term, trunc, info = run.step(a)
        assert obs["error"] is not None and obs["result"] is None and obs["remaining_steps"] == 100 - i
        assert not term and not trunc


def test_C14_error_costs_a_step(fx_C):
    run = Run()
    run.reset(fx_C["dir"])
    a, *_ = run.step(act("get_record", table="ledger", id=fx_C["R1"]))
    e, *_ = run.step(act("get_record", table="ledger", id=fx_C["U"]))
    b, *_ = run.step(act("get_record", table="ledger", id=fx_C["R1"]))
    assert (a["remaining_steps"], e["remaining_steps"], b["remaining_steps"]) == (99, 98, 97)
    assert e["error"] is not None and a["result"] == b["result"] and b["error"] is None


def _report_core(rep: dict) -> dict:
    return {
        k: rep.get(k)
        for k in (
            "score",
            "counts",
            "findings",
            "termination_cause",
            "inspection_steps",
            "unmatched_issue_ids",
            "submitted",
            "valid_submission",
        )
    }


def test_C15_submit_is_final(fx_E):
    run = Run()
    run.reset(fx_E["dir"])
    run.step(act("get_record", table="ledger", id=fx_E["ep"]["ledger"][0]["row_id"]))
    oracle = oracle_from_truth(fx_E["ep"]["truth"])
    obs, r, term, trunc, info = run.step(act("submit", findings=oracle))
    assert term is True and obs["result"] == {"accepted": True}
    before = _report_core(run.env.evaluator_report())
    assert before["counts"]["tp"] == 1
    for a in (
        act("list_records", table="ledger", cursor=None),
        act("submit", findings={"findings": []}),
        act("submit", findings=oracle),
        act("get_record", table="ledger", id=fx_E["U"]),
    ):
        o, *_ = run.step(a)
        assert o.get("result") in (None,) or o["result"] != {"accepted": True}, f"post-end {a['name']} accepted"
    assert _report_core(run.env.evaluator_report()) == before, "post-end actions changed the recorded result"


def test_C16_submit_on_action_100(fx_E):
    run = Run()
    run.reset(fx_E["dir"])
    rows = fx_E["ep"]["ledger"]
    for i in range(99):
        a = (
            act("get_record", table="ledger", id=rows[i % len(rows)]["row_id"])
            if i % 7
            else act("get_record", table="ledger", id=fx_E["U"])
        )
        o, r, term, trunc, info = run.step(a)
        assert not term and not trunc, f"episode ended early at step {i + 1}"
    oracle = oracle_from_truth(fx_E["ep"]["truth"])
    obs, r, term, trunc, info = run.step(act("submit", findings=oracle))
    assert obs["result"] == {"accepted": True} and term is True and trunc is False and obs["remaining_steps"] == 0
    rep = run.env.evaluator_report()
    assert rep["inspection_steps"] == 99 and rep["counts"]["tp"] == 1
    s = judge_adapter.score_episode(fx_E["dir"], oracle, 99)
    assert abs(s["return"] - (1 - 0.002 * 99)) <= TOL


def test_C17_100_inspections_truncate(fx_E):
    run = Run()
    run.reset(fx_E["dir"])
    for i in range(100):
        o, r, term, trunc, info = run.step(act("calculator", expression=f"{i}+1"))
        if i < 99:
            assert not term and not trunc
    assert trunc is True, "100 inspections did not truncate"
    rep_before = _report_core(run.env.evaluator_report())
    o, *_ = run.step(act("submit", findings=oracle_from_truth(fx_E["ep"]["truth"])))
    assert o["result"] != {"accepted": True}
    rep = run.env.evaluator_report()
    assert _report_core(rep) == rep_before
    assert (rep["counts"]["tp"], rep["counts"]["fp"], rep["counts"]["fn"]) == (0, 0, 1), rep["counts"]


class FakeClock:
    def __init__(self, t: float = 1000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t


def _timeout_run(fx_E) -> tuple:
    clock = FakeClock()
    env = judge_adapter.JudgeEnv(clock=clock)
    run = Run(env)
    run.reset(fx_E["dir"])
    clock.t += 10
    o1 = run.step(act("get_record", table="ledger", id=fx_E["ep"]["ledger"][0]["row_id"]))
    clock.t += 50.5  # the policy "thinks" past the 60 s window that opened at reset
    o2 = run.step(act("submit", findings=oracle_from_truth(fx_E["ep"]["truth"])))
    o3 = run.step(act("submit", findings=oracle_from_truth(fx_E["ep"]["truth"])))
    return run, o1, o2, o3


def test_C18_time_limit(fx_E):
    run, o1, o2, o3 = _timeout_run(fx_E)
    assert o1[3] is False and o1[1] is not None
    obs, r, term, trunc, info = o2
    assert trunc is True, f"60 s exceeded but truncated={trunc}"
    assert obs["result"] != {"accepted": True}, "a submit after the time limit was executed"
    assert o3[0]["result"] != {"accepted": True}
    rep = run.env.evaluator_report()
    assert (rep["counts"]["tp"], rep["counts"]["fp"], rep["counts"]["fn"]) == (0, 0, 1)
    run2, *_ = _timeout_run(fx_E)
    assert [t[1:] for t in run.transcript] == [t[1:] for t in run2.transcript], "time-limit scenario not reproducible"


def test_C19_closed_rewards_hidden(fx_E):
    run = Run()
    run.reset(fx_E["dir"])
    assert run.reset_info == {}
    rows = fx_E["ep"]["ledger"]
    for i in range(3):
        o, r, term, trunc, info = run.step(act("get_record", table="ledger", id=rows[i]["row_id"]))
        assert isinstance(r, (int, float)) and not isinstance(r, bool) and r == 0 and info == {}
    oracle = oracle_from_truth(fx_E["ep"]["truth"])
    o, r, term, trunc, info = run.step(act("submit", findings=oracle))
    assert r == 0 and isinstance(r, (int, float)) and info == {}
    assert o == {"result": {"accepted": True}, "error": None, "remaining_steps": 96}
    s = judge_adapter.score_episode(fx_E["dir"], oracle, 3)
    assert s["tp"] == 1 and abs(s["return"] - 0.994) <= TOL
    rep = run.env.evaluator_report()
    assert rep["counts"]["tp"] == 1 and abs(rep["score"]["reward"] - 0.994) <= TOL
    # the same episode in train mode returns the true terminal reward (separation of modes)
    tr = Run()
    tr.reset(fx_E["dir"], mode="train")
    for i in range(3):
        tr.step(act("get_record", table="ledger", id=rows[i]["row_id"]))
    _, r_train, *_ = tr.step(act("submit", findings=oracle))
    assert abs(r_train - 0.994) <= TOL


def _probe_actions(fx) -> list:
    d = fx["dir"]
    return [
        act("get_record", table="truth", id="A"),
        act("get_record", table="provenance", id="x"),
        act("list_records", table="manifest", cursor=None),
        act("list_records", table="../truth.json", cursor=None),
        act("get_record", table="ledger", id="' OR '1'='1"),
        act("get_record", table="ledger", id="*"),
        act("get_record", table="ledger", id="../../truth.json"),
        act("get_document", doc_id=f"{d}/truth.json"),
        act("get_document", doc_id="http://127.0.0.1:80/"),
        act("list_records", table="ledger", cursor="../../x"),
        act("list_records", table="ledger", cursor="ledger:-1"),
        act("list_records", table="ledger", cursor="ledger:99999"),
        act("list_records", table="ledger", cursor=None, limit=51),
        act("list_records", table="ledger", cursor=None, limit=0),
        act("get_record", table="ledger", id=fx["ep"]["ledger"][0]["row_id"], path="/etc/passwd"),
        act("calculator", expression="__import__('subprocess').run('ls')"),
        {"name": "get_record"},
        {"action": "get_record", "args": {}},
        "not-an-object",
        act("calculator", expression="1/0"),
        act("calculator", expression="(" * 500 + "1" + ")" * 500),
    ]


def test_C20_no_leak_anywhere(fx_C, fx_E):
    for fx in (fx_C, fx_E):
        ep = fx["ep"]
        everything = []
        actions = [act("list_records", table=t, cursor=None) for t in ("ledger", "invoices", "payments", "fx")]
        actions += [act("get_document", doc_id=d["doc_id"]) for d in ep["invoices"] + ep["payments"]]
        actions += [act("get_record", table="invoices", id=d["invoice_id"]) for d in ep["invoices"]]
        actions += [act("get_record", table="payments", id=d["payment_id"]) for d in ep["payments"]]
        actions += [act("get_record", table="fx", id=fx_key(r)) for r in ep["fx"]]
        actions += [act("get_record", table="ledger", id=r["row_id"]) for r in ep["ledger"]]
        actions += _probe_actions(fx)
        for i in range(0, len(actions), 90):
            run = Run()
            run.reset(fx["dir"], seed=31337)
            everything.append(run.first_obs)
            assert run.reset_info == {}
            for a in actions[i : i + 90]:
                o, r, term, trunc, info = run.step(a)
                assert info == {} and r == 0, f"info/reward leak on {a}"
                everything.append(o)
                if o["error"] is not None:
                    assert o["error"]["code"] in judge_adapter.PUBLIC_ERROR_CODES
                    assert o["result"] is None
            # a list_records that pages fully, so every record is seen
        for t in ("ledger", "invoices", "payments", "fx"):
            run = Run()
            run.reset(fx["dir"])
            recs, _ = list_all(run, t)
            everything.append(recs)
        keys = all_keys(everything)
        assert not (keys & SECRET_KEYS), f"closed keys visible to the policy: {keys & SECRET_KEYS}"
        strings = all_strings(everything)
        assert not (strings & secrets_of(ep)), f"closed values visible: {strings & secrets_of(ep)}"
        blob = json.dumps(everything)
        for needle in (
            fx["dir"],
            os.path.dirname(fx["dir"]),
            "root:x:0",
            "Traceback",
            "/Users/",
            "truth.json",
            "provenance.json",
        ):
            assert needle not in blob, f"{needle!r} reached the policy channel"


# ======================================================================================== Block 2
@pytest.mark.parametrize("name", list(D_CASES))
def test_D(name, d_episodes):
    info = d_episodes[name]
    fails = check_d(
        name, info["case"], info["dir"], {k: {"case": v["case"], "ep": v["ep"]} for k, v in d_episodes.items()}
    )
    assert not fails, f"{name} ({info['case']['scenario']}, seed {info['seed']}): " + "; ".join(fails)


# ======================================================================================== Block 3
def _F(b3, **over) -> dict:
    f = {
        "type": "cutoff",
        "affected_ids": [b3["R1"]],
        "claimed_amount_minor": 10000,
        "currency": "KZT",
        "evidence_ids": [b3["D1"], b3["D2"]],
        "explanation": "revenue posted on the wrong side",
    }
    f.update(over)
    return f


def _MF(b3, **over) -> dict:
    f = {
        "type": "duplicate_invoice",
        "affected_ids": [b3["R1"], b3["R2"]],
        "claimed_amount_minor": 10000,
        "currency": "KZT",
        "evidence_ids": [b3["MD1"], b3["MD2"]],
        "explanation": "same obligation twice",
    }
    f.update(over)
    return f


def _score(b3, name: str, findings: list | dict, steps: int = 10) -> dict:
    doc = findings if isinstance(findings, dict) else {"findings": findings}
    return judge_adapter.score_episode(b3["dirs"][name], doc, steps)


def _expect(s: dict, tp, fp, fn, p, r, f1, ret):
    got = (s["tp"], s["fp"], s["fn"])
    assert got == (tp, fp, fn), f"TP/FP/FN {got} != {(tp, fp, fn)} ({s})"
    for k, v in (("precision", p), ("recall", r), ("f1", f1), ("return", ret)):
        assert s[k] is not None and abs(s[k] - float(v)) <= TOL, f"{k} {s[k]} != {float(v)} ({s})"


def _invalid(s: dict):
    assert s["return"] == -1, s
    assert all(s[k] is None for k in ("tp", "fp", "fn", "precision", "recall", "f1")), s


def test_T01(b3):
    _expect(_score(b3, "A", [_F(b3)]), 1, 0, 0, 1, 1, 1, 0.98)


def test_T02(b3):
    _expect(_score(b3, "A", []), 0, 0, 1, 0, 0, 0, -1)


def test_T03(b3):
    _expect(_score(b3, "empty", []), 0, 0, 0, 0, 0, 1, 0.98)


def test_T04(b3):
    _expect(_score(b3, "empty", [_F(b3)]), 0, 1, 0, 0, 0, 0, -1)


def test_T05(b3):
    s = _score(b3, "A", [_F(b3), _F(b3)])
    _expect(s, 1, 1, 0, Fraction(1, 2), 1, Fraction(2, 3), Fraction(47, 150))
    assert s["return"] <= _score(b3, "A", [_F(b3)])["return"]


def test_T06(b3):
    _expect(_score(b3, "A", [_F(b3, type="fx_mismatch")]), 0, 1, 1, 0, 0, 0, -1)


def test_T07(b3):
    _expect(_score(b3, "A", [_F(b3, affected_ids=[b3["R2"]])]), 0, 1, 1, 0, 0, 0, -1)


def test_T08(b3):
    _expect(_score(b3, "A", [_F(b3, claimed_amount_minor=10001)]), 0, 1, 1, 0, 0, 0, -1)


def test_T09(b3):
    _expect(_score(b3, "A", [_F(b3, currency="USD")]), 0, 1, 1, 0, 0, 0, -1)


def test_T10(b3):
    _expect(_score(b3, "A", [_F(b3, evidence_ids=[b3["D1"]])]), 0, 1, 1, 0, 0, 0, -1)


def test_T11(b3):
    _expect(_score(b3, "A", [_F(b3, evidence_ids=[b3["D1"], b3["U"]])]), 0, 1, 1, 0, 0, 0, -1)


def test_T12(b3):
    five = read_episode(b3["dirs"]["five"])
    records = [d["invoice_id"] for d in five["invoices"]]
    assert len(records) == 5
    types = five["manifest"]["issue_types"]
    assert len(types) == 4
    findings = [_F(b3, type=t, affected_ids=[rid]) for rid in records for t in types]
    assert len(findings) == 20
    _expect(_score(b3, "five", findings), 1, 19, 0, Fraction(1, 20), 1, Fraction(2, 21), Fraction(-871, 1050))


def test_T13(b3):
    _expect(_score(b3, "AB", [_F(b3)]), 1, 0, 1, 1, Fraction(1, 2), Fraction(2, 3), Fraction(47, 150))


def test_T14(b3):
    _expect(_score(b3, "AB", [_F(b3), _F(b3, affected_ids=[b3["R3"]])]), 1, 1, 1, 0.5, 0.5, 0.5, -0.02)


def test_T15(b3):
    _expect(_score(b3, "A", [_F(b3)], steps=0), 1, 0, 0, 1, 1, 1, 1)


def test_T16(b3):
    s = _score(b3, "A", [_F(b3)], steps=50)
    _expect(s, 1, 0, 0, 1, 1, 1, 0.90)
    assert abs(_score(b3, "A", [_F(b3)])["return"] - s["return"] - 0.08) <= TOL


def test_T17(b3):
    _expect(_score(b3, "A", [_F(b3)], steps=100), 1, 0, 0, 1, 1, 1, 0.80)


def _invalid_episode(b3, caplog, findings: list):
    """Score path and episode path: invalid structure -> -1, episode ends, reason in the evaluator log."""
    with caplog.at_level(logging.INFO, logger="judge_adapter"):
        caplog.clear()
        _invalid(_score(b3, "A", findings))
        scored_logged = [
            r for r in caplog.records if r.name.startswith("judge_adapter") and r.levelno >= logging.WARNING
        ]
        assert scored_logged, "no evaluator-log entry for the invalid structure (score_episode)"
        caplog.clear()
        run = Run()
        run.reset(b3["dirs"]["A"])
        for i in range(10):
            run.step(act("calculator", expression=f"{i}*2"))
        obs, r, term, trunc, info = run.step(act("submit", findings={"findings": findings}))
        assert term is True and r == 0 and obs["error"] is not None and obs["result"] is None
        rep = run.env.evaluator_report()
        assert rep["score"]["reward"] == -1, rep["score"]
        assert [r for r in caplog.records if r.name.startswith("judge_adapter") and r.levelno >= logging.WARNING], (
            "no evaluator-log entry for the invalid submit (episode)"
        )


def test_T18(b3, caplog):
    _invalid_episode(b3, caplog, [_F(b3, affected_ids=[b3["R1"]]) for _ in range(31)])


def test_T19(b3, caplog):
    rows = [r["row_id"] for r in b3["ep"]["ledger"] if r["row_id"] != b3["D2"]][:9]
    ev = [b3["D1"], b3["D2"], *rows]
    assert len(set(ev)) == 11
    _invalid_episode(b3, caplog, [_F(b3, evidence_ids=ev)])


def test_T20(b3, caplog):
    _invalid_episode(b3, caplog, [_F(b3, explanation="x" * 1001)])


# ---------------------------------------------------------------------------------- M01-M12
def test_M01(b3):
    _expect(_score(b3, "M", [_MF(b3, affected_ids=[b3["R2"], b3["R1"], b3["R1"]])]), 1, 0, 0, 1, 1, 1, 0.98)


def test_M02(b3):
    _expect(_score(b3, "M", [_MF(b3, affected_ids=[b3["R1"], b3["R2"], b3["R3"]])]), 0, 1, 1, 0, 0, 0, -1)


def test_M03(b3):
    _expect(_score(b3, "M", [_MF(b3, evidence_ids=[b3["MD2"], b3["MD1"], b3["MD3"]])]), 1, 0, 0, 1, 1, 1, 0.98)


def test_M04(b3):
    _expect(_score(b3, "M", [_MF(b3, evidence_ids=[b3["MD1"], b3["MD2"], b3["U"]])]), 0, 1, 1, 0, 0, 0, -1)


def test_M05(b3):
    _invalid(_score(b3, "M", [_MF(b3, evidence_ids=[b3["MD1"]] * 10 + [b3["MD2"]])]))


def test_M06(b3):
    for cur in ("kzt", "KZT ", " KZT", "Kzt"):
        _expect(_score(b3, "M", [_MF(b3, currency=cur)]), 0, 1, 1, 0, 0, 0, -1)


def test_M07(b3):
    _expect(_score(b3, "M", [_MF(b3, claimed_amount_minor=10001)]), 0, 1, 1, 0, 0, 0, -1)


def test_M08(b3):
    _expect(_score(b3, "M_tau1", [_MF(b3, claimed_amount_minor=10001)]), 1, 0, 0, 1, 1, 1, 0.98)
    _expect(_score(b3, "M_tau1", [_MF(b3, claimed_amount_minor=9999)]), 1, 0, 0, 1, 1, 1, 0.98)
    _expect(_score(b3, "M_tau1", [_MF(b3, claimed_amount_minor=10002)]), 0, 1, 1, 0, 0, 0, -1)
    # tau of the other fixtures is untouched
    _expect(_score(b3, "M", [_MF(b3, claimed_amount_minor=10001)]), 0, 1, 1, 0, 0, 0, -1)


def test_M09(b3):
    _invalid(_score(b3, "M", [_MF(b3, claimed_amount_minor="10000")]))
    _invalid(_score(b3, "M", [_MF(b3, claimed_amount_minor=True)]))
    _invalid(_score(b3, "M", [_MF(b3, claimed_amount_minor=10000.0)]))


def test_M10(b3):
    F0 = _MF(b3, evidence_ids=[b3["MD1"], b3["MD2"], b3["MD3"]])
    F1 = _MF(b3)
    _expect(_score(b3, "M10", [F0, F1]), 2, 0, 0, 1, 1, 1, 0.98)
    _expect(_score(b3, "M10", [F1, F0]), 2, 0, 0, 1, 1, 1, 0.98)


def test_M11(b3):
    F0, F1 = _MF(b3), _MF(b3, explanation="second")
    s1 = _score(b3, "M11", [F0, F1])
    _expect(s1, 2, 0, 0, 1, 1, 1, 0.98)
    assert _score(b3, "M11", [F1, F0]) == s1
    run = Run()
    run.reset(b3["dirs"]["M11"])
    run.step(act("submit", findings={"findings": [F0, F1]}))
    pairs = {f["index"]: f["matched_issue_id"] for f in run.env.evaluator_report()["findings"]}
    assert pairs == {0: "A", 1: "B"}, f"tie not broken as A->F0, B->F1: {pairs}"


def test_M12(b3):
    s = _score(b3, "M", [_MF(b3), _MF(b3)])
    _expect(s, 1, 1, 0, Fraction(1, 2), 1, Fraction(2, 3), Fraction(47, 150))
    assert s == _score(b3, "A", [_F(b3), _F(b3)]), "M12 differs from the reward vector of test 5"


# ======================================================================================== Block 4
@pytest.mark.parametrize("k", range(1, 21), ids=[f"P{k:02d}" for k in range(1, 21)])
def test_P(k, d_episodes, jury_root):
    name = f"D{k:02d}"
    other = d_episodes[f"D{(k % 20) + 1:02d}"]["dir"]
    work = jury_root / "P"
    work.mkdir(exist_ok=True)
    fails = check_p(k, name, d_episodes[name], other, str(work))
    assert not fails, f"P{k:02d} on {name}: " + "; ".join(fails)
