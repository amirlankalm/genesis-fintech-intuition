# Verification log

Written by `make reproduce` (calling `python tools/write_verification.py`). Every block is the tail of a command
that was run on the tree named below. Nothing here is typed in by hand.

- **Commit SHA:** `3cfefaa8e76e584e8f290e3dcb7784769b90ac1b`
- **Date:** 2026-11-21 12:56:47 UTC
- **Tree digest:** `b677234ecef710e3fa091f9911a42ec87a7641139bf9fa41a97c705129ea7d77` over 404 files (everything git would commit, this log excluded).
- **Tree unchanged by the run:** yes.
- **Host:** Darwin arm64, Python 3.11.15 for this script.
- **Git state when run:** HEAD `3cfefaa` on `main`, 2 uncommitted path(s) on top of it.
  The digest above identifies the tree whether or not it is committed. Recompute it with `tree_digest` in this script.
- **Result:** 9 of 9 commands exited 0.

### Lint, format and types

`make lint` -> **exit 0**

```
uv run ruff check src tests policies tools baselines judge_adapter.py
All checks passed!
uv run ruff format --check src tests policies tools baselines judge_adapter.py
109 files already formatted
uv run mypy src
Success: no issues found in 33 source files
```

### Tests with coverage (gate 80%)

`make test` -> **exit 0**

```
src/genesis_audit/cli.py            436     77     94     11    82%   79, 83-95, 99-106, 123, 135, 196->198, 202-206, 231-235, 245-246, 259-260, 283, 302-303, 307, 357-366, 382-384, 388, 406, 483->486, 502-506, 535-537, 542-544, 626-639
src/genesis_audit/env.py            257      2     54      1    99%   99-100, 402->404
src/genesis_audit/episodes.py        99      3     14      1    96%   94-95, 137
src/genesis_audit/errors.py          16      1      2      1    89%   31
src/genesis_audit/evaluate.py       304     14     56      5    94%   64-71, 453->460, 528->538, 577, 601, 613-614, 650-651
src/genesis_audit/families.py       235      7     72      7    95%   312, 322, 347, 350, 365, 399, 451
src/genesis_audit/matching.py       105      1     36      1    99%   103
src/genesis_audit/money.py           60      2     32      0    98%   29-30
src/genesis_audit/paths.py           15      1      4      1    89%   29
src/genesis_audit/perturb.py         40      1     10      1    96%   50
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
1249 passed, 2 skipped in 298.36s (0:04:58)
```

### Self-check on this machine

`uv run python -m genesis_audit check` -> **exit 0**

```
PASS  every shipped episode regenerates byte for byte from its seed or its hand-written history: 31 episodes, no drift
PASS  the episode root holds every shipped episode: 31 found; teaching 4, fixture 7, train 10, dev 10
PASS  boundary holds under 'seatbelt': hostile probe denied on all 11 attempts that must fail; known gap, not closable on this backend: read_evaluator_environ
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

### Isolation and boundary probe (Seatbelt, Docker, Process)

`uv run pytest -p no:cacheprovider tests/test_boundary.py` -> **exit 0**

```
....ss......                                                             [100%]
10 passed, 2 skipped in 1.12s
```

### Replay and paired perturbation checks

`uv run pytest -p no:cacheprovider tests/test_bridge.py tests/test_perturb.py -k replay or perturb or twin` -> **exit 0**

```
.............                                                            [100%]
13 passed, 58 deselected in 5.47s
```

### Self-check under Python 3.12 (no virtual environment)

`/usr/local/bin/python3.12 -m genesis_audit check` -> **exit 0**

```
PASS  every shipped episode regenerates byte for byte from its seed or its hand-written history: 31 episodes, no drift
PASS  the episode root holds every shipped episode: 31 found; teaching 4, fixture 7, train 10, dev 10
PASS  boundary holds under 'seatbelt': hostile probe denied on all 11 attempts that must fail; known gap, not closable on this backend: read_evaluator_environ
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
PASS  every shipped episode regenerates byte for byte from its seed or its hand-written history: 31 episodes, no drift
PASS  the episode root holds every shipped episode: 31 found; teaching 4, fixture 7, train 10, dev 10
PASS  boundary holds under 'seatbelt': hostile probe denied on all 11 attempts that must fail; known gap, not closable on this backend: read_evaluator_environ
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
1245 passed, 6 skipped in 360.36s (0:06:00)
65 passed in 0.49s
16/16 checks passed
...
  "envelope": {
    "seconds_per_episode": 60,
    "memory_bytes": 4294967296,
    "max_steps": 100
  },
  "largest_episode": "train_10",
  "build_largest_from_seed": {
    "seconds": 1.5104,
    "peak_python_bytes": 9018734
  },
  "peak_resident_bytes": {
    "evaluator": 43548672,
    "largest_policy_process": 27987968
  },
  "slowest_solver_episode_seconds": 0.1111,
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
1 passed, 11 deselected in 0.37s
```
