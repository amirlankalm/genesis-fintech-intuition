"""Organizer-style baseline policies that play only through judge_adapter.make_env() with the official envelope.

Each module exposes `run(env, observation, ...)`: it plays one episode from the first observation returned by
`env.reset(...)` until the episode ends. They see nothing but observations, except `oracle`, which is jury side.

- random_explorer: random tool calls with a fixed seed, then a random small submission
- simple_reconciliation: the shortest rule per family, ignoring the policy text (policies/reconciliation_naive.py)
- flag_all: accuse every candidate of every family up to the 30-finding cap (policies/flag_all.py)
- oracle: submits the truth (judge_adapter.oracle_findings) with no inspection; jury side only
- reconciliation: the published rules applied to what the tools return (policies/reconciliation.py), an extra
"""
