"""The jury adapter (judge_adapter.py) against the official interface: "Единый способ подключения", Block 1
(C01-C20 as they concern the adapter), the ADP-* and CRIT-* items, and the baselines driven through it."""

from __future__ import annotations

import inspect
import json
import logging
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

import judge_adapter
from baselines import flag_all, oracle, random_explorer, reconciliation, simple_reconciliation
from genesis_audit import paths

ROOT = Path(__file__).resolve().parents[1]
CONFIG = {"generator": {"invoices": 24, "ledger_rows": 260}, "inject": {"duplicate_invoice": 1, "cutoff": 1}}
SEED = 11
CALC = {"name": "calculator", "args": {"expression": "0.1+0.2"}}
OFFICIAL_KEYS = ["tp", "fp", "fn", "precision", "recall", "f1", "return"]


class FakeClock:
    def __init__(self) -> None:
        self.now = 500.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture(scope="module")
def episode(tmp_path_factory: pytest.TempPathFactory) -> str:
    """A generated episode with two issues, written by generate_episode (the jury's directory)."""
    directory = tmp_path_factory.mktemp("jury") / "D06 copy.v1"  # any directory name
    judge_adapter.generate_episode(SEED, CONFIG, str(directory))
    return str(directory)


@pytest.fixture(scope="module")
def shipped_dir(tmp_path_factory: pytest.TempPathFactory) -> str:
    directory = tmp_path_factory.mktemp("shipped") / "fixture_duplicate"
    directory.mkdir()
    for root in (paths.PUBLIC_ROOT, paths.PRIVATE_ROOT):
        for entry in (root / "fixture_duplicate").iterdir():
            shutil.copy(entry, directory / entry.name)
    return str(directory)


def closed(directory: str, **extra: Any) -> dict[str, Any]:
    return {"mode": "closed", "episode_dir": directory, "team_config": {}, **extra}


def submit(document: dict[str, Any]) -> dict[str, Any]:
    return {"name": "submit", "args": {"findings": document}}


def first_record(env: judge_adapter.JudgeEnv, table: str) -> dict[str, Any]:
    observation = env.step({"name": "list_records", "args": {"table": table, "cursor": None, "limit": 1}})[0]
    return observation["result"]["records"][0]


# ------------------------------------------------------------------------------------------- the interface


def test_crit_adapter_signatures_are_exactly_the_official_ones() -> None:
    def names(function: Any) -> list[str]:
        return list(inspect.signature(function).parameters)

    assert names(judge_adapter.generate_episode) == ["seed", "config", "output_dir"]
    assert names(judge_adapter.make_env) == []
    assert names(judge_adapter.score_episode) == ["episode_dir", "findings", "inspection_steps"]
    env = judge_adapter.make_env()
    assert names(env.reset) == ["seed", "config"] and names(env.step) == ["action"]
    assert judge_adapter.ADAPTER_VERSION and judge_adapter.ENV_VERSION.startswith("genesis-audit-env/")


def test_crit_adapter_signatures_keyword_and_positional_calls_agree(episode: str, tmp_path: Path) -> None:
    assert judge_adapter.generate_episode(seed=SEED, config=CONFIG, output_dir=str(tmp_path / "kw")) is None
    judge_adapter.generate_episode(SEED, CONFIG, str(tmp_path / "pos"))
    for name in (tmp_path / "kw").iterdir():
        assert (
            name.read_bytes() == (tmp_path / "pos" / name.name).read_bytes() == (Path(episode) / name.name).read_bytes()
        )
    by_keyword, by_position = judge_adapter.make_env(), judge_adapter.make_env()
    first_kw = by_keyword.reset(seed=None, config=closed(episode))
    first_pos = by_position.reset(None, closed(episode))
    assert first_kw == first_pos
    assert by_keyword.step(action=CALC) == by_position.step(CALC)
    document = judge_adapter.oracle_findings(episode_dir=episode)
    assert judge_adapter.score_episode(episode_dir=episode, findings=document, inspection_steps=3) == (
        judge_adapter.score_episode(episode, document, 3)
    )


def test_adp_generate_episode_writes_eight_flat_files_and_refuses_bad_config(episode: str, tmp_path: Path) -> None:
    names = sorted(entry.name for entry in Path(episode).iterdir())
    assert names == sorted([*judge_adapter.EPISODE_FILE_NAMES, "truth.json", "provenance.json"])
    truth = json.loads((Path(episode) / "truth.json").read_text(encoding="utf-8"))
    assert sorted(issue["type"] for issue in truth["issues"]) == ["cutoff", "duplicate_invoice"]
    for bad_seed in (-1, True, None, "7"):
        with pytest.raises(judge_adapter.AdapterError, match="seed"):
            judge_adapter.generate_episode(bad_seed, {}, str(tmp_path / "never"))
    for bad in ({"bogus": 1}, {"inject": {"cutoff": -1}}, {"generator": {"invoices": 5}}, {"inject": {"x": 1}}):
        with pytest.raises(judge_adapter.AdapterError, match="refused"):
            judge_adapter.generate_episode(1, bad, str(tmp_path / "never"))
    assert not (tmp_path / "never").exists()  # nothing written when the request is refused


def test_crit_container_import_path_without_installation(tmp_path: Path) -> None:
    """`import judge_adapter` finds the repo's package from any cwd, with site-packages switched off (-S)."""
    code = f"import sys; sys.path.insert(0, {str(ROOT)!r}); import judge_adapter, genesis_audit; print(genesis_audit.__file__)"
    done = subprocess.run(
        [sys.executable, "-S", "-B", "-c", code], cwd=tmp_path, capture_output=True, text=True, check=True
    )
    assert Path(done.stdout.strip()).is_relative_to(ROOT / "src")


# ------------------------------------------------------------------------------------- reset and observations


def test_c01_c02_reset_closed_returns_the_official_first_observation(episode: str) -> None:
    env = judge_adapter.make_env()
    observation, info = env.reset(seed=123, config=closed(episode))
    assert list(observation) == ["task", "manifest", "policy", "remaining_steps"]
    assert observation["remaining_steps"] == 100 and info == {}
    assert '{"name": name, "args": {...}}' in observation["task"] and '"action": name' not in observation["task"]
    assert json.loads(json.dumps(observation)) == observation
    text = json.dumps(observation)
    truth = json.loads((Path(episode) / "truth.json").read_text(encoding="utf-8"))
    for secret in [issue["issue_id"] for issue in truth["issues"]] + [episode, "provenance", "truth.json"]:
        assert secret not in text


def test_adp_reset_closed_loads_exactly_the_directory_and_repeated_reset_restarts(episode: str) -> None:
    env = judge_adapter.make_env()
    first, _ = env.reset(None, closed(episode))
    env.step(CALC)
    env.step(CALC)
    again, _ = env.reset(None, closed(episode))
    assert again == first and env.step(CALC)[0]["remaining_steps"] == 99
    manifest = json.loads((Path(episode) / "manifest.json").read_text(encoding="utf-8"))
    assert first["manifest"]["episode_id"] == manifest["episode_id"]


def test_crit_adapter_signatures_closed_mode_accepts_and_ignores_any_seed(episode: str) -> None:
    observations = [judge_adapter.make_env().reset(seed, closed(episode))[0] for seed in (None, 0, -5, "x", 2**70)]
    assert all(observation == observations[0] for observation in observations)


def test_adp_reset_refusals_are_jury_side_errors(episode: str) -> None:
    env = judge_adapter.make_env()
    with pytest.raises(judge_adapter.AdapterError, match="episode_dir"):
        env.reset(1, {"mode": "closed"})
    with pytest.raises(judge_adapter.AdapterError, match="mode"):
        env.reset(1, {"mode": "eval", "episode_dir": episode})
    with pytest.raises(judge_adapter.AdapterError, match="seed"):
        env.reset(None, {"mode": "train", "team_config": {}})
    with pytest.raises(judge_adapter.AdapterError, match="refused"):
        env.reset(1, {"mode": "train", "team_config": {"inject": {"nope": 1}}})
    with pytest.raises(judge_adapter.AdapterError, match="episode directory"):
        env.reset(1, closed(str(Path(episode) / "missing")))
    with pytest.raises(Exception, match="reset"):
        env.step(CALC)  # a refused reset leaves no live episode


def test_adp_reset_train_generates_the_same_episode_generate_episode_writes(episode: str) -> None:
    generated, info = judge_adapter.make_env().reset(SEED, {"mode": "train", "team_config": CONFIG})
    loaded, _ = judge_adapter.make_env().reset(None, closed(episode))
    assert generated == loaded
    assert info == {"env_version": judge_adapter.ENV_VERSION, "mode": "train"}


# ------------------------------------------------------------------------------------------ step translation


def test_c04_c07_c08_c09_step_results_have_the_official_shapes(episode: str) -> None:
    env = judge_adapter.make_env()
    env.reset(None, closed(episode))
    observation, reward, terminated, truncated, info = env.step(
        {"name": "list_records", "args": {"table": "ledger", "cursor": None, "limit": 50}}
    )
    assert type(reward) is float and reward == 0.0 and terminated is False and truncated is False and info == {}
    assert list(observation) == ["result", "error", "remaining_steps"] and observation["error"] is None
    page = observation["result"]
    assert (
        list(page) == ["records", "next_cursor"] and len(page["records"]) == 50 and isinstance(page["next_cursor"], str)
    )
    row = page["records"][0]
    assert env.step({"name": "get_record", "args": {"table": "ledger", "id": row["row_id"]}})[0]["result"] == row
    invoice = first_record(env, "invoices")
    assert env.step({"name": "get_document", "args": {"doc_id": invoice["doc_id"]}})[0]["result"] == invoice
    assert (
        env.step({"name": "get_record", "args": {"table": "invoices", "id": invoice["invoice_id"]}})[0]["result"]
        == invoice
    )
    fx = first_record(env, "fx")
    key = f"{fx['date']}|{fx['source_currency']}|{fx['target_currency']}"
    assert env.step({"name": "get_record", "args": {"table": "fx", "id": key}})[0]["result"] == fx
    calculated = env.step(CALC)[0]
    assert calculated == {"result": "0.3", "error": None, "remaining_steps": 92}


@pytest.mark.parametrize(
    ("action", "code"),
    [
        ({"name": "get_record", "args": {"table": "ledger", "id": "U-not-there"}}, "unknown_id"),  # C11
        ({"name": "get_document", "args": {"doc_id": "U-not-there"}}, "unknown_id"),  # C12
        ({"name": "drop_table", "args": {}}, "unknown_action"),  # C13
        ({"name": "calculator", "args": {"expression": "open('/etc/passwd')"}}, "calc_syntax"),  # C10
        ({"name": "list_records", "args": {"table": "truth"}}, "unknown_table"),
        ({"name": "list_records", "args": {"table": "ledger", "limit": 51}}, "bad_limit"),
        ({"name": "list_records", "args": {"table": "ledger", "cursor": "ledger:x"}}, "bad_cursor"),
        ({"name": "get_record", "args": {"table": "ledger"}}, "bad_arguments"),
        (
            {"action": "list_records", "args": {"table": "ledger"}},
            "invalid_action",
        ),  # the core envelope is not official
        ({"action": "submit", "args": {"findings": {"findings": []}}}, "invalid_action"),
        ({"name": "calculator", "args": {"expression": "1"}, "extra": 1}, "invalid_action"),
        ("list_records", "invalid_action"),
    ],
)
def test_c10_to_c14_errors_are_bounded_public_and_cost_one_step(episode: str, action: Any, code: str) -> None:
    env = judge_adapter.make_env()
    env.reset(None, closed(episode))
    observation, reward, terminated, truncated, info = env.step(action)
    assert observation["result"] is None and observation["error"]["code"] == code
    assert observation["error"]["code"] in judge_adapter.PUBLIC_ERROR_CODES
    assert observation["error"]["message"] == judge_adapter.PUBLIC_ERRORS[code]
    assert episode not in json.dumps(observation) and "/" not in observation["error"]["message"]
    assert (observation["remaining_steps"], reward, terminated, truncated, info) == (99, 0.0, False, False, {})
    assert env.step(CALC)[0] == {"result": "0.3", "error": None, "remaining_steps": 98}  # C14


def test_adp_step_envelope_a_broken_submit_ends_the_episode_as_an_invalid_submission(episode: str) -> None:
    for action in ({"name": "submit", "args": {"findings": {"findings": []}}, "extra": 1}, {"name": "submit"}):
        env = judge_adapter.make_env()
        env.reset(None, closed(episode))
        observation, reward, terminated, truncated, info = env.step(action)
        assert observation["result"] is None and observation["error"]["code"] == "invalid_submission"
        assert (reward, terminated, truncated, info) == (0.0, True, False, {})
        assert env.evaluator_report()["score"]["reward"] == -1.0


# ------------------------------------------------------------------------------------- rewards and scoring


def test_c19_closed_mode_reward_is_numeric_zero_and_info_empty_at_every_step(episode: str) -> None:
    env = judge_adapter.make_env()
    _, info = env.reset(None, closed(episode))
    transitions = [env.step(CALC) for _ in range(3)]
    transitions.append(env.step(submit(judge_adapter.oracle_findings(episode))))
    transitions.append(env.step(CALC))  # after the end
    assert info == {}
    assert [(type(t[1]), t[1], t[4]) for t in transitions] == [(float, 0.0, {})] * 5
    assert transitions[3][0] == {"result": {"accepted": True}, "error": None, "remaining_steps": 96}
    assert transitions[4][0]["error"]["code"] == "episode_over" and transitions[4][2] is True
    assert env.evaluator_report()["score"]["reward"] == pytest.approx(0.994, abs=1e-9)


@pytest.mark.parametrize("steps", [0, 1, 7, 50])
def test_adp_generate_reset_closed_oracle_scores_one_minus_step_cost(episode: str, steps: int) -> None:
    env = judge_adapter.make_env()
    env.reset(None, closed(episode))
    for _ in range(steps):
        env.step(CALC)
    document = judge_adapter.oracle_findings(episode)
    observation, reward, terminated, _, _ = env.step(submit(document))
    assert observation["result"] == {"accepted": True} and reward == 0.0 and terminated
    score = judge_adapter.score_episode(episode, document, steps)
    assert list(score) == OFFICIAL_KEYS
    assert (score["tp"], score["fp"], score["fn"]) == (2, 0, 0)
    assert score["return"] == pytest.approx(1 - 0.002 * steps, abs=1e-9)
    assert env.evaluator_report()["score"]["reward"] == score["return"]


def test_adp_train_mode_shows_the_terminal_reward(episode: str) -> None:
    env = judge_adapter.make_env()
    env.reset(None, {"mode": "train", "episode_dir": episode})
    rewards = [env.step(CALC)[1] for _ in range(4)]
    _, terminal, terminated, _, info = env.step(submit(judge_adapter.oracle_findings(episode)))
    assert rewards == [0.0] * 4 and terminated and info == {}
    assert type(terminal) is float and terminal == pytest.approx(0.992, abs=1e-9)
    env.reset(None, {"mode": "train", "episode_dir": episode})
    assert env.step(submit({"findings": []}))[1] == -1.0  # two issues missed


def test_t18_invalid_submit_gives_minus_one_nulls_and_an_evaluator_log(
    episode: str, caplog: pytest.LogCaptureFixture
) -> None:
    finding = judge_adapter.oracle_findings(episode)["findings"][0]
    document = {"findings": [finding] * 31}
    for mode, expected in (("closed", 0.0), ("train", -1.0)):
        env = judge_adapter.make_env()
        env.reset(None, {"mode": mode, "episode_dir": episode})
        with caplog.at_level(logging.WARNING, logger="judge_adapter"):
            observation, reward, terminated, truncated, _ = env.step(submit(document))
        assert observation["error"]["code"] == "invalid_submission" and observation["result"] is None
        assert (reward, terminated, truncated) == (expected, True, False)
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="judge_adapter"):
        score = judge_adapter.score_episode(episode, document, 4)
    assert score == {**dict.fromkeys(OFFICIAL_KEYS[:-1]), "return": -1.0}
    assert any("at most 30" in record.getMessage() for record in caplog.records if record.name == "judge_adapter")
    for bad in (
        [],
        None,
        {"findings": [{**finding, "claimed_amount_minor": True}]},
        {"episode_id": "other", "findings": []},
    ):
        assert judge_adapter.score_episode(episode, bad, 0)["return"] == -1.0
    with pytest.raises(judge_adapter.AdapterError, match="inspection_steps"):
        judge_adapter.score_episode(episode, {"findings": []}, -1)


def test_crit_oversize_submit_through_the_adapter_is_an_invalid_submission(episode: str) -> None:
    finding = {**judge_adapter.oracle_findings(episode)["findings"][0], "explanation": "x" * 9000}
    env = judge_adapter.make_env()
    env.reset(None, closed(episode))
    observation, reward, terminated, _, _ = env.step(submit({"findings": [finding] * 31}))
    assert observation["error"]["code"] == "invalid_submission" and terminated and reward == 0.0


def test_adp_score_episode_agrees_with_the_environment_on_right_and_wrong_findings(shipped_dir: str) -> None:
    correct = judge_adapter.oracle_findings(shipped_dir)
    finding = correct["findings"][0]
    variants = [
        correct,
        {"findings": []},
        {"findings": [finding, finding]},  # M12
        {"findings": [{**finding, "claimed_amount_minor": finding["claimed_amount_minor"] + 1}]},  # M07
        {"findings": [{**finding, "currency": finding["currency"].lower()}]},  # M06
        {"findings": [{**finding, "evidence_ids": [*finding["evidence_ids"], "U-missing"]}]},  # M04
        {"findings": [{**finding, "type": "Duplicate"}]},
    ]
    for document in variants:
        env = judge_adapter.make_env()
        env.reset(None, closed(shipped_dir))
        env.step(CALC)
        env.step(submit(document))
        report = env.evaluator_report()
        score = judge_adapter.score_episode(shipped_dir, document, 1)
        assert (score["tp"], score["fp"], score["fn"]) == tuple(report["counts"][k] for k in ("tp", "fp", "fn"))
        assert score["return"] == report["score"]["reward"]


def test_c18_time_limit_counts_from_the_top_of_reset_with_an_injected_clock(
    episode: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = FakeClock()
    real_load = judge_adapter._load

    def slow_load(directory: object) -> Any:
        clock.now += 30.0  # loading spends half the budget, and it counts
        return real_load(directory)

    monkeypatch.setattr(judge_adapter, "_load", slow_load)
    env = judge_adapter.JudgeEnv(clock=clock)
    env.reset(None, closed(episode))
    clock.now += 29.0
    assert env.step(CALC)[0]["result"] == "0.3"  # 59 s: still inside
    clock.now += 1.5
    observation, reward, terminated, truncated, info = env.step(submit(judge_adapter.oracle_findings(episode)))
    assert observation == {"result": None, "error": None, "remaining_steps": 99}
    assert (reward, terminated, truncated, info) == (0.0, False, True, {})
    report = env.evaluator_report()
    assert report["termination_cause"] == "wall_time" and report["counts"] == {"tp": 0, "fp": 0, "fn": 2}


def test_c16_c17_step_budget_through_the_adapter(episode: str) -> None:
    env = judge_adapter.make_env()
    env.reset(None, closed(episode))
    for _ in range(99):
        env.step(CALC)
    observation, _, terminated, _, _ = env.step(submit(judge_adapter.oracle_findings(episode)))
    assert observation == {"result": {"accepted": True}, "error": None, "remaining_steps": 0} and terminated
    env.reset(None, closed(episode))
    transitions = [env.step(CALC) for _ in range(100)]
    assert transitions[-1][3] is True and transitions[-1][0]["result"] == "0.3"
    assert all(not t[2] and not t[3] for t in transitions[:-1])
    assert env.evaluator_report()["counts"] == {"tp": 0, "fp": 0, "fn": 2}


def test_crit_version_in_evaluator_log(episode: str, caplog: pytest.LogCaptureFixture) -> None:
    env = judge_adapter.make_env()
    with caplog.at_level(logging.INFO, logger="judge_adapter"):
        env.reset(42, closed(episode))
    logged = " ".join(record.getMessage() for record in caplog.records if record.name == "judge_adapter")
    for value in (judge_adapter.ENV_VERSION, judge_adapter.ADAPTER_VERSION, '"seed": 42', episode):
        assert value in logged
    env.step(submit({"findings": []}))
    judge = env.evaluator_report()["judge"]
    assert judge["adapter_version"] == judge_adapter.ADAPTER_VERSION and judge["seed"] == 42
    assert judge["config"]["episode_dir"] == episode


def test_crit_oracle_recipe_builds_findings_from_truth(episode: str) -> None:
    document = judge_adapter.oracle_findings(episode)
    truth = json.loads((Path(episode) / "truth.json").read_text(encoding="utf-8"))["issues"]
    manifest = json.loads((Path(episode) / "manifest.json").read_text(encoding="utf-8"))
    assert document["episode_id"] == manifest["episode_id"] and len(document["findings"]) == len(truth)
    for issue in truth:
        finding = next(f for f in document["findings"] if sorted(f["affected_ids"]) == sorted(issue["affected_ids"]))
        assert (finding["type"], finding["claimed_amount_minor"], finding["currency"]) == (
            issue["type"], issue["expected_amount_minor"], issue["currency"],
        )  # fmt: skip
        assert sorted(finding["evidence_ids"]) in [sorted(ids) for ids in issue["acceptable_evidence_sets"]]


# ---------------------------------------------------------------------------------------------- baselines


def test_dlv_four_baseline_adapters_play_through_make_env(shipped_dir: str) -> None:
    results = {}
    plays = {
        "random_explorer": lambda env, obs: random_explorer.run(env, obs),
        "simple_reconciliation": lambda env, obs: simple_reconciliation.run(env, obs),
        "flag_all": lambda env, obs: flag_all.run(env, obs),
        "oracle": lambda env, obs: oracle.run(env, obs, episode_dir=shipped_dir),
        "reconciliation": lambda env, obs: reconciliation.run(env, obs),
    }
    for name, play in plays.items():
        env = judge_adapter.make_env()
        observation, _ = env.reset(None, closed(shipped_dir))
        play(env, observation)
        report = env.evaluator_report()
        assert report["termination_cause"] == "submitted", name
        results[name] = report["score"]["reward"]
    assert results["oracle"] == 1.0 and results["reconciliation"] > 0.9
    assert results["flag_all"] < 0 and results["random_explorer"] == -1.0


def test_dlv_random_explorer_is_reproducible_with_its_fixed_seed(shipped_dir: str) -> None:
    def actions() -> list[Any]:
        sent: list[Any] = []
        env = judge_adapter.make_env()
        observation, _ = env.reset(None, closed(shipped_dir))

        class Spy:
            def step(self, action: dict) -> tuple[dict, float, bool, bool, dict]:
                sent.append(action)
                return env.step(action)

        random_explorer.run(Spy(), observation)
        return sent

    assert actions() == actions() and all(set(action) == {"name", "args"} for action in actions())


def test_dlv_trajectories_jsonl_judge_run_writes_the_official_shapes(shipped_dir: str, tmp_path: Path) -> None:
    sys.path.insert(0, str(ROOT / "tools"))
    import judge_run

    summary, trajectories = tmp_path / "s.json", tmp_path / "t.jsonl"
    code = judge_run.main(
        ["--episode-dir", shipped_dir, "--summary", str(summary), "--trajectories", str(trajectories)]
    )
    assert code == 0
    result = json.loads(summary.read_text(encoding="utf-8"))
    assert set(result["per_policy"]) == set(judge_run.POLICIES) and result["cross_check_failures"] == []
    assert result["per_policy"]["oracle"]["mean_return"] == 1.0
    lines = [json.loads(line) for line in trajectories.read_text(encoding="utf-8").splitlines()]
    required = {
        "run_id",
        "policy",
        "split",
        "episode_id",
        "step",
        "action",
        "observation",
        "reward",
        "terminated",
        "truncated",
    }
    assert all(required <= set(line) for line in lines)
    assert all(line["reward"] == 0.0 for line in lines)  # closed mode
    steps = [line for line in lines if line["step"] > 0]
    assert all(set(line["action"]) == {"name", "args"} for line in steps)
    assert all(list(line["observation"]) == ["result", "error", "remaining_steps"] for line in steps)
    with pytest.raises(SystemExit, match="docs"):
        judge_run.main(["--episode-dir", shipped_dir, "--summary", str(ROOT / "docs" / "x.json")])
