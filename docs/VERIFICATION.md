# Verification log

Written by `python tools/write_verification.py`. Every block is the tail of a command that was run on
the tree named below. Nothing here is typed in by hand.

- **Tree digest:** `f039161ec8f814502d194f1b1a4af9a8532f17dcba1b9a63dc115d89d8e8c135` over 403 files (everything git would commit, this log excluded).
- **Tree unchanged by the run:** yes.
- **Host:** Darwin arm64, Python 3.12.8 for this script.
- **Git state when run:** HEAD `50d34a9` on `main`, working tree clean apart from this log.
  The digest above identifies the tree whether or not it is committed. Recompute it with `tree_digest` in this script.
- **Result:** 7 of 7 commands exited 0.

### Lint, format and types

`make lint` -> **exit 0**

```
uv run ruff check src tests policies tools baselines judge_adapter.py
All checks passed!
uv run ruff format --check src tests policies tools baselines judge_adapter.py
108 files already formatted
uv run mypy src
Success: no issues found in 33 source files
```

### Tests with coverage (gate 80%)

`make test` -> **exit 0**

```
src/genesis_audit/prng.py            36      0      8      1    98%   43->41
src/genesis_audit/sandbox.py        104     15     38      8    78%   76->78, 79, 81, 89, 154, 158, 163-167, 180, 185-188
src/genesis_audit/schemas.py         72      1     36      0    99%   51
src/genesis_audit/shipped.py         99     11     22      1    85%   247, 270-279
src/genesis_audit/store.py          365      6    110      3    98%   84-85, 262, 276->279, 328, 384-385
src/genesis_audit/teaching.py       139     11     40      2    89%   151->149, 183, 351-360
src/genesis_audit/truth.py          100      6     48      4    93%   55, 80, 119, 121, 156-157
src/genesis_audit/tutor/core.py     130      3     44      4    96%   41, 78-79, 107->113, 144->147, 150->148
src/genesis_audit/world.py          572     15    210     16    96%   179, 314, 316, 430->420, 469, 499, 560->518, 702-703, 704->699, 706, 827-828, 869->865, 880, 904, 918, 929, 964
-----------------------------------------------------------------------------
TOTAL                              4105    215   1224     83    94%
9 files skipped due to complete coverage.
Required test coverage of 80% reached. Total coverage: 93.77%
1245 passed, 2 skipped in 324.62s (0:05:24)
```

### Self-check on this machine

`uv run python -m genesis_audit check` -> **exit 0**

```
PASS  every episode loads: files consistent, posting structure holds, truth expressible: 31 episodes
PASS  independent checker re-derives the truth of every episode from public records: 31 episodes, 62 issues re-derived
PASS  the oracle scores 1.0 everywhere, and fetching every evidence record fits the step budget: 31 episodes, most evidence fetches in one episode: 30
PASS  every run replays to the same digest and score: 248 replays
PASS  nothing private in policy-visible trajectories: no private token found
PASS  id-renaming and row-order pairs preserve oracle findings and reward: 107 pairs, 20 of them on generated episodes
PASS  a truth-blind investigator finds every issue on every episode, and a memoriser fails the control: F1 = 1 on 138 runs incl. perturbed twins, worst reward 0.896 (reading cost only); memoriser -1.000 vs abstain -1.000 on the variant it has not seen
PASS  docs/RESULTS.md is reproduced exactly: 248 runs re-measured
PASS  docs/DIGESTS.json is reproduced exactly: 248 transition digests and exact rewards
PASS  docs/trajectories.jsonl.gz is reproduced exactly: 2022 transitions of 248 runs, policy-visible fields only
PASS  docs/measurements/scale.json agrees with a fresh measurement, and that is inside the envelope: 52 steps at most to read an episode in full; slowest solver episode 0.07 s of 60; clock and memory readings are not compared
PASS  docs/measurements/random_inspector_sweep.json is consistent with a re-run of its first seeds: 12 seeds on each teaching episode, each reward found in the stored histogram
PASS  truth-blind policies keep their counts and steps under id renaming and row shuffling: 5 policies x 4 teaching episodes x 3 seeds
16/16 checks passed
```

### Self-check under Python 3.12 (no virtual environment)

`/usr/local/bin/python3.12 -m genesis_audit check` -> **exit 0**

```
PASS  every episode loads: files consistent, posting structure holds, truth expressible: 31 episodes
PASS  independent checker re-derives the truth of every episode from public records: 31 episodes, 62 issues re-derived
PASS  the oracle scores 1.0 everywhere, and fetching every evidence record fits the step budget: 31 episodes, most evidence fetches in one episode: 30
PASS  every run replays to the same digest and score: 248 replays
PASS  nothing private in policy-visible trajectories: no private token found
PASS  id-renaming and row-order pairs preserve oracle findings and reward: 107 pairs, 20 of them on generated episodes
PASS  a truth-blind investigator finds every issue on every episode, and a memoriser fails the control: F1 = 1 on 138 runs incl. perturbed twins, worst reward 0.896 (reading cost only); memoriser -1.000 vs abstain -1.000 on the variant it has not seen
PASS  docs/RESULTS.md is reproduced exactly: 248 runs re-measured
PASS  docs/DIGESTS.json is reproduced exactly: 248 transition digests and exact rewards
PASS  docs/trajectories.jsonl.gz is reproduced exactly: 2022 transitions of 248 runs, policy-visible fields only
PASS  docs/measurements/scale.json agrees with a fresh measurement, and that is inside the envelope: 52 steps at most to read an episode in full; slowest solver episode 0.09 s of 60; clock and memory readings are not compared
PASS  docs/measurements/random_inspector_sweep.json is consistent with a re-run of its first seeds: 12 seeds on each teaching episode, each reward found in the stored histogram
PASS  truth-blind policies keep their counts and steps under id renaming and row shuffling: 5 policies x 4 teaching episodes x 3 seeds
16/16 checks passed
```

### Self-check under Python 3.13 (no virtual environment)

`/opt/homebrew/bin/python3.13 -m genesis_audit check` -> **exit 0**

```
PASS  every episode loads: files consistent, posting structure holds, truth expressible: 31 episodes
PASS  independent checker re-derives the truth of every episode from public records: 31 episodes, 62 issues re-derived
PASS  the oracle scores 1.0 everywhere, and fetching every evidence record fits the step budget: 31 episodes, most evidence fetches in one episode: 30
PASS  every run replays to the same digest and score: 248 replays
PASS  nothing private in policy-visible trajectories: no private token found
PASS  id-renaming and row-order pairs preserve oracle findings and reward: 107 pairs, 20 of them on generated episodes
PASS  a truth-blind investigator finds every issue on every episode, and a memoriser fails the control: F1 = 1 on 138 runs incl. perturbed twins, worst reward 0.896 (reading cost only); memoriser -1.000 vs abstain -1.000 on the variant it has not seen
PASS  docs/RESULTS.md is reproduced exactly: 248 runs re-measured
PASS  docs/DIGESTS.json is reproduced exactly: 248 transition digests and exact rewards
PASS  docs/trajectories.jsonl.gz is reproduced exactly: 2022 transitions of 248 runs, policy-visible fields only
PASS  docs/measurements/scale.json agrees with a fresh measurement, and that is inside the envelope: 52 steps at most to read an episode in full; slowest solver episode 0.08 s of 60; clock and memory readings are not compared
PASS  docs/measurements/random_inspector_sweep.json is consistent with a re-run of its first seeds: 12 seeds on each teaching episode, each reward found in the stored histogram
PASS  truth-blind policies keep their counts and steps under id renaming and row shuffling: 5 policies x 4 teaching episodes x 3 seeds
16/16 checks passed
```

### Container: Python 3.11, no network, 60s limit; evaluator as root, policies under setuid

`make docker-check` -> **exit 0**

```
1241 passed, 6 skipped in 340.35s (0:05:40)
65 passed in 0.50s
16/16 checks passed
...
  "peak_resident_bytes": {
    "evaluator": 43474944,
    "largest_policy_process": 27979776
  },
  "slowest_solver_episode_seconds": 0.1245,
  "most_steps_to_read_everything": 52,
  "within_envelope": true,
  "episodes": {
    "teaching_b": {
      "ledger_rows": 12,
      "documents": 5,
DEPRECATED: The legacy builder is deprecated and will be removed in a future release.
            Install the buildx component to build images with BuildKit:
            https://docs.docker.com/go/buildx/
```

### Per-policy Docker backend: hostile probe

`uv run pytest -p no:cacheprovider tests/test_boundary.py -k docker` -> **exit 0**

```
.                                                                        [100%]
1 passed, 11 deselected in 0.43s
```
