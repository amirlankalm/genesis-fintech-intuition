# E2: hostile review of the case stage

Reviewer: Team Intuition automated testing battery (20 November 2026). Every row below was run; nothing is inferred from reading alone.

**What was reviewed.** The working tree changed while I worked (generator, CLI, SPEC and episodes were rewritten between 09:20 and 09:50). I froze three copies outside the repository (09:27, 09:40, 09:49) and ran the attacks on those. Every item under "Actual failures" was re-run on the live tree at 09:52 (HEAD `c8b388b` plus uncommitted changes to `cli.py`, `evaluate.py`, `families.py`, `teaching.py`, `world.py`) and still reproduces there. Things that failed on an earlier copy and were fixed by 09:49 are listed separately at the end of section 2.

**Scale of the runs.** 1,430 generation attempts per copy (300 small, 100 medium, 40 large, 990 at the edges of the documented config ranges), under a private key; 1,424 built, 6 refused for asking more than 12 issues. Reward battery: 1,685 scripted submissions on 15 episodes. No repository file was modified except this one. `tools/independent_checker.py` was not read or used as evidence; where a harness verdict comes only from that line, the row says so.

## 1. Attack table

| # | Area | What I tried | Expected | Observed | Verdict |
|---|---|---|---|---|---|
| 1 | Truth validity | Wrote my own detector from SPEC 6 text (not from `families.py`), ran it on the 27 shipped case episodes and on 1,424 generated ones | Same issues, ids, amounts, currencies, evidence | Identical on all | HOLDS |
| 2 | Truth validity | Clean twin of each of the 1,424 episodes: built with no errors, both detectors | No issue | No issue in any | HOLDS |
| 3 | Truth validity | Rename ids and shuffle rows (2 seeds each, 1,424 episodes), re-derive truth with both detectors | Same truth after renaming | Same in all 2,848 | HOLDS |
| 4 | Truth validity | FX amounts recomputed with exact fractions and my own half-up | Equal to truth | Equal in all | HOLDS |
| 5 | Truth validity | `books.undo(provenance)` on every built episode versus its clean twin | Clean books | Equal in all 1,424 | HOLDS |
| 6 | Truth validity | Provenance `expected` versus truth | Equal | Equal in all 1,424 | HOLDS |
| 7 | Truth validity | Whole-minute timestamps, ledger in (time, row_id) order, ledger rows at company offset | As SPEC 6.0 says | True in all 1,424 | HOLDS |
| 8 | Hand-built history | On-disk books with a recorded allocation above the required one | Refused at load (SPEC 6.0) | Loaded and served by `reset`; `families.detect` refuses the same records | FAILS (F4) |
| 9 | Hand-built history | Refund of USD 300.00 on a USD 120.00 receipt; refund dated before its receipt | Refused (PC-29) | Both build, no issue | FAILS (F8) |
| 10 | Hand-built history | Count structure checks during a build with 5 errors | After every injected error (SPEC 6.0) | 2 versions of the books checked: clean and final | FAILS (F11) |
| 11 | Hand-built history | Invoice issued 23:59:59.5 on the last day; same invoice with lines reordered; receipt before `issued_at` | As SPEC says: after the period; not a duplicate; allocated normally | As SPEC says | HOLDS |
| 12 | Hand-built history | One receipt naming invoices of two customers | Undecided (OQ-16) | Builds silently, no issue | WEAK |
| 13 | Solvability | Evidence ids of every issue fetched one by one under `evidence_rule: observed` (15 episodes); reading cost of every generated episode | Retrievable; fits 100 steps | All retrievable; most steps to read everything 52; worst generated config I could build stays under 60 | HOLDS |
| 14 | Reward integrity | Per issue: wrong type, amount +1/-1/negated, wrong currency, evidence minus one id, empty evidence, 10 unrelated records, another issue's evidence, affected ids subset/superset/lower-case | No true positive | None earned one (1,000+ submissions) | HOLDS |
| 15 | Reward integrity | Evidence plus a real `invoice_id`, `payment_id` or an invented id | Finding voided | Voided | HOLDS |
| 16 | Reward integrity | Same finding twice; same issue with a superset of evidence; hedge filling the cap of 30 | One true positive, rest false positives | As expected | HOLDS |
| 17 | Reward integrity | 300 random orderings of mixed submissions | Same counts | Same counts | HOLDS |
| 18 | Interactions | FX plus allocation on one receipt: type swapped, amounts summed, allocation measured against the required translation, union evidence | Only the two exact findings match, each once | As expected | HOLDS |
| 19 | Interactions | Duplicate plus cutoff on one record: cutoff on the original, cutoff with both ids, duplicate with only the copy, doubled amount, cutoff evidence on the duplicate | No credit | No credit | HOLDS |
| 20 | Shortcuts | Duplicate from the ledger alone: two revenue credits, same customer, currency and amount, within four hours | F1 below 0.5 | F1 0.75 train, 0.80 dev, 0.82 on 434 fresh companies | FAILS (F6) |
| 21 | Shortcuts | Zero-step tell from the manifest: `ledger_rows > 1974` or `documents > 188` | No better than chance | Fires on 194 episodes, all 194 faulty; never on 403 clean | FAILS (F5) |
| 22 | Shortcuts | Printed-date FX, printed-date cutoff, same customer and total, issued_at string match, posting lag outside clean range, unapplied amount digit pattern, round row count | F1 below 0.5 | 0.26, 0.44, 0.33, 0.32, 0.00, 0.29; round row count 79% faulty against a 72% base rate | HOLDS |
| 23 | Shortcuts | Partial rules: duplicate by customer, instant and total; allocation on first receipt only | Reported if above 0.5 | 0.67 (dev 0.58, train 0.44); 0.89 (dev 0.88, train 0.75) | WEAK |
| 24 | Shortcuts | Diff of twin pairs `train_01`/`train_02`, `dev_03`/`dev_04` | Only what the errors touch | `episode_id`, `ledger_rows` (+1), 5 and 11 ledger lines; invoices, payments, fx, policy identical | HOLDS |
| 25 | Determinism | Regenerate all 31 shipped episodes and 3 fresh ones under PYTHONHASHSEED 0, 1, 4242, random on Python 3.11, 3.12, 3.13 | Identical bytes | Zero drift, one digest in all 8 runs | HOLDS |
| 26 | Determinism | Feed `provenance.json`'s recorded `generator` back into `shipped.generate` | The same episode | A different episode for 10 of 20 | FAILS (F1) |
| 27 | Leakage | With the public dev key, decide "clean" from `episode_id` alone, as a policy under seatbelt | SPEC says the dev key protects nothing | Proved clean and recovered the seed on 5 of 5 shipped clean episodes in 0.1 to 0.2 s, 0 inspection steps | WEAK (documented; see F9 for the silent default) |
| 28 | Leakage | Shipped `docs/trajectories.jsonl.gz`: private tokens, the draft's seven fields | None; all present | None; all present in 2,029 transitions | HOLDS |
| 29 | `generate --job` | Job naming one episode twice; later entry refused; non-JSON job; no secret file | Refuse, atomic, clean error, warn | Second silently replaces the first; earlier entries stay written; raw traceback; public key used silently | FAILS (F9) |
| 30 | `generate --job` | `../x`, absolute path, empty name, shipped name, name the loader refuses, unknown keys, missing seed | Refused before writing | Refused on the live tree | HOLDS (fixed during review) |
| 31 | `harness` | Truth edited: issue removed, amount +1, new real error in public records | FAIL | 3 lines fail, exit 1 | HOLDS |
| 32 | `harness` | Manifest tolerance 10^12; `page_limit` 2000, `max_steps` 100000, `max_findings` 100000; `policy.json` notes rewritten to the wrong rule | FAIL | 8/8 passed, exit 0 | FAILS (F2) |
| 33 | `harness` | Extra balanced journal entry; other-entry amounts x10; ledger and invoice files reversed | FAIL or documented as out of scope | 8/8 passed | WEAK |
| 34 | `harness` | Truth with an extra acceptable evidence set of 3 unrelated rows; provenance falsified; `issue_types` cut to one family | FAIL | Only the independent-checker line fails; pairs and investigator pass | WEAK |
| 35 | `harness` | `provenance.json` deleted | A FAIL line and a summary | Traceback, exit 1, no summary | FAILS (F10) |
| 36 | `harness` | Boundary probe on a root without `teaching_b`, no confinement | Reads reported as succeeded | Reported `denied:FileNotFoundError` | FAILS (F3) |
| 37 | `check` | Baseline on an untouched copy | All pass | 14/14, 24 s | HOLDS |
| 38 | `check` | Shipped public file edited; shipped truth edited | FAIL | Fail on the byte-for-byte line | HOLDS |
| 39 | `check` | `scale.json` falsified, sweep file emptied, a `truth.json` dropped into a public episode directory, answer key overwritten | FAIL | 14/14 passed | FAILS (F7) |
| 40 | `measure` | Run and compare deterministic fields with committed `scale.json` | Equal | Equal for 31 episodes; exit 0 | HOLDS |
| 41 | Contract at scale | Full paging of `dev_09` (1,982 rows) and `train_10`: order, cursors, step count | File order, 52 and 47 steps | Exact; 19 ms | HOLDS |
| 42 | Contract at scale | 12 bad cursors and 7 bad limits | Bounded error, one step each | `bad_cursor` / `bad_limit`; `ledger:0` also rejected; `ledger:00050` accepted | HOLDS (two nits in section 3) |
| 43 | Contract at scale | Step 100 inspection; submit on step 100; submit after the end; submit at 60.1 s; eval mode terminal step for right, empty and malformed | PC-3, PC-13, PC-16, PC-17 | As specified; eval terminal transitions identical | HOLDS |
| 44 | Contract at scale | `observed` rule with only the pages that hold the evidence; with one page | All matched; none matched | 12 of 12 with 13 pages; 0 of 12 | HOLDS |
| 45 | Documents | SPEC 6.7 fixture table, SPEC 7 seeds, bases, offsets, twin and clean counts, SPEC 10 values (1/3, 0.8, 1.0, -1, 0.984, 0.896, abstain means) | Match | All match | HOLDS |
| 46 | Documents | SPEC 6.6 "every generated company contains each of these" over 764 clean companies | None lacking | Four kinds lacking in 0.1% to 9.3% | FAILS (F11) |
| 47 | Documents | SPEC 7 "the count lands within about fifteen rows" of the target | True | True in the middle; target 2000 always gives 1973 or 1974; small targets with many invoices give up to +263 | FAILS (F11) |
| 48 | Draft requirements | Each family alone at 1 to 12 errors, each interaction at 1 to 3, 40 seeds each | Builds with exactly those issues | All build except FX above 4 on a default company (13 of 40 refused at 8) | HOLDS |
| 49 | Test suite | `pytest` on the 09:40 copy | Pass | Passed, 2 min 42 s | HOLDS |

## 2. Actual failures, most serious first

### F1. The generator input recorded in provenance does not regenerate the episode

`plan_errors` keys its random stream on the `inject` dict exactly as the caller spelled it. `shipped.generate` then writes a normalised form to provenance (zero counts dropped, `interactions: []` added). The two spellings give different errors. So the private half of a faulty episode does not contain what is needed to rebuild it, and two spellings of the same request are two different episodes.

```
uv run python - <<'EOF'
import json
from genesis_audit import shipped, paths
g = json.load(open(paths.PRIVATE_ROOT / "train_02" / "provenance.json"))["generator"]
pub, truth, _ = shipped.generate(g["seed"], g["config"], g["inject"])
print("recorded inject:", g["inject"])
print("on disk:", json.load(open(paths.PUBLIC_ROOT / "train_02" / "manifest.json"))["episode_id"], "| from provenance:", pub.manifest["episode_id"])
for spelling in ({"payment_allocation": 2}, {"payment_allocation": 2, "interactions": []}, {"payment_allocation": 2, "cutoff": 0}):
    print(spelling, "->", shipped.generate(g["seed"], g["config"], spelling)[0].manifest["episode_id"])
EOF
```

Observed:

```
recorded inject: {'payment_allocation': 2, 'interactions': []}
on disk: ep-7d8d04c7c2 | from provenance: ep-9aba218dc6
{'payment_allocation': 2} -> ep-7d8d04c7c2
{'payment_allocation': 2, 'interactions': []} -> ep-9aba218dc6
{'payment_allocation': 2, 'cutoff': 0} -> ep-14e1019409
```

Affected: `train_02`, `train_03`, `train_04`, `train_05`, `train_06`, `dev_01`, `dev_04`, `dev_05`, `dev_07`, `dev_09`. `check` does not see it because it regenerates from the dicts in `shipped.py`, not from provenance.

### F2. The harness passes on a root whose manifest and policy were edited to weaken the grader

On a held-out root nothing ties the public files to what the generator wrote. Tolerance, page limit, step budget, findings cap and the rule text given to the policy can all be changed and every line still passes.

```
T=$(mktemp -d); mkdir -p $T/public $T/private
for e in fixture_fx train_02 dev_04; do cp -R episodes/public/$e $T/public/; cp -R episodes/private/$e $T/private/; done
python3 - "$T" <<'EOF'
import json, pathlib, sys
for m in pathlib.Path(sys.argv[1], "public").glob("*/manifest.json"):
    d = json.loads(m.read_text()); d["amount_tolerance_minor"] = {k: 10**12 for k in d["amount_tolerance_minor"]}
    d["limits"].update(max_steps=100000, page_limit=2000, max_findings=100000); m.write_text(json.dumps(d, indent=2) + "\n")
for p in pathlib.Path(sys.argv[1], "public").glob("*/policy.json"):
    d = json.loads(p.read_text()); d["fx"]["note"] = "Use the rate of the date printed on the receipt. Always divide."
    d["cutoff"]["note"] = "Compare the dates as printed."; p.write_text(json.dumps(d, indent=2) + "\n")
EOF
GENESIS_AUDIT_PUBLIC_ROOT=$T/public GENESIS_AUDIT_PRIVATE_ROOT=$T/private uv run python -m genesis_audit harness; echo exit=$?
```

Observed: `8/8 checks passed`, `exit=0`. On that root one `list_records` call with `limit: 2000` returned all 444 ledger rows of `dev_04`, and the three true findings with every amount claimed as 1 scored `{'tp': 3, 'fp': 0, 'fn': 0}`, reward 0.998.

### F3. The boundary probe proves nothing on a held-out root

`probe_in_process` aims four of its attempts at `teaching_b` files. On a root without that episode the files do not exist, and the probe reports the missing file as a denial. The same answer appears with no confinement at all.

```
GENESIS_AUDIT_PUBLIC_ROOT=$T/public GENESIS_AUDIT_PRIVATE_ROOT=$T/private uv run python -m genesis_audit probe --confine none
```

Observed: `read_truth`, `stat_truth`, `list_private`, `read_public_file` all `denied:FileNotFoundError`, `held: true`, while `write_file` and `read_source` are `ok`. On the shipped root the same command reports all four as `ok`. Under a real backend the harness line "hostile probe denied on all 11 attempts" therefore counts four attempts that could not have succeeded. I did not find a backend misconfiguration that this hides; the point is that the probe would not notice one.

### F4. A recorded allocation above the required one is accepted at load

SPEC 6.0 lists it among the things "refused at build and at load". The loader does not check it; only `families.detect` does.

```
uv run python - <<'EOF'
import shutil, tempfile
from pathlib import Path
from genesis_audit import families, paths
from genesis_audit.episodes import DirectorySource
from genesis_audit.env import AuditEnv
T = Path(tempfile.mkdtemp())
for half, root in (("public", paths.PUBLIC_ROOT), ("private", paths.PRIVATE_ROOT)):
    shutil.copytree(root / "fixture_clean", T / half / "over_alloc")
p = T / "public/over_alloc/ledger.csv"; out = []
for line in p.read_text().splitlines():   # P27 pays 230,000 on a 200,000 invoice: record 210,000 applied
    f = line.split(",")
    if f[-1] == "P27" and f[2] == "accounts_receivable": f[4] = "210000"
    elif f[-1] == "P27" and f[2] == "unapplied_receipts" and f[4] != "0": f[4] = "20000"
    elif f[-1] == "P27" and f[2] == "unapplied_receipts" and f[3] != "0": f[3] = "20000"
    elif f[-1] == "P27" and f[2] == "bank" and f[4] != "0": f[4] = "20000"
    out.append(",".join(f))
p.write_text("\n".join(out) + "\n")
src = DirectorySource(T / "public", T / "private")
loaded = src.load("over_alloc"); print("load: accepted")
print("reset:", AuditEnv(src).reset(config={"episode": "over_alloc"})[0]["steps_remaining"], "steps")
families.detect(loaded.public)
EOF
```

Observed: `load: accepted`, `reset: 100 steps`, then `EpisodeError: over-allocation: more was applied than the policy allows, which no convention here covers`. On that root the harness prints `PASS every episode loads: files consistent, posting structure holds, truth expressible`, then stops with exit 2 and no summary.

### F5. The manifest tells a policy, before any step, that the largest companies are faulty

A clean company is capped at 1,974 ledger rows and 188 documents (`ROW_ROOM`, `DOCUMENT_ROOM`). Errors add rows and documents on top. So a count above either cap is only ever seen on faulty books.

```
uv run python - <<'EOF'
from genesis_audit import shipped
cfg = {"invoices": 100, "ledger_rows": 2000}
for inject in ({}, {"duplicate_invoice": 1}, {"payment_allocation": 2}, {"cutoff": 2}):
    c = [shipped.generate(s, cfg, inject, secret=b"any-private-key-0123456789")[0].manifest["counts"] for s in range(20)]
    print(inject, sorted({x["ledger_rows"] for x in c}))
EOF
```

Observed:

```
{} [1973, 1974]
{'duplicate_invoice': 1} [1975, 1976]
{'payment_allocation': 2} [1974, 1975, 1976]
{'cutoff': 2} [1973, 1974]
```

Over the sweep: the test `ledger_rows > 1974 or documents > 188` fired on 194 episodes, all faulty, and on none of 403 clean ones. Among companies with target 2,000 it fired on 125 of 128 faulty and 0 of 60 clean. Shipped `dev_09` (1,982 rows, 191 documents) is an instance. The tell is one-sided: it never says a company is clean.

### F6. Duplicates are found at F1 0.75 to 0.82 without applying the duplicate rule

A copy is always posted within 3 to 240 minutes of its original. Two revenue credits with the same customer, currency and amount inside four hours are a duplicate most of the time. The heuristic never looks at `issued_at`, `due_at` or `line_items`.

```
uv run python - <<'EOF'
from datetime import datetime, timedelta
from genesis_audit import shipped, paths
from genesis_audit.episodes import DirectorySource
src = DirectorySource(paths.PUBLIC_ROOT, paths.PRIVATE_ROOT)
when = datetime.fromisoformat
for split in ("train", "dev"):
    tp = fp = fn = 0
    for name in shipped.SPLITS[split]:
        ep = src.load(name); pub = ep.public
        doc = {i["invoice_id"]: i["doc_id"] for i in pub.tables["invoices"]}
        rev = sorted((r for r in pub.tables["ledger"] if r["account"] == "revenue" and r["invoice_id"]), key=lambda r: when(r["timestamp"]))
        claims = set()
        for a, x in enumerate(rev):
            for y in rev[a + 1:]:
                if when(y["timestamp"]) - when(x["timestamp"]) > timedelta(hours=4): break
                if (x["entity_id"], x["currency"], x["credit_minor"]) == (y["entity_id"], y["currency"], y["credit_minor"]):
                    claims.add((frozenset([x["invoice_id"], y["invoice_id"]]), x["credit_minor"], x["currency"], frozenset([doc[x["invoice_id"]], doc[y["invoice_id"]]])))
        truth = {(t.affected_ids, t.expected_amount_minor, t.currency, t.acceptable_evidence_sets[0]) for t in ep.truth if t.type == "duplicate_invoice"}
        tp += len(claims & truth); fp += len(claims - truth); fn += len(truth - claims)
    print(split, "tp", tp, "fp", fp, "fn", fn, "F1", round(2 * tp / (2 * tp + fp + fn), 3))
EOF
```

Observed: `train tp 3 fp 1 fn 1 F1 0.75`, `dev tp 6 fp 2 fn 1 F1 0.8`. On 434 fresh companies: tp 399, fp 121, fn 57, precision 0.767, recall 0.875, F1 0.818. It is not cheaper in steps than the rule (it reads the ledger, the rule reads only invoices); it is a surface regularity that only copies have.

### F7. `check` passes with falsified measurements and a truth file in a public directory

`cmd_check` says it "re-measures everything this repository reports". It does not look at `docs/measurements/`, which SPEC PC-36 cites, and it does not notice files that should not be there.

```
T=$(mktemp -d); rsync -a --exclude .venv --exclude .git --exclude out ./ $T/
python3 - "$T" <<'EOF'
import json, pathlib, sys
c = pathlib.Path(sys.argv[1])
(c / "episodes/public/train_01/truth.json").write_text((c / "episodes/private/train_02/truth.json").read_text())
s = json.loads((c / "docs/measurements/scale.json").read_text()); s["within_envelope"] = False
for e in s["episodes"].values(): e["solver_f1"] = 0.0; e["steps_to_read_everything"] = 1
(c / "docs/measurements/scale.json").write_text(json.dumps(s, indent=2) + "\n")
(c / "docs/measurements/random_inspector_sweep.json").write_text("{}\n")
(c / "episodes/private/fixture_clean/ANSWER_KEY.md").write_text("all wrong\n")
EOF
PYTHONPATH=$T/src .venv/bin/python -m genesis_audit check
```

Observed: `14/14 checks passed`.

### F8. Refund checks compare across currencies and ignore time

PC-29 says a refund is "never more than that receipt's unapplied credit" and comes "at any later time". `validate_books` compares minor units without looking at the currency, and never compares timestamps. `derive` posts a refund in the receipt currency while the unapplied credit is in the invoice currency.

```
uv run python - <<'EOF'
import copy
from genesis_audit import books, shipped
w = copy.deepcopy(dict(shipped.FIXTURE_WORLD))
next(p for p in w["payments"] if p["payment_id"] == "P31")["amount_minor"] = 12000      # USD 120.00, leaves KZT 10,000.00 unapplied
w["refunds"] = [*w["refunds"], {"payment_id": "P31", "timestamp": "2026-10-25T12:00:00+05:00", "amount_minor": 30000}]  # refund USD 300.00
print(len(books.build(w, [])[1]), "issues, built")
w = copy.deepcopy(dict(shipped.FIXTURE_WORLD))
w["refunds"] = [{"payment_id": "P27", "timestamp": "2026-10-02T12:00:00+05:00", "amount_minor": 30000}]                 # receipt P27 is dated 3 Nov
print(len(books.build(w, [])[1]), "issues, built")
EOF
```

Observed: both print `0 issues, built`. The generator never writes a cross-currency refund, so shipped and generated episodes are not affected.

### F9. `generate --job`: silent overwrite inside one job, partial writes, raw traceback, silent public key

```
T=$(mktemp -d); export GENESIS_AUDIT_PUBLIC_ROOT=$T/pub GENESIS_AUDIT_PRIVATE_ROOT=$T/priv
echo '{"episodes": [{"name": "twice", "seed": 1}, {"name": "twice", "seed": 2, "inject": {"cutoff": 1}}]}' > $T/j1.json
echo '{"episodes": [{"name": "a_ok", "seed": 1}, {"name": "b_bad", "seed": 2, "inject": {"duplicate_invoice": 13}}, {"name": "c_never", "seed": 3}]}' > $T/j2.json
echo 'not json' > $T/j3.json
for j in j1 j2 j3; do uv run python -m genesis_audit generate --job $T/$j.json; echo exit=$?; done; ls $T/pub
```

Observed:

- `j1`: two "generated one episode" lines, exit 0; the seed on disk for `twice` is 2. The first episode is gone, although the command's own refusal text says "generate never overwrites".
- `j2`: `a_ok` written, then `EpisodeError: b_bad: issues = 13 is outside the case envelope 0..12`, exit 2. `a_ok` stays; `c_never` is never written.
- `j3`: `json.decoder.JSONDecodeError` traceback, exit 1.
- With no `GENESIS_AUDIT_SECRET_FILE`, every run above used the public dev key and printed nothing about it. On such an episode a policy can prove "clean" from `episode_id` alone (row 27).

### F10. The harness crashes instead of failing when `provenance.json` is missing

```
rm $T/private/train_02/provenance.json     # the root from F2
GENESIS_AUDIT_PUBLIC_ROOT=$T/public GENESIS_AUDIT_PRIVATE_ROOT=$T/private uv run python -m genesis_audit harness; echo exit=$?
```

Observed: five result lines, then `FileNotFoundError: ... /private/train_02/provenance.json` from `leaked_tokens`, exit 1, no "n/m checks passed" line. `labels_of` was changed during the review to survive a missing file; `leaked_tokens` was not.

### F11. Three SPEC statements the code does not keep

- **6.0: "These checks run on the clean books and again after every injected error."** A build with 5 errors records 5 injections and calls `validate_books` 3 times, on 2 distinct versions of the books (row counts 45, 45, 48). Intermediate versions are never checked.
- **6.6: "Every generated company contains each of these."** Over 764 distinct clean companies: no receipt quoted the other way (divide) in 71 (9.3%); no receipt that names no invoice in 62 (8.1%, and 62 of the 78 companies at 186 documents or more, because the document cap drops them); no identical invoices to two customers in 2 (0.3%); no double payment in 1 (0.1%). Examples under key `b"reviewer-private-secret-0001"`: seed 3000 with `{"base_currency": "USD", "foreign_currencies": ["JPY"], "timezone": "UTC", "period": "2026-Q2", "invoices": 105, "ledger_rows": 2000}` has 188 documents and 0 receipts with empty `invoice_refs`; seed 1006 with `{"base_currency": "KZT", "foreign_currencies": ["EUR"], "timezone": "Asia/Almaty", "period": "2026-02", "invoices": 20, "ledger_rows": 400}` has 3 cross-currency receipts, none of them a divide.
- **7: "`ledger_rows` is a target: the count lands within about fifteen rows of it."** True for 908 of 908 mid-range companies. With target 2,000 all 188 companies landed on 1,973 or 1,974 (26 or 27 short). With small targets and many invoices the count ran up to 263 over. Also, `invoices` is a floor: 12 gives 21 or 22 invoices.

### Reproduced on an earlier copy, fixed on the live tree by 09:49

Listed so they are not re-reported; I did not find them still open.

- `generate --job` wrote outside the roots for `../x` and absolute names (both halves in one directory), wrote loose files into the root for an empty name, replaced a shipped name, and accepted names the loader refuses. All now refused before writing.
- Job files with a wrong top-level key, a missing seed or unknown keys gave `KeyError` tracebacks. Now a `LifecycleError`.
- Split payments and overpayments were missing in up to 20% of very small companies. Now present in all 764.
- Before 09:27, clean row counts sat on the target or one below it, so a round count marked clean books. The jitter added since removes that (round-count test now 79% against a 72% base rate).

## 3. Weak spots that are not failures

- **The engine-side harness lines do not cover truth evidence, provenance or `issue_types`.** An extra bogus acceptable evidence set, falsified provenance and a manifest cut to one family (with truth cut to match) each pass the pairs and investigator lines. Only the independent-checker line fails, and that file was being rewritten during this review.
- **Harmless edits to public records pass the harness** (extra balanced journal entry, other-entry amounts x10, files reversed). No rule is touched, so this may be acceptable; SPEC 9 does not say either way.
- **The reference solver hardcodes the rules.** `reconciliation.py` reads account names from the policy and nothing else, which is why F2's rewritten notes go unnoticed.
- **Partial rules go a long way.** Allocation checked on the first receipt of an invoice only: precision 1.0, F1 0.89 fresh, 0.88 dev, 0.75 train. The ordering and open-balance rule decides about one allocation error in five. Duplicate by customer, instant and total: F1 0.67 fresh, 0.58 dev, 0.44 train; one decoy pair per company is all that stands against it.
- **Dev key.** Under the public key a policy proves a company clean from `episode_id` with HMAC alone, no world generated: 0.1 to 0.2 s for shipped seeds, about 1,600 seeds per second across 700 to 1,800 candidate settings. SPEC 7 says the key protects nothing but not that the test is this cheap.
- **Cursors.** `ledger:0` is `bad_cursor` and costs a step, though PC-4 calls a cursor a plain offset. `ledger:00050` is accepted as an alias of `ledger:50`.
- **Sheet labels follow the name, not the provenance.** An episode directory named like a shipped one gets the shipped split and status in `--sheet`. `generate` now refuses such names, so it needs a hand-made root.
- **OQ-16 is live in code.** A receipt for invoices of two customers builds with no issue and takes the first invoice's customer on its rows.
- **FX capacity.** A default company holds about 5 mistranslatable receipts: `{"fx_mismatch": 8}` was refused on 13 of 40 seeds, and a refusal mid-job leaves earlier entries written (F9).
- **Hand-built episodes are outside the draft's size envelope.** Fixtures have 45 to 47 rows and 17 or 18 documents; teaching episodes 12 rows and 5 documents. SPEC 6.7 states the sizes.
- **Draft requirement "vary names, timezones".** The schema has no entity names; line descriptions come from a fixed list of 12. All seven zones are fixed-offset, so daylight saving is never exercised (SPEC says so).

Draft requirements otherwise met: four families configurable on their own; three interaction scenarios; clean companies; split payments, refunds and repeated amounts in every company on the live tree; 200 to 2,000 rows, 20 to 200 documents, 0 to 12 issues on all generated episodes; 10 train and 10 dev (18 companies); the four baselines plus three more; trajectories with the seven required fields.

## 4. What I did not test

- Linux, Docker and setuid backends. Everything ran on macOS arm64 under `seatbelt` or in-process.
- The draft's hardware envelope (2 cores, 4 GB). I only confirmed `measure` reports 0.06 s for the slowest episode and 68 MB peak on this machine.
- `tools/independent_checker.py`, by instruction.
- The bridge protocol at scale beyond what the harness and my one hostile policy exercise; paging attacks were run in-process against `AuditEnv`.
- Timing side channels, and process command lines during `generate` (seeds are in the job file, not on argv; I read the re-exec code but did not sample `ps`).
- A full `harness` run on a root generated under a private secret file. Private keys were used through the Python API only.
- More than two perturbation seeds per episode.
- The teaching slice, the tutor pages, README and NOTES claims, and the Russian and Kazakh text of the draft.
- Any tree state after 09:52.


---

## Author's response (not the reviewer's)

Everything above this line was written by the independent reviewer and is unchanged. This section is mine. The reviewer has not re-checked it.

| # | Failure | What I did | Pinned by |
|---|---|---|---|
| 1 | Recorded settings did not regenerate 10 of 20 episodes | The error stream is keyed on `inject` in one fixed spelling, the same one provenance stores | `test_the_recorded_settings_regenerate_the_episode` (all 20), `test_how_inject_is_spelled_does_not_change_the_episode` |
| 2 | Harness passed on a root with a weakened grader | The contract of a case episode is fixed by its version: published policy text word for word, the draft's budget and caps, all four families, tolerance 0. Any manifest limit above the draft's is refused for every episode | `test_a_root_with_a_weakened_grader_does_not_load` (5 cases), `test_truth_inside_the_tolerance_is_refused` |
| 3 | Boundary probe vacuous on held-out roots | The probe is aimed at an episode that exists under the root, and fails if there is none | `test_the_boundary_probe_aims_at_an_episode_that_exists` |
| 4 | Over-allocation loaded | The loader now derives truth with the published rules and compares it with `truth.json`; whatever the rules refuse does not load | `test_over_allocation_is_refused_at_load` |
| 5 | Row and document counts above a fixed margin meant "faulty" | Each company draws its own margin from its seed, so clean companies reach past any fixed threshold; one at the very edge whose errors do not fit is refused | `test_the_size_envelope_of_the_draft_is_enforced` |
| 6 | Posting proximity found duplicates (F1 0.75 to 0.82) | A copy is posted whenever, like any invoice. Every company has two valid pairs of one customer at one instant that are keyed in together, one differing only in a line description. The shortcut now scores F1 0.00 on train and dev (0 of 11 found, 40 false pairs) | `test_proximity_of_postings_does_not_find_duplicates`, `test_part_of_the_duplicate_rule_is_not_enough` |
| 7 | `check` passed with falsified measurements and stray files | `check` re-measures: everything in `scale.json` that is not a clock or memory reading must match, and the sweep must be consistent with a re-run of its first seeds. A file that does not belong in the public or private half of an episode is refused at load. The hand-written answer keys are prose and are still not checked | `test_falsified_measurements_and_stray_files_are_noticed` |
| 8 | Refund in another currency, or before its receipt | Refused: a refund is in the receipt's currency, later than the receipt, and not of a translated receipt | `test_refunds_outside_the_convention_are_refused` |
| 9 | `generate --job`: repeated name, partial writes, traceback, silent public key | Names are checked first; everything is built before anything is written; a bad file is a one-line error; the public key is announced on stderr | `test_generate_is_all_or_nothing_and_says_which_key_it_used`, `test_generate_refuses_unsafe_job_files` |
| 10 | Harness crashed on a missing `provenance.json` | A missing or unreadable private half is a refusal at load, and the harness reports it as a failed check | `test_harness_reports_a_root_that_does_not_load_instead_of_crashing` |
| 11 | Three SPEC statements the code did not keep | Structure is validated after every single error. Every look-alike kind is placed on purpose whatever the seed, including a translation that divides, a receipt that names no invoice and a two-customer pair. The row-target sentence now says what the code does | `test_structure_is_checked_after_every_single_error`, `test_any_seed_builds_a_valid_company_or_is_refused_cleanly`, `test_every_company_holds_valid_look_alikes_of_every_family` |

Weak spots acted on: an extra evidence set or a missing issue in `truth.json` is now refused by the loader as well as by the independent checker; a receipt for invoices of two customers is refused; a cursor is accepted only as the environment writes it; SPEC section 7 now says how cheaply the public key identifies a shipped episode.

Weak spots left as they are, on purpose: the reference solver is a script that hard-codes the rules; harmless edits to public files (extra balanced rows) still make a valid episode; a policy that implements most of a rule scores partly; there are no entity names and no daylight-saving zones; falsified provenance is caught only by the independent checker.
