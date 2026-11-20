"""The jury's OWN reconciliation of one episode, written from the published rules only.

Sources: docs/ADAPTER.md section 5 and the episode's policy.json (posting, duplicates, allocation, fx, cutoff,
overlap, finding_conventions). Nothing here imports the team's matcher, families or generator.

reconcile(ep) returns a Recon with
  issues    the discrepancies the published rules imply, each with its canonical affected set, amount,
            currency and the conventional minimal evidence set;
  problems  contradictions: books that do not follow the posting rules, broken references, unbalanced
            currencies, over-application, missing fx rows. A correct episode (before or after injection)
            has none except the declared discrepancies themselves;
  facts     the look-alikes present (split payments, refunds, repeated amounts, fx receipts, boundary
            invoices), for the clean-company scenarios D02-D05.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, localcontext
from typing import Any

from jury_data import fx_key


@dataclass(frozen=True)
class Issue:
    type: str
    affected: frozenset[str]
    amount: int
    currency: str
    evidence: frozenset[str]

    @property
    def key(self) -> tuple:
        return (self.type, tuple(sorted(self.affected)), self.amount, self.currency)


@dataclass
class Recon:
    issues: list[Issue] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    facts: dict[str, list] = field(default_factory=lambda: defaultdict(list))

    def keys(self) -> Counter:
        return Counter(i.key for i in self.issues)


def parse_ts(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError(f"timestamp without offset: {value}")
    return dt


def _round_half_up_minor(major: Decimal, exponent: int) -> int:
    q = Decimal(1).scaleb(-exponent)
    return int((major.quantize(q, rounding=ROUND_HALF_UP)).scaleb(exponent))


class Books:
    def __init__(self, ep: dict[str, Any]):
        self.ep = ep
        self.manifest = ep["manifest"]
        self.policy = ep["policy"]
        acc = self.policy["accounts"]
        self.AR = acc["receivable"]
        self.REV = acc["revenue"]
        self.BANK = acc["bank"]
        self.UNAPPLIED = acc["unapplied"]
        self.CLEARING = acc["fx_clearing"]
        self.ps = parse_ts(self.manifest["period_start"])
        self.pe = parse_ts(self.manifest["period_end"])
        self.company_tz = self.ps.tzinfo
        self.exp = {c: v["exponent"] for c, v in self.manifest["currencies"].items()}
        self.ledger = ep["ledger"]
        self.invoices = {d["invoice_id"]: d for d in ep["invoices"]}
        self.payments = {d["payment_id"]: d for d in ep["payments"]}
        self.fx = {}
        for r in ep["fx"]:
            self.fx.setdefault((r["date"], r["source_currency"], r["target_currency"]), []).append(r)

    def side(self, ts: str) -> int:
        t = parse_ts(ts)
        if t < self.ps:
            return -1
        if t > self.pe:
            return 1
        return 0

    def local_date(self, ts: str) -> str:
        return parse_ts(ts).astimezone(self.company_tz).date().isoformat()

    def fx_row(self, date: str, rc: str, ic: str):
        rows = self.fx.get((date, rc, ic)) or self.fx.get((date, ic, rc)) or []
        return rows

    def translate(self, amount_minor: int, rc: str, ic: str, date: str) -> tuple[int, str] | None:
        rows = self.fx_row(date, rc, ic)
        if len(rows) != 1:
            return None
        row = rows[0]
        rate = Decimal(row["rate"])
        with localcontext() as ctx:
            ctx.prec = 60
            major = Decimal(amount_minor).scaleb(-self.exp[rc])
            if row["source_currency"] == rc:
                translated = major * rate
            else:
                translated = major / rate
            return _round_half_up_minor(translated, self.exp[ic]), fx_key(row)

    def translate_with_row(self, amount_minor: int, rc: str, ic: str, row: dict) -> int:
        rate = Decimal(row["rate"])
        with localcontext() as ctx:
            ctx.prec = 60
            major = Decimal(amount_minor).scaleb(-self.exp[rc])
            translated = major * rate if row["source_currency"] == rc else major / rate
            return _round_half_up_minor(translated, self.exp[ic])


def _dup_key(doc: dict, books: Books) -> tuple:
    import json

    return (
        doc["entity_id"],
        doc["currency"],
        parse_ts(doc["issued_at"]),
        parse_ts(doc["due_at"]),
        json.dumps(doc["line_items"], sort_keys=True),
    )


def reconcile(ep: dict[str, Any]) -> Recon:
    b = Books(ep)
    rec = Recon()
    P = rec.problems
    consumed: set[str] = set()

    # ---------------------------------------------------------------- referential integrity
    for space, items in (
        ("row_id", [r["row_id"] for r in b.ledger]),
        ("doc_id", [d["doc_id"] for d in ep["invoices"] + ep["payments"]]),
        ("invoice_id", [d["invoice_id"] for d in ep["invoices"]]),
        ("payment_id", [d["payment_id"] for d in ep["payments"]]),
    ):
        dup = [k for k, n in Counter(items).items() if n > 1]
        if dup:
            P.append(f"{space} not unique: {dup[:5]}")
    fx_dup = [k for k, rows in b.fx.items() if len(rows) > 1]
    if fx_dup:
        P.append(f"fx key not unique: {fx_dup[:3]}")
    entities = {d["entity_id"] for d in ep["invoices"]}
    for r in b.ledger:
        if r["invoice_id"] is not None and r["invoice_id"] not in b.invoices:
            P.append(f"ledger {r['row_id']} names unknown invoice {r['invoice_id']}")
        if r["payment_id"] is not None and r["payment_id"] not in b.payments:
            P.append(f"ledger {r['row_id']} names unknown payment {r['payment_id']}")
        # suppliers of "other journal entries" (no invoice_id/payment_id) need not have invoices
        if r["invoice_id"] is not None and r["entity_id"] is not None and r["entity_id"] not in entities:
            P.append(f"ledger {r['row_id']} names unknown entity {r['entity_id']}")
        if r["currency"] not in b.exp:
            P.append(f"ledger {r['row_id']} currency {r['currency']} not in manifest")
        if (r["debit_minor"] > 0) == (r["credit_minor"] > 0):
            P.append(f"ledger {r['row_id']} must have exactly one of debit/credit")
    for p in ep["payments"]:
        for ref in p["invoice_refs"]:
            if ref not in b.invoices:
                P.append(f"payment {p['payment_id']} refs unknown invoice {ref}")

    # ---------------------------------------------------------------- per-currency balance
    bal: dict[str, int] = defaultdict(int)
    for r in b.ledger:
        bal[r["currency"]] += r["debit_minor"] - r["credit_minor"]
    for cur, v in bal.items():
        if v != 0:
            P.append(f"currency {cur} debits != credits by {v}")

    by_inv: dict[str, list] = defaultdict(list)
    by_pay: dict[str, list] = defaultdict(list)
    for r in b.ledger:
        if r["payment_id"] is not None:
            by_pay[r["payment_id"]].append(r)
        elif r["invoice_id"] is not None:
            by_inv[r["invoice_id"]].append(r)

    # ---------------------------------------------------------------- invoices: posting + cutoff
    for inv_id, doc in b.invoices.items():
        rows = by_inv.get(inv_id, [])
        ar = [r for r in rows if r["account"] == b.AR and r["debit_minor"] > 0]
        rev = [r for r in rows if r["account"] == b.REV and r["credit_minor"] > 0]
        other = [r for r in rows if r not in ar and r not in rev]
        if other:
            P.append(f"invoice {inv_id}: unexpected rows {[r['row_id'] for r in other]}")
        if len(ar) != 1 or ar[0]["debit_minor"] != doc["total_minor"] or ar[0]["currency"] != doc["currency"]:
            P.append(f"invoice {inv_id}: not one AR debit for its total")
        if len(rev) != 1 or rev[0]["credit_minor"] != doc["total_minor"] or rev[0]["currency"] != doc["currency"]:
            P.append(f"invoice {inv_id}: not one revenue credit for its total")
            continue
        for r in ar + rev:
            consumed.add(r["row_id"])
            if r["entity_id"] != doc["entity_id"]:
                P.append(f"invoice {inv_id}: row {r['row_id']} entity differs")
        if sum(li["amount_minor"] for li in doc["line_items"]) != doc["total_minor"]:
            P.append(f"invoice {inv_id}: line items do not sum to total")
        for li in doc["line_items"]:
            if li["quantity"] * li["unit_price_minor"] != li["amount_minor"]:
                P.append(f"invoice {inv_id}: line item quantity x price != amount")
        s_doc, s_rev = b.side(doc["issued_at"]), b.side(rev[0]["timestamp"])
        if s_doc != s_rev:
            rec.issues.append(
                Issue(
                    "cutoff",
                    frozenset([inv_id]),
                    doc["total_minor"],
                    doc["currency"],
                    frozenset([doc["doc_id"], rev[0]["row_id"]]),
                )
            )
        elif s_doc != 0:
            rec.facts["boundary_ok"].append(inv_id)
        if parse_ts(doc["due_at"]) < parse_ts(doc["issued_at"]):
            P.append(f"invoice {inv_id}: due before issued")

    # ---------------------------------------------------------------- duplicates
    groups: dict[tuple, list] = defaultdict(list)
    for doc in ep["invoices"]:
        groups[_dup_key(doc, b)].append(doc)
    amounts: dict[tuple, set] = defaultdict(set)
    for key, docs in groups.items():
        if len(docs) > 1:
            d0 = docs[0]
            rec.issues.append(
                Issue(
                    "duplicate_invoice",
                    frozenset(d["invoice_id"] for d in docs),
                    d0["total_minor"] * (len(docs) - 1),
                    d0["currency"],
                    frozenset(d["doc_id"] for d in docs),
                )
            )
        amounts[(docs[0]["currency"], docs[0]["total_minor"])].add(key)
    rec.facts["repeated_amounts"] = [k for k, keys in amounts.items() if len(keys) > 1]

    # ---------------------------------------------------------------- receipts: fx + allocation
    open_bal = {i: d["total_minor"] for i, d in b.invoices.items()}
    receipts = sorted(ep["payments"], key=lambda p: parse_ts(p["timestamp"]))
    seen_ts: dict[tuple, str] = {}
    for p in receipts:
        for ref in p["invoice_refs"]:
            k = (parse_ts(p["timestamp"]), ref)
            if k in seen_ts:
                P.append(f"receipts {seen_ts[k]} and {p['payment_id']} on invoice {ref} share a timestamp")
            seen_ts[k] = p["payment_id"]
    alloc_count: dict[str, int] = defaultdict(int)
    for p in receipts:
        pid = p["payment_id"]
        rows = by_pay.get(pid, [])
        refs = [r for r in p["invoice_refs"] if r in b.invoices]
        bank_dr = [r for r in rows if r["account"] == b.BANK and r["debit_minor"] > 0]
        if (
            len(bank_dr) != 1
            or bank_dr[0]["debit_minor"] != p["amount_minor"]
            or bank_dr[0]["currency"] != p["currency"]
        ):
            P.append(f"receipt {pid}: not one bank debit for the document amount")
            continue
        consumed.add(bank_dr[0]["row_id"])
        if bank_dr[0]["timestamp"] != p["timestamp"] and parse_ts(bank_dr[0]["timestamp"]) != parse_ts(p["timestamp"]):
            P.append(f"receipt {pid}: bank row not at the document instant")
        inv_curs = {b.invoices[r]["currency"] for r in refs}
        if len(inv_curs) > 1:
            P.append(f"receipt {pid}: invoices in several currencies")
            continue
        ic = inv_curs.pop() if inv_curs else p["currency"]
        brought = p["amount_minor"]
        translation: list[str] = []  # ADAPTER.md section 5: across currencies, the fx_clearing debit is evidence
        if p["currency"] != ic:
            cl_cr = [r for r in rows if r["account"] == b.CLEARING and r["credit_minor"] > 0]
            cl_dr = [r for r in rows if r["account"] == b.CLEARING and r["debit_minor"] > 0]
            if (
                len(cl_cr) != 1
                or cl_cr[0]["currency"] != p["currency"]
                or cl_cr[0]["credit_minor"] != p["amount_minor"]
                or len(cl_dr) != 1
                or cl_dr[0]["currency"] != ic
            ):
                P.append(f"receipt {pid}: fx_clearing rows do not follow the posting rule")
                continue
            consumed.update([cl_cr[0]["row_id"], cl_dr[0]["row_id"]])
            brought = cl_dr[0]["debit_minor"]
            translation = [cl_dr[0]["row_id"]]
            date = b.local_date(p["timestamp"])
            tr = b.translate(p["amount_minor"], p["currency"], ic, date)
            if tr is None:
                P.append(f"receipt {pid}: no single fx row for {date} {p['currency']}/{ic}")
            else:
                required, key = tr
                rec.facts["fx_receipts"].append(pid)
                if required != brought:
                    rec.issues.append(
                        Issue(
                            "fx_mismatch",
                            frozenset([pid]),
                            abs(required - brought),
                            ic,
                            frozenset([p["doc_id"], key, cl_dr[0]["row_id"]]),
                        )
                    )
                    # how was it translated? another date's rate, or none
                    other = [
                        fx_key(rw)
                        for rws in b.fx.values()
                        for rw in rws
                        if {rw["source_currency"], rw["target_currency"]} == {p["currency"], ic}
                        and b.translate_with_row(p["amount_minor"], p["currency"], ic, rw) == brought
                    ]
                    rec.facts["fx_wrong_rows"].append((pid, other))
                elif date != p["timestamp"][:10]:
                    rec.facts["fx_local_date_differs"].append(pid)
        remaining = brought
        for ref in p["invoice_refs"]:
            if ref not in b.invoices:
                continue
            inv = b.invoices[ref]
            req = max(0, min(remaining, open_bal[ref]))
            open_bal[ref] -= req
            remaining -= req
            ar_rows = [r for r in rows if r["account"] == b.AR and r["invoice_id"] == ref]
            for r in ar_rows:
                consumed.add(r["row_id"])
                if r["currency"] != ic:
                    P.append(f"receipt {pid}: AR row {r['row_id']} in {r['currency']} not {ic}")
            recorded = sum(r["credit_minor"] - r["debit_minor"] for r in ar_rows)
            if req > 0:
                alloc_count[ref] += 1
            if recorded < req:
                ev = [inv["doc_id"], p["doc_id"]] + [r["row_id"] for r in ar_rows] + translation
                rec.issues.append(Issue("payment_allocation", frozenset([ref, pid]), req - recorded, ic, frozenset(ev)))
            elif recorded > req:
                P.append(f"receipt {pid}: applied {recorded} to {ref}, more than the policy allows ({req})")
        if len([r for r in p["invoice_refs"] if r in b.invoices]) > 1:
            rec.facts["multi_invoice_receipts"].append(pid)
        stray_ar = [r for r in rows if r["account"] == b.AR and r["invoice_id"] not in p["invoice_refs"]]
        if stray_ar:
            P.append(f"receipt {pid}: AR rows for invoices it does not reference")
        un_cr = [r for r in rows if r["account"] == b.UNAPPLIED and r["credit_minor"] > 0]
        un_dr = [r for r in rows if r["account"] == b.UNAPPLIED and r["debit_minor"] > 0]
        bank_cr = [r for r in rows if r["account"] == b.BANK and r["credit_minor"] > 0]
        consumed.update(r["row_id"] for r in un_cr + un_dr + bank_cr)
        recorded_ar = sum(r["credit_minor"] - r["debit_minor"] for r in rows if r["account"] == b.AR)
        un_total = sum(r["credit_minor"] for r in un_cr if r["currency"] == ic)
        if refs and recorded_ar + un_total != brought:
            P.append(f"receipt {pid}: AR + unapplied ({recorded_ar}+{un_total}) != amount brought {brought}")
        refund = sum(r["debit_minor"] for r in un_dr)
        if refund or bank_cr:
            if refund != sum(r["credit_minor"] for r in bank_cr):
                P.append(f"receipt {pid}: refund unapplied debit != bank credit")
            if any(r["currency"] != ic for r in un_dr + bank_cr):
                P.append(f"receipt {pid}: refund not in the invoice currency")
            if any(parse_ts(r["timestamp"]) <= parse_ts(p["timestamp"]) for r in un_dr + bank_cr):
                P.append(f"receipt {pid}: refund not later than the receipt")
            if refund > un_total:
                P.append(f"receipt {pid}: refund exceeds the unapplied credit")
            rec.facts["refunds"].append(pid)
    rec.facts["split_invoices"] = [i for i, n in alloc_count.items() if n > 1]

    # ---------------------------------------------------------------- rows no rule explains
    for r in b.ledger:
        if (r["invoice_id"] is not None or r["payment_id"] is not None) and r["row_id"] not in consumed:
            P.append(f"ledger {r['row_id']} carries ids but follows no posting rule")
    return rec


# ------------------------------------------------------------------------------------------- before state
def _key_of(table: str, record: dict) -> str:
    return {"ledger": "row_id", "invoices": "invoice_id", "payments": "payment_id"}.get(table, "row_id")


def reconstruct_before(ep: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Undo every provenance change (reverse order) on a copy of the published state."""
    import copy

    problems: list[str] = []
    before = copy.deepcopy(ep)
    prov = ep.get("provenance") or {}
    for inj in reversed(prov.get("injections", [])):
        for ch in reversed(inj.get("changes", [])):
            table = ch.get("table")
            rows = before.get(table)
            if rows is None or table == "fx":
                problems.append(f"{inj.get('injection_id')}: change on unsupported table {table}")
                continue
            op = ch.get("op")
            if op == "insert":
                rec = ch["record"]
                match = [i for i, r in enumerate(rows) if r == rec]
                if len(match) != 1:
                    problems.append(f"{inj.get('injection_id')}: inserted {table} record not found as written")
                    continue
                rows.pop(match[0])
            elif op == "delete":
                rec = ch["record"]
                if table == "ledger" and any(r["row_id"] == rec["row_id"] for r in rows):
                    problems.append(f"{inj.get('injection_id')}: deleted row {rec['row_id']} still present")
                rows.append(dict(rec))
            elif op == "update":
                rid = ch["id"]
                cand_keys = ("row_id",) if table == "ledger" else ("invoice_id", "doc_id", "payment_id")
                match = [r for r in rows if any(r.get(k) == rid for k in cand_keys)]
                if len(match) != 1:
                    problems.append(f"{inj.get('injection_id')}: updated record {rid} not found")
                    continue
                if match[0].get(ch["field"]) != ch["after"]:
                    problems.append(f"{inj.get('injection_id')}: {rid}.{ch['field']} is not the provenance 'after'")
                match[0][ch["field"]] = ch["before"]
            else:
                problems.append(f"{inj.get('injection_id')}: unknown op {op}")
    return before, problems
