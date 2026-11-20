from __future__ import annotations

import json
from collections import Counter

import pytest
from helpers import CLEAN, EVIDENCE, FAULTY, FAULTY_ID, finding, submit_action

from genesis_audit import evaluate, paths
from genesis_audit.env import DEV_SECRET, AuditEnv, DirectorySource
from genesis_audit.prng import KeyedStream, keyed_hex

BOTH = {"rename_ids": True, "shuffle_rows": True}
KNOWN_BELOW = [216, 37, 606, 825, 91]
KNOWN_SHUFFLE = [1, 0, 2, 4, 5, 3, 7, 8, 9, 6]
KNOWN_TOKEN = "AFGBDFDG"
KNOWN_HEX = "8e224d7c63bb"


def make(secret: bytes = DEV_SECRET) -> AuditEnv:
    return AuditEnv(DirectorySource(paths.PUBLIC_ROOT, paths.PRIVATE_ROOT), secret=secret)


def perturbed(seed: int, options: dict | None = None, secret: bytes = DEV_SECRET, episode: str = FAULTY) -> AuditEnv:
    env = make(secret)
    env.reset(seed, {"episode": episode, "perturb": options or BOTH})
    return env


def ledger(env: AuditEnv) -> list[dict]:
    return [dict(row) for row in env.evaluator_view().public.tables["ledger"]]


def test_keyed_stream_is_deterministic_and_keyed() -> None:
    def draw(key: bytes, label: str) -> list[int]:
        stream = KeyedStream(key, label)
        return [stream.below(1000) for _ in range(50)]

    values = draw(b"key", "label")
    assert values == draw(b"key", "label")
    assert values != draw(b"other", "label") and values != draw(b"key", "label2")
    assert all(0 <= value < 1000 for value in values)


def test_keyed_stream_known_answers_pin_the_algorithm() -> None:
    # HMAC-SHA256 counter mode: these values must never change across Python versions or refactors.
    stream = KeyedStream(b"genesis", "known-answer")
    assert [stream.below(1000) for _ in range(5)] == KNOWN_BELOW
    assert KeyedStream(b"genesis", "known-answer").shuffled(range(10)) == KNOWN_SHUFFLE
    assert KeyedStream(b"genesis", "known-answer").token(8, "ABCDEFGH") == KNOWN_TOKEN
    assert keyed_hex(b"genesis", "known-answer", 12) == KNOWN_HEX


def test_keyed_stream_helpers() -> None:
    stream = KeyedStream(b"key", "shuffle")
    items = list(range(20))
    mixed = stream.shuffled(items)
    assert sorted(mixed) == items and mixed != items and items == list(range(20))  # a permutation; input untouched
    assert set(stream.token(200, "AB")) == {"A", "B"}
    uniform, spread = KeyedStream(b"key", "uniform"), Counter()
    for _ in range(4000):
        spread[uniform.below(4)] += 1
    assert sorted(spread) == [0, 1, 2, 3] and all(850 < count < 1150 for count in spread.values())
    with pytest.raises(ValueError):
        KeyedStream(b"", "label")
    with pytest.raises(ValueError):
        stream.below(0)


def test_perturbation_renames_every_id_consistently_and_keeps_the_books() -> None:
    base = make()
    base.reset(config={"episode": FAULTY})
    env = perturbed(seed=3)
    mapping = env.evaluator_id_mapping()
    original, changed = ledger(base), ledger(env)
    assert len(mapping) == 12 + 5 + 2 + 3 + 2 and all(old != new for old, new in mapping.items())
    assert len(set(mapping.values())) == len(mapping)

    def facts(rows: list[dict]) -> Counter:
        return Counter((r["timestamp"], r["account"], r["debit_minor"], r["credit_minor"], r["currency"]) for r in rows)

    assert facts(original) == facts(changed)
    by_new_id = {row["row_id"]: row for row in changed}
    for row in original:  # every link survives renaming
        twin = by_new_id[mapping[row["row_id"]]]
        for field in ("entity_id", "invoice_id", "payment_id"):
            assert twin[field] == (mapping[row[field]] if row[field] is not None else None)
    assert [mapping[row["row_id"]] for row in original] != [row["row_id"] for row in changed]  # order changed
    public = env.evaluator_view().public
    assert public.manifest["episode_id"] not in (FAULTY_ID, "") and public.manifest["counts"]["ledger_rows"] == 12
    payment = next(p for p in public.tables["payments"] if p["payment_id"] == mapping["P9"])
    assert payment["invoice_refs"] == [mapping["I7"]] and payment["doc_id"] == mapping["D44"]


def test_same_seed_same_episode_and_different_seed_or_secret_differs() -> None:
    def snapshot(env: AuditEnv) -> str:
        public = env.evaluator_view().public
        return json.dumps([public.manifest, public.tables], sort_keys=True, default=list)

    assert snapshot(perturbed(5)) == snapshot(perturbed(5))
    assert snapshot(perturbed(5)) != snapshot(perturbed(6))
    assert snapshot(perturbed(5)) != snapshot(perturbed(5, secret=b"a private evaluation key"))
    ids = {perturbed(seed).evaluator_view().public.manifest["episode_id"] for seed in range(30)}
    assert len(ids) == 30


def test_options_are_independent() -> None:
    base = make()
    base.reset(config={"episode": FAULTY})
    renamed_only = perturbed(4, {"rename_ids": True, "shuffle_rows": False})
    shuffled_only = perturbed(4, {"rename_ids": False, "shuffle_rows": True})
    mapping = renamed_only.evaluator_id_mapping()
    assert [mapping[r["row_id"]] for r in ledger(base)] == [r["row_id"] for r in ledger(renamed_only)]
    assert shuffled_only.evaluator_id_mapping() == {}
    assert sorted(r["row_id"] for r in ledger(shuffled_only)) == sorted(r["row_id"] for r in ledger(base))
    assert [r["row_id"] for r in ledger(shuffled_only)] != [r["row_id"] for r in ledger(base)]
    neither = perturbed(4, {"rename_ids": False, "shuffle_rows": False})
    assert ledger(neither) == ledger(base)


def test_scoring_follows_the_renamed_ids() -> None:
    env = perturbed(9)
    mapping, episode_id = env.evaluator_id_mapping(), env.evaluator_view().public.manifest["episode_id"]
    stale = submit_action([finding()], episode_id)
    assert env.step(stale)[1] == -1.0  # the unperturbed ids mean nothing here
    env = perturbed(9)
    renamed = finding(affected_ids=[mapping["I7"], mapping["P9"]], evidence_ids=[mapping[i] for i in EVIDENCE])
    assert env.step(submit_action([renamed], episode_id))[1] == 1.0


def test_seed_is_not_visible_to_the_policy() -> None:
    seed = 987654321
    env = perturbed(seed)
    observation = env.trajectory()[0]["observation"]
    env.step({"action": "list_records", "args": {"table": "ledger"}})
    assert str(seed) not in json.dumps(env.trajectory())
    assert "seed" not in json.dumps(observation).lower()
    # the id derivation is keyed: knowing the public dev key says nothing about ids made with a private key
    private = perturbed(seed, secret=b"a private evaluation key")
    assert private.evaluator_view().public.manifest["episode_id"] != observation["manifest"]["episode_id"]
    assert set(private.evaluator_id_mapping().values()).isdisjoint(env.evaluator_id_mapping().values())


@pytest.mark.parametrize("episode", [FAULTY, CLEAN])
def test_twenty_paired_checks_pass(episode: str) -> None:
    results = [evaluate.paired_check(episode, seed) for seed in range(1, 21)]
    failed = [result for result in results if not result["ok"]]
    assert not failed, failed
    assert all(set(result["checks"]) == set(results[0]["checks"]) for result in results)


def test_perturbation_is_an_isomorphism_over_a_hundred_seeds() -> None:
    """Review E, hypothesis S2: a correct finding stays a true positive, and a stale one never is."""
    for seed in range(100, 200):
        env = perturbed(seed)
        mapping, episode_id = env.evaluator_id_mapping(), env.evaluator_view().public.manifest["episode_id"]
        renamed = finding(affected_ids=[mapping["I7"], mapping["P9"]], evidence_ids=[mapping[i] for i in EVIDENCE])
        assert env.step(submit_action([renamed], episode_id))[1] == 1.0
    issue_ids = {perturbed(seed).evaluator_view().truth[0].issue_id for seed in range(100, 120)}
    assert len(issue_ids) == 20  # private ids are re-keyed too, so logs of different variants do not link up
