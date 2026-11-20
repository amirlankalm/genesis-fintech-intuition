"""Block 2 (D) and Block 4 (P) per-episode checks. Each returns a list of failure strings (empty = pass)."""

from __future__ import annotations

import os
import re
from collections import Counter
from decimal import Decimal
from typing import Any

from jury_data import canonical_json, choose_unknown_id, fx_key, read_episode, write_episode
from jury_play import Run, act, canonical_findings, fetch_evidence, id_sets, oracle_from_truth, public_view
from jury_recon import reconcile, reconstruct_before
from jury_transform import build_maps, invert, map_findings, map_record, permute, rename, union

import judge_adapter

TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(Z|[+-]\d{2}:\d{2})$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
RATE_RE = re.compile(r"^[0-9]+(\.[0-9]+)?$")


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def truth_keys(truth: dict) -> Counter:
    return Counter(
        (i["type"], tuple(sorted(set(i["affected_ids"]))), i["expected_amount_minor"], i["currency"])
        for i in truth["issues"]
    )


def check_formats(view: dict[str, list[dict]], manifest: dict) -> list[str]:
    """Section 03 formats on what the tools return."""
    f: list[str] = []
    for k in ("period_start", "period_end"):
        if not TS_RE.match(str(manifest.get(k))):
            f.append(f"manifest.{k} is not ISO-8601 with offset")
    exps = manifest.get("currencies", {})
    for r in view["ledger"]:
        if not TS_RE.match(str(r.get("timestamp"))):
            f.append(f"ledger {r.get('row_id')}: timestamp {r.get('timestamp')!r} lacks an offset")
        for k in ("debit_minor", "credit_minor"):
            if not _is_int(r.get(k)) or r[k] < 0:
                f.append(f"ledger {r.get('row_id')}: {k} not a non-negative integer")
        for k in ("entity_id", "invoice_id", "payment_id"):
            if not (r.get(k) is None or (isinstance(r[k], str) and r[k] != "")):
                f.append(f"ledger {r.get('row_id')}: {k} is neither an id nor explicit null ({r.get(k)!r})")
        if r.get("currency") not in exps:
            f.append(f"ledger {r.get('row_id')}: currency {r.get('currency')} not in manifest.currencies")
    for d in view["invoices"]:
        for k in ("issued_at", "due_at"):
            if not TS_RE.match(str(d.get(k))):
                f.append(f"invoice {d.get('invoice_id')}: {k} lacks an offset")
        if not _is_int(d.get("total_minor")):
            f.append(f"invoice {d.get('invoice_id')}: total_minor not an integer")
        for li in d.get("line_items", []):
            if not all(_is_int(li.get(k)) for k in ("quantity", "unit_price_minor", "amount_minor")):
                f.append(f"invoice {d.get('invoice_id')}: line item amounts not integers")
        if d.get("currency") not in exps:
            f.append(f"invoice {d.get('invoice_id')}: currency not in manifest")
    for d in view["payments"]:
        if not TS_RE.match(str(d.get("timestamp"))):
            f.append(f"payment {d.get('payment_id')}: timestamp lacks an offset")
        if not _is_int(d.get("amount_minor")):
            f.append(f"payment {d.get('payment_id')}: amount_minor not an integer")
        if not isinstance(d.get("invoice_refs"), list):
            f.append(f"payment {d.get('payment_id')}: invoice_refs not a list")
    for r in view["fx"]:
        if not (isinstance(r.get("rate"), str) and RATE_RE.match(r["rate"]) and Decimal(r["rate"]) > 0):
            f.append(f"fx {r}: rate is not a positive decimal string")
        if not DATE_RE.match(str(r.get("date"))):
            f.append(f"fx {r}: date not YYYY-MM-DD")
    return f[:20]


def _multiset(records: list[dict]) -> Counter:
    return Counter(canonical_json(r) for r in records)


def provenance_expected(ep: dict) -> Counter:
    prov = ep.get("provenance") or {}
    out = Counter()
    for inj in prov.get("injections", []):
        exp = inj.get("expected")
        exps = exp if isinstance(exp, list) else [exp]
        for e in exps:
            if not e:
                continue
            out[(e["type"], tuple(sorted(set(e["affected_ids"]))), e["amount_minor"], e["currency"])] += 1
    return out


def change_deltas(ep: dict) -> dict[str, list[int]]:
    """Per injected receipt: the AR credit removed and the fx_clearing debit moved, read off the changes."""
    deltas: dict[str, list[int]] = {"ar": [], "clearing": []}
    acc = ep["policy"]["accounts"]
    rows = {r["row_id"]: r for r in ep["ledger"]}
    for inj in (ep.get("provenance") or {}).get("injections", []):
        for ch in inj.get("changes", []):
            if ch.get("table") != "ledger":
                continue
            if ch["op"] == "delete" and ch["record"]["account"] == acc["receivable"]:
                deltas["ar"].append(ch["record"]["credit_minor"])
            if ch["op"] == "update" and ch["field"] == "credit_minor":
                r = rows.get(ch["id"])
                if r and r["account"] == acc["receivable"]:
                    deltas["ar"].append(ch["before"] - ch["after"])
            if ch["op"] == "update" and ch["field"] == "debit_minor":
                r = rows.get(ch["id"])
                if r and r["account"] == acc["fx_clearing"]:
                    deltas["clearing"].append(abs(ch["before"] - ch["after"]))
    return deltas


def check_d(name: str, case: dict, d_dir: str, all_eps: dict[str, dict]) -> list[str]:
    fails: list[str] = []
    ep = read_episode(d_dir)
    truth = ep["truth"]
    expect = Counter(case["expect"])

    # ---- 5. formats, through the tools; and the tool view equals the published files
    view, run = public_view(d_dir)
    fails += check_formats(view, run.first_obs["manifest"])
    for t in ("ledger", "invoices", "payments", "fx"):
        if _multiset(view[t]) != _multiset(ep[t]):
            fails.append(f"[cond 5/6] list_records({t}) through the tools differs from the episode's data")

    # ---- 1. books agreed before injection (provenance replayed backwards), independent reconciliation
    before, prov_problems = reconstruct_before(ep)
    fails += [f"[cond 1] provenance does not replay: {p}" for p in prov_problems]
    rb = reconcile(before)
    if rb.issues:
        fails.append(f"[cond 1] books before injection are not agreed: {[i.key for i in rb.issues]}")
    fails += [f"[cond 1] before-state contradiction: {p}" for p in rb.problems[:5]]

    # ---- 2/6. after injection exactly the declared discrepancy, no contradictions
    ra = reconcile(ep)
    fails += [f"[cond 6] contradiction: {p}" for p in ra.problems[:5]]
    mine = ra.keys()
    declared = provenance_expected(ep)
    if mine - rb.keys() != declared or declared - (mine - rb.keys()):
        fails.append(
            f"[cond 2] independent reconciliation finds {sorted(mine)} but provenance declares {sorted(declared)}"
        )
    # ---- 3. truth = the real change
    tk = truth_keys(truth)
    if tk != mine:
        fails.append(f"[cond 3] truth {sorted(tk)} != independent reconciliation {sorted(mine)}")
    if Counter(i["type"] for i in truth["issues"]) != expect:
        fails.append(f"[cond 3] truth types {[i['type'] for i in truth['issues']]} != requested {case['expect']}")
    if not case["expect"] and (truth["issues"] or (ep.get("provenance") or {}).get("injections")):
        fails.append("[cond 3] clean company carries truth issues or injections")
    deltas = change_deltas(ep)
    for i in ra.issues:
        if i.type == "payment_allocation" and i.amount not in deltas["ar"]:
            fails.append(f"[cond 3] allocation amount {i.amount} does not follow from the change {deltas['ar']}")
        if i.type == "fx_mismatch" and i.amount not in deltas["clearing"]:
            fails.append(f"[cond 3] fx amount {i.amount} does not follow from the change {deltas['clearing']}")

    # ---- 4. one complete acceptable evidence set, the one the rules give, reachable through the tools
    doc_ids, row_ids, fxk = id_sets(ep)
    by_key = {}
    for i in ra.issues:
        by_key.setdefault(i.key, []).append(i)
    published = {
        **{d["doc_id"]: d for d in view["invoices"] + view["payments"]},
        **{r["row_id"]: r for r in view["ledger"]},
        **{fx_key(r): r for r in view["fx"]},
    }
    for issue in truth["issues"]:
        key = (
            issue["type"],
            tuple(sorted(set(issue["affected_ids"]))),
            issue["expected_amount_minor"],
            issue["currency"],
        )
        sets = [frozenset(s) for s in issue["acceptable_evidence_sets"]]
        rule_sets = [i.evidence for i in by_key.get(key, [])]
        # complete = it holds every record the published convention needs to verify the conclusion
        if rule_sets and not any(rule_sets[0] <= s for s in sets):
            fails.append(
                f"[cond 4] {issue['type']}: no acceptable set is complete; the published conventions need "
                f"{sorted(rule_sets[0])}; truth sets {issue['acceptable_evidence_sets']}"
            )
        ok_any = False
        for s in sets:
            ok = True
            for ident in sorted(s):
                obs, err = fetch_evidence(run, ident, doc_ids, row_ids, fxk)
                if err or obs["error"] is not None or obs["result"] != published.get(ident):
                    ok = False
            ok_any = ok_any or ok
        if not ok_any:
            fails.append(f"[cond 4] {issue['type']}: no acceptable evidence set is fully accessible via the tools")

    # ---- scenario-specific requirements of the matrix
    sc = case["scenario"]
    facts = ra.facts
    if sc == "clean_split_payment" and not (facts.get("split_invoices") or facts.get("multi_invoice_receipts")):
        fails.append("D02 needs a correctly split payment; none found")
    if sc == "clean_refund" and not facts.get("refunds"):
        fails.append("D03 needs a correct refund; none found")
    if sc in ("clean_repeated_amounts", "duplicate") and not facts.get("repeated_amounts"):
        fails.append(f"{name} needs legitimately repeated amounts that are not duplicates; none found")
    if sc == "clean_fx_and_period_boundary" and not (facts.get("fx_receipts") and facts.get("boundary_ok")):
        fails.append("D05 needs correct fx translations and correct period-boundary postings")
    # receivable rows cited by a set (a foreign receipt's set also cites its fx_clearing debit, policy case-draft-2)
    receivable = {r["row_id"] for r in ep["ledger"] if r["account"] == ep["policy"]["accounts"]["receivable"]}
    if sc == "allocation_missing":
        if any(set(s) & receivable for i in truth["issues"] for s in i["acceptable_evidence_sets"]) or any(
            i.evidence & receivable for i in ra.issues
        ):
            fails.append("D09 'missing': an allocation row for the pair still exists")
    if sc == "allocation_partial" and any(not i.evidence & receivable for i in ra.issues):
        fails.append("D10 'partial': no partial allocation row for the pair")
    if sc in ("fx_date", "fx_rate"):
        wrong = facts.get("fx_wrong_rows", [])
        if sc == "fx_date" and not all(rows for _, rows in wrong):
            fails.append("D12 'date': the recorded translation matches no other date's fx row")
        if sc == "fx_rate" and any(rows for _, rows in wrong):
            fails.append(f"D13 'rate': the recorded translation equals another fx row {wrong}")
    if sc == "cutoff_and_allocation":
        fails += _check_cutoff_and_allocation(case["params"], ep, ra)
    if sc == "duplicate_then_cutoff":
        fails += _check_duplicate_then_cutoff(case["params"], ep, ra)
    if sc == "duplicate":
        mine_dup = [i for i in ra.issues if i.type == "duplicate_invoice"]
        for other_name, other in all_eps.items():
            if other_name == name or other["case"]["scenario"] != "duplicate":
                continue
            o = [i for i in reconcile(other["ep"]).issues if i.type == "duplicate_invoice"]
            if o and mine_dup and (o[0].affected == mine_dup[0].affected or o[0].evidence == mine_dup[0].evidence):
                fails.append(f"{name} and {other_name} duplicate the same ids/documents")
    return fails


def _boundary_ok(b_side: str, sides: set[int]) -> bool:
    return sides == ({-1, 0} if b_side == "start" else {0, 1})


def _sides(ep: dict, inv_id: str) -> set[int]:
    from jury_recon import Books

    books = Books(ep)
    doc = books.invoices[inv_id]
    rev = [
        r for r in ep["ledger"] if r["invoice_id"] == inv_id and r["payment_id"] is None and r["account"] == books.REV
    ]
    return {books.side(doc["issued_at"]), books.side(rev[0]["timestamp"])}


def _check_cutoff_and_allocation(params: dict, ep: dict, ra) -> list[str]:
    f = []
    cut = [i for i in ra.issues if i.type == "cutoff"]
    alloc = [i for i in ra.issues if i.type == "payment_allocation"]
    if len(cut) != 1 or len(alloc) != 1:
        return [f"interaction 1 needs one cutoff and one allocation issue, found {[i.key for i in ra.issues]}"]
    inv = next(iter(cut[0].affected))
    if inv not in alloc[0].affected:
        f.append("interaction 1: the allocation issue is not on the cutoff invoice")
    if not _boundary_ok(params["boundary"], _sides(ep, inv)):
        f.append(f"interaction 1: boundary '{params['boundary']}' not honoured (sides {_sides(ep, inv)})")
    pay = next(iter(alloc[0].affected - {inv}))
    pdoc = next(p for p in ep["payments"] if p["payment_id"] == pay)
    idoc = next(d for d in ep["invoices"] if d["invoice_id"] == inv)
    foreign = pdoc["currency"] != idoc["currency"]
    if foreign != (params["receipt_currency"] == "foreign"):
        f.append(f"interaction 1: receipt_currency '{params['receipt_currency']}' not honoured")
    # partial = some receivable row carries both ids (the set may also hold a foreign receipt's fx_clearing debit)
    receivable = ep["policy"]["accounts"]["receivable"]
    partial = any(r["row_id"] in alloc[0].evidence and r["account"] == receivable for r in ep["ledger"])
    if partial != (params["allocation"] == "partial"):
        f.append(f"interaction 1: allocation '{params['allocation']}' not honoured")
    return f


def _check_duplicate_then_cutoff(params: dict, ep: dict, ra) -> list[str]:
    cut = [i for i in ra.issues if i.type == "cutoff"]
    dup = [i for i in ra.issues if i.type == "duplicate_invoice"]
    if len(cut) != 1 or len(dup) != 1:
        return [f"interaction 2 needs one duplicate and one cutoff, found {[i.key for i in ra.issues]}"]
    f = []
    inv = next(iter(cut[0].affected))
    if inv not in dup[0].affected:
        f.append("interaction 2: the cutoff is not on a record of the duplicate group")
    if not _boundary_ok(params["boundary"], _sides(ep, inv)):
        f.append(f"interaction 2: boundary '{params['boundary']}' not honoured (sides {_sides(ep, inv)})")
    return f


# ============================================================================== Block 4
def _script(ep: dict, findings: dict, unknown: str) -> list[dict]:
    """A fixed jury action script: some inspection (incl. one error), the oracle's evidence, then submit."""
    doc_ids, row_ids, fxk = id_sets(ep)
    s = [
        act("list_records", table="ledger", cursor=None, limit=7),
        act("list_records", table="invoices", cursor=None, limit=5),
        act("get_record", table="ledger", id=ep["ledger"][3]["row_id"]),
        act("get_record", table="invoices", id=ep["invoices"][1]["invoice_id"]),
        act("get_record", table="payments", id=ep["payments"][0]["payment_id"]),
        act("get_document", doc_id=ep["payments"][0]["doc_id"]),
        act("get_record", table="fx", id=fx_key(ep["fx"][2])),
        act("calculator", expression="1/3"),
        act("get_record", table="ledger", id=unknown),
    ]
    for f in findings["findings"]:
        for ident in f["evidence_ids"]:
            if ident in doc_ids:
                s.append(act("get_document", doc_id=ident))
            elif ident in row_ids:
                s.append(act("get_record", table="ledger", id=ident))
            else:
                s.append(act("get_record", table="fx", id=ident))
    return s


def _map_action(a: dict, u: dict[str, str]) -> dict:
    return {"name": a["name"], "args": {k: (u.get(v, v) if isinstance(v, str) else v) for k, v in a["args"].items()}}


def _play(d: str, script: list[dict], findings: dict, env=None) -> Run:
    run = Run(env)
    run.reset(d, seed=0)
    for a in script:
        run.step(a)
    run.step(act("submit", findings=findings))
    return run


def _strings(value: Any, out: set[str]) -> set[str]:
    if isinstance(value, str):
        out.add(value)
    elif isinstance(value, list):
        for v in value:
            _strings(v, out)
    elif isinstance(value, dict):
        for v in value.values():
            _strings(v, out)
    return out


SCORE_FIELDS = ("tp", "fp", "fn", "precision", "recall", "f1", "return")


def _digest(directory: str) -> str:
    import hashlib

    h = hashlib.sha256()
    for name in sorted(os.listdir(directory)):
        h.update(name.encode())
        with open(os.path.join(directory, name), "rb") as fh:
            h.update(fh.read())
    return h.hexdigest()


def check_p(k: int, d_name: str, d_info: dict, other_dir: str, work: str) -> list[str]:
    fails: list[str] = []
    orig_dir = d_info["dir"]
    ep = read_episode(orig_dir)
    kind = "permute" if k <= 5 else ("rename" if k <= 10 else "both")
    tseed = 9_000 + k
    maps = build_maps(ep, tseed) if kind != "permute" else {s: {} for s in ("row_id",)}
    t_ep = ep
    if kind in ("rename", "both"):
        t_ep = rename(t_ep, maps)
    if kind in ("permute", "both"):
        t_ep = permute(t_ep, tseed)
    t_dir = os.path.join(work, f"P{k:02d}_{d_name}_{kind}")
    write_episode(t_dir, t_ep)
    if _digest(orig_dir) != d_info["digest"]:
        fails.append("the original episode directory was modified")
    u = union(maps)
    inv = invert(u)
    # jury preconditions: the transformation really happened
    if kind in ("permute", "both"):
        assert any(
            canonical_json(sorted(t_ep[t], key=canonical_json)) == canonical_json(sorted(ep[t], key=canonical_json))
            and t_ep[t] != ep[t]
            for t in ("ledger", "invoices", "payments", "fx")
        ), "permutation is a no-op"
    if kind in ("rename", "both"):
        written = "".join(
            open(os.path.join(t_dir, n), encoding="utf-8").read()
            for n in ("ledger.csv", "invoices.jsonl", "payments.jsonl", "truth.json", "provenance.json")
        )
        stale = [old for old in u if f'"{old}"' in written or f"{old}," in written or f",{old}\n" in written]
        assert not stale, f"transformer left old ids: {stale[:5]}"

    # ---- 1. exact replay of the original: regenerate, replay twice, replay after another episode
    regen = os.path.join(work, f"P{k:02d}_{d_name}_regen")
    judge_adapter.generate_episode(d_info["seed"], d_info["config"], regen)
    re_ep = read_episode(regen)
    for part in ("manifest", "policy", "ledger", "invoices", "payments", "fx", "truth", "provenance"):
        if canonical_json(re_ep[part]) != canonical_json(ep[part]):
            fails.append(f"[pair 1] regenerating with the same seed/config/version changes {part}")
    oracle_o = oracle_from_truth(ep["truth"], ep["manifest"]["episode_id"])
    unknown = choose_unknown_id(ep)
    script = _script(ep, oracle_o, unknown)
    r1 = _play(orig_dir, script, oracle_o)
    r2 = _play(orig_dir, script, oracle_o)
    env3 = judge_adapter.make_env()
    warm = Run(env3)
    warm.reset(other_dir)
    for _ in range(5):
        warm.step(act("list_records", table="ledger", cursor=None, limit=50))
    r3 = _play(orig_dir, script, oracle_o, env=env3)
    if r1.transcript != r2.transcript:
        fails.append("[pair 1] two replays of the same actions differ")
    if r1.transcript != r3.transcript:
        fails.append("[pair 1] a replay after another episode on the same env differs (reset carries state)")
    ki = r1.inspection_steps
    s1 = judge_adapter.score_episode(orig_dir, oracle_o, ki)
    s1b = judge_adapter.score_episode(orig_dir, oracle_o, ki)
    if s1 != s1b:
        fails.append("[pair 1] score_episode not reproducible")

    # ---- 2. oracle on the transformed copy, mapped back
    oracle_t = oracle_from_truth(t_ep["truth"], t_ep["manifest"]["episode_id"])
    if canonical_findings(map_findings(oracle_t, inv)) != canonical_findings(oracle_o):
        fails.append("[pair 2] oracle findings on the copy do not map back to the original's")
    ad_o = judge_adapter.oracle_findings(orig_dir)
    ad_t = judge_adapter.oracle_findings(t_dir)
    if canonical_findings(map_findings(ad_t, inv)) != canonical_findings(ad_o):
        fails.append("[pair 2] the adapter's oracle on the copy does not map back to its oracle on the original")

    # ---- 3. same steps, same TP/FP/FN/P/R/F1/return
    t_script = [_map_action(a, u) for a in script]
    rt = _play(t_dir, t_script, oracle_t)
    if rt.inspection_steps != ki:
        fails.append(f"[pair 3] inspection steps differ: {ki} vs {rt.inspection_steps}")
    if rt.transcript[-1][1] != {
        "result": {"accepted": True},
        "error": None,
        "remaining_steps": 100 - len(t_script) - 1,
    }:
        fails.append(f"[pair 3] submit on the copy not accepted: {rt.transcript[-1][1]}")
    st = judge_adapter.score_episode(t_dir, oracle_t, ki)
    if st != s1:
        fails.append(f"[pair 3] scores differ: original {s1} vs transformed {st}")
    n = len(ep["truth"]["issues"])
    if (s1["tp"], s1["fp"], s1["fn"]) != (n, 0, 0) or s1["f1"] != 1.0:
        fails.append(f"[pair 3] oracle does not reach the maximum on the original: {s1}")
    for side, d, r in (("original", orig_dir, r1), ("transformed", t_dir, rt)):
        rep = r.env.evaluator_report()["score"]
        sc = judge_adapter.score_episode(d, oracle_o if side == "original" else oracle_t, ki)
        if any(rep[f] != sc[f] for f in ("tp", "fp", "fn", "f1")) or abs(rep["reward"] - sc["return"]) > 1e-9:
            fails.append(f"[pair 3] env's own end-of-episode score differs from score_episode on the {side}")

    # ---- 4. no new leak, nothing inaccessible; a broken evidence set must not keep the reward
    if n:
        broken_o = {"findings": [dict(f, evidence_ids=f["evidence_ids"][1:]) for f in oracle_o["findings"]]}
        broken_t = map_findings(broken_o, u)
        bo = judge_adapter.score_episode(orig_dir, broken_o, ki)
        bt = judge_adapter.score_episode(t_dir, broken_t, ki)
        if bo != bt or bo["tp"] != 0:
            fails.append(f"[pair 4] broken evidence: original {bo} vs copy {bt} (expected tp=0 on both)")
        if kind != "permute":
            stale = judge_adapter.score_episode(t_dir, oracle_o, ki)
            if stale["tp"] != 0:
                fails.append(f"[pair 4] the copy still credits the OLD ids: {stale}")
    view_o, _ = public_view(orig_dir)
    view_t, run_t = public_view(t_dir)
    for t in ("ledger", "invoices", "payments", "fx"):
        back = [map_record(r, inv) for r in view_t[t]]
        if _multiset(back) != _multiset(view_o[t]):
            fails.append(f"[pair 4] the copy's {t} does not map back to the original's")
        if canonical_json(view_t[t]) != canonical_json(t_ep[t]):
            fails.append(f"[pair 4] list_records({t}) on the copy does not follow the copy's record order")
    seen = _strings(run_t.observations(), set())
    secret = {i["issue_id"] for i in t_ep["truth"]["issues"]}
    canary = (t_ep.get("provenance") or {}).get("canary")
    if canary:
        secret.add(canary)
    if seen & secret:
        fails.append(f"[pair 4] closed values reach the policy on the copy: {sorted(seen & secret)}")
    if kind != "permute":
        old = set(u) & seen
        if old:
            fails.append(f"[pair 4] old ids still visible on the renamed copy: {sorted(old)[:5]}")
    doc_ids, row_ids, fxk = id_sets(t_ep)
    acc = Run()
    acc.reset(t_dir)
    for f in oracle_t["findings"]:
        for ident in f["evidence_ids"]:
            obs, err = fetch_evidence(acc, ident, doc_ids, row_ids, fxk)
            if err or obs["error"] is not None:
                fails.append(f"[pair 4] evidence {ident} of the copy is not accessible")
    return fails
