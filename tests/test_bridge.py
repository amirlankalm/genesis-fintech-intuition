"""Out-of-process policies through the real bridge, including hostile ones."""

from __future__ import annotations

import json

import pytest
from helpers import CLEAN, FAULTY

from genesis_audit import cli, evaluate, paths
from genesis_audit.bridge import MAX_LINE_BYTES, decode_action, run_policy
from genesis_audit.env import BRIDGE_REJECT
from genesis_audit.sandbox import Confinement

HOSTILE = paths.REPO_ROOT / "policies" / "hostile"
PLAIN = Confinement("none")
STRONGEST = Confinement.strongest(cli._private_paths())  # the CLI's own configuration
BACKENDS = [PLAIN] if STRONGEST.backend == "none" else [PLAIN, STRONGEST]
BACKEND_IDS = [c.backend for c in BACKENDS]
each_backend = pytest.mark.parametrize("confinement", BACKENDS, ids=BACKEND_IDS)


def hostile(name: str, confinement: Confinement = PLAIN, **config) -> tuple[dict, list[dict], dict]:
    result = run_policy(evaluate.new_env(), HOSTILE / name, (), seed=None, config={"episode": FAULTY, **config},
                        confinement=confinement)  # fmt: skip
    return result.report, result.trajectory, result.process


def score(policy: str, episode: str, confinement: Confinement = PLAIN) -> tuple:
    record = evaluate.run(policy, episode, confinement=confinement)
    s = record.report["score"]
    return s["tp"], s["fp"], s["fn"], round(s["reward"], 6), record.report["inspection_steps"]


def test_naive_reconciliation_is_defeated_by_the_open_balance_rule() -> None:
    # It reports "receipt minus allocated": 110,000 for P9 (the truth is 100,000) and 20,000 for the decoy P5.
    assert score("reconciliation_naive", FAULTY) == (0, 2, 1, -1.0, 3)
    assert score("reconciliation_naive", CLEAN) == (0, 2, 0, -1.0, 3)


def test_bounded_flag_all_loses_even_though_it_contains_the_answer() -> None:
    assert score("flag_all", FAULTY) == (1, 18, 0, round(2 * 0.1 - 1 - 0.006, 6), 3)
    assert score("always_abstain", FAULTY) == (0, 0, 1, -1.0, 0) and score("always_abstain", CLEAN) == (0, 0, 0, 1.0, 0)
    assert score("flag_all", CLEAN) == (0, 15, 0, -1.0, 3)


def test_random_inspector_is_seeded_and_scores_low() -> None:
    first, second = (evaluate.run("random_inspector", FAULTY, confinement=PLAIN) for _ in range(2))
    assert first.trajectory == second.trajectory and first.report["score"] == second.report["score"]
    assert first.report["valid_submission"] and first.report["score"]["reward"] <= 0
    assert first.process["args"] == ["7"]  # the policy's own seed is recorded with the run


@pytest.mark.parametrize("policy", sorted(evaluate.SCRIPTED))
def test_confinement_does_not_change_any_result(policy: str) -> None:
    if STRONGEST.backend == "none":
        pytest.skip("no confinement backend on this machine")
    for episode in (FAULTY, CLEAN):
        free, confined = (evaluate.run(policy, episode, confinement=c) for c in (PLAIN, STRONGEST))
        assert confined.report["score"] == free.report["score"]
        assert confined.report["trajectory_digest"] == free.report["trajectory_digest"]
        assert confined.process["backend"] == STRONGEST.backend and confined.process["exit_code"] == 0


@each_backend
def test_silent_policy_runs_into_the_wall_time_limit(confinement: Confinement) -> None:
    report, trajectory, process = hostile("silent.py", confinement, wall_time_limit_s=0.4)
    assert (report["termination_cause"], report["steps_used"]) == ("wall_time", 0)
    assert report["score"]["reward"] == -1.0 and trajectory[-1]["truncated"] is True
    assert process["exit_code"] != 0  # it was killed


@each_backend
def test_policy_that_exits_or_crashes_is_truncated(confinement: Confinement) -> None:
    for name in ("exits.py", "crashes.py"):
        report, trajectory, process = hostile(name, confinement)
        assert report["termination_cause"] == "policy_exit" and report["counts"] == {"tp": 0, "fp": 0, "fn": 1}
        assert len(trajectory) == 2 and trajectory[1]["event"] == "forced_truncation"
    assert len(process["stderr_head"]) <= 2000 and process["exit_code"] == 1  # stderr is bounded and private


@each_backend
def test_undecodable_and_oversized_lines_cost_steps_but_are_not_submissions(confinement: Confinement) -> None:
    report, trajectory, process = hostile("garbage.py", confinement)
    codes = json.loads(process["stderr_head"])
    assert codes == ["invalid_action", "invalid_action", "invalid_action", "invalid_action", "action_too_large", None]
    assert (report["termination_cause"], report["inspection_steps"], report["valid_submission"]) == (
        "submitted",
        5,
        True,
    )
    assert [t["action"] for t in trajectory[1:6]] == [{BRIDGE_REJECT: "invalid_action"}] * 4 + [
        {BRIDGE_REJECT: "action_too_large"}
    ]
    assert len(json.dumps(trajectory)) < 20_000  # the 300 kB line was never stored


@each_backend
def test_flooding_the_bridge_ends_the_episode(confinement: Confinement) -> None:
    report, _, _ = hostile("flood.py", confinement)
    assert report["termination_cause"] == "protocol_abuse" and report["score"]["reward"] == -1.0


@each_backend
def test_nothing_is_processed_after_the_submission(confinement: Confinement) -> None:
    report, trajectory, _ = hostile("chatter.py", confinement)
    assert report["termination_cause"] == "submitted" and report["actions_after_end"] == 0
    assert len(trajectory) == 2 and report["steps_used"] == 1


@each_backend
def test_final_message_carries_the_reward_only_in_train_mode(confinement: Confinement) -> None:
    for mode, expected in (("train", -1.0), ("eval", 0.0)):  # C19: closed mode sends a numeric 0
        _, _, process = hostile("echo_reward.py", confinement, mode=mode)
        final = json.loads(process["stderr_head"])
        assert final["reward"] == expected and final["terminated"] is True
        assert set(final) == {"type", "observation", "reward", "terminated", "truncated", "info"}
        assert final["observation"] == {"status": "episode_over", "steps_remaining": 99}


def test_decode_action() -> None:
    assert decode_action(b'{"action": "list_records", "args": {"table": "fx"}}\n')["action"] == "list_records"
    for raw in (b"", b"nope", b"\xff\xfe", b'{"a": NaN}', b'{"a": 1, "a": 2}', b"[" * 100_000):
        assert decode_action(raw) == {BRIDGE_REJECT: "invalid_action"}
    assert MAX_LINE_BYTES >= 30 * (1000 * 4 + 10 * 70 + 600)  # a maximal legal submission fits in one line


def test_policy_runs_never_expose_private_text() -> None:
    records = evaluate.run_matrix(STRONGEST)
    assert evaluate.leaked_tokens(records) == []
    for record in records:
        if record.process is not None:
            assert "Traceback" not in record.process["stderr_head"]


def test_an_evaluator_failure_sends_nothing_to_the_policy(tmp_path, monkeypatch) -> None:
    """Review E, hypothesis B3: a scoring bug must surface to the evaluator and never cross the bridge."""
    import genesis_audit.env as env_module

    recorder = tmp_path / "recorder.py"
    received = tmp_path / "received.jsonl"
    recorder.write_text(
        "import json, sys\n"
        f"log = open({str(received)!r}, 'w')\n"
        "first = sys.stdin.readline(); log.write(first); log.flush()\n"
        "episode_id = json.loads(first)['observation']['manifest']['episode_id']\n"
        "print(json.dumps({'action': 'submit', 'args': {'findings': {'episode_id': episode_id, 'findings': []}}}), flush=True)\n"
        "rest = sys.stdin.read(); log.write(rest); log.flush()\n"
    )

    def explode(*args: object, **kwargs: object) -> None:
        raise RuntimeError(f"scoring bug near {paths.PRIVATE_ROOT}/teaching_b/truth.json")

    monkeypatch.setattr(env_module, "match", explode)
    with pytest.raises(RuntimeError, match="scoring bug"):
        run_policy(evaluate.new_env(), recorder, (), seed=None, config={"episode": FAULTY}, confinement=PLAIN)
    lines = received.read_text().splitlines()
    assert len(lines) == 1 and json.loads(lines[0])["type"] == "reset"  # the reset message, then silence
    assert "truth" not in lines[0] and str(paths.PRIVATE_ROOT) not in lines[0]


# --- From the code review: the evaluator must never hang, crash or grow without bound on policy input ---


@each_backend
def test_policy_that_never_reads_cannot_stall_the_evaluator(confinement: Confinement) -> None:
    import time

    started = time.monotonic()
    report, trajectory, _ = hostile("noread.py", confinement, wall_time_limit_s=1.0)
    assert time.monotonic() - started < 6
    assert report["termination_cause"] == "wall_time" and report["inspection_steps"] == 60  # its actions were served


def test_child_that_outlives_the_policy_is_killed_and_cannot_block_shutdown(tmp_path) -> None:
    import os
    import subprocess
    import time

    started = time.monotonic()
    pid_file = tmp_path / "child.pid"
    result = run_policy(evaluate.new_env(), HOSTILE / "grandchild.py", (str(pid_file),), seed=None,
                        config={"episode": FAULTY, "wall_time_limit_s": 30}, confinement=PLAIN)  # fmt: skip
    assert time.monotonic() - started < 6 and result.report["termination_cause"] == "policy_exit"
    child = int(pid_file.read_text())
    for _ in range(20):  # the kill is asynchronous; a zombie may linger until it is reaped by init
        try:
            os.kill(child, 0)
        except ProcessLookupError:
            break
        time.sleep(0.1)
    else:
        alive = subprocess.run(
            ["ps", "-o", "stat=", "-p", str(child)], capture_output=True, text=True, check=False
        ).stdout
        assert "Z" in alive, "the policy's child process survived the episode"


@each_backend
def test_stderr_is_bounded_in_memory_and_never_written_to_disk(confinement: Confinement) -> None:
    report, _, process = hostile("stderr_flood.py", confinement)
    assert report["termination_cause"] == "submitted" and process["stderr_head"] == "e" * 2000


@each_backend
def test_flood_after_the_end_does_not_accumulate(confinement: Confinement) -> None:
    import resource
    import time

    before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    started = time.monotonic()
    report, trajectory, _ = hostile("submit_then_flood.py", confinement)
    grew = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss - before
    assert report["termination_cause"] == "submitted" and len(trajectory) == 2
    assert time.monotonic() - started < 6
    assert grew < 64 * 1024 * 1024 * (
        1 if __import__("sys").platform == "darwin" else 1 / 1024
    )  # bytes on macOS, kB on Linux


@each_backend
def test_size_and_nesting_bounds_are_exact_and_never_crash_the_evaluator(confinement: Confinement) -> None:
    report, trajectory, process = hostile("edge_lines.py", confinement)
    codes = json.loads(process["stderr_head"])
    assert codes == [
        "unknown_id",  # exactly 262,144 bytes: inside the bound
        "action_too_large",  # one byte more
        "invalid_action",  # 991 levels of nesting used to crash the digest
        "invalid_action",  # 17 levels: just past the depth bound
        "unknown_id",  # 100 kB of two-byte characters is not "too large" just because it is not ASCII
        "invalid_action",  # JSON null is an action that is not an object
        "invalid_action",  # an empty line
    ]
    assert report["termination_cause"] == "submitted" and report["inspection_steps"] == 7
    # actions inside the bound are logged in full (two large ones here); the rejected ones are not stored
    assert report["trajectory_digest"] and len(json.dumps(trajectory)) < 1_000_000


def test_bridged_episode_needs_a_wall_time_limit() -> None:
    from genesis_audit.errors import LifecycleError

    with pytest.raises(LifecycleError, match="wall-time"):
        hostile("exits.py", wall_time_limit_s=None)


@pytest.mark.parametrize("name", ["exits.py", "silent.py", "flood.py"])
def test_a_policy_that_never_acts_scores_a_perfect_abstention_on_clean_books(name: str) -> None:
    """Judge question 8a. Truncation counts as an empty submission [S1], so on clean books doing nothing is 1.0.

    This test pins the consequence so that it is known, not to bless it: see SPEC section 10 and OQ-10.
    """
    result = run_policy(evaluate.new_env(), HOSTILE / name, (), seed=None,
                        config={"episode": CLEAN, "wall_time_limit_s": 0.5}, confinement=PLAIN)  # fmt: skip
    assert result.report["inspection_steps"] == 0 and result.report["score"]["reward"] == 1.0
    assert result.report["termination_cause"] in ("policy_exit", "wall_time", "protocol_abuse")


def test_truth_blind_policies_under_perturbation() -> None:
    """Judge question 11b: real policies on perturbed twins, counts and steps reported separately."""
    for policy in ("always_abstain", "reconciliation_naive", "flag_all"):
        for episode in (FAULTY, CLEAN):
            for seed in range(1, 11):
                check = evaluate.perturbed_policy_check(policy, episode, seed, PLAIN)
                assert check["same"], check
    drifted = [evaluate.perturbed_policy_check("random_inspector", FAULTY, seed, PLAIN) for seed in range(1, 6)]
    assert all(check["twin"][0] == 0 for check in drifted)  # its choices follow row order, so only "no hit" is stable


def test_a_memoriser_of_amounts_is_perfect_because_there_is_one_company() -> None:
    """Judge question 10b. A limit of the slice, pinned so nobody mistakes these episodes for a benchmark.

    Perturbation defeats memorised ids. It cannot defeat memorised amounts: every variant is the
    same latent company. Until a generator varies the economics, a score here says nothing about
    generalization, and twins and perturbations of one latent must stay on one side of any split.
    """
    options = {"perturb": {"rename_ids": True, "shuffle_rows": True}}
    for episode in (FAULTY, CLEAN):
        rewards = set()
        for seed in range(1, 21):
            result = run_policy(evaluate.new_env(), HOSTILE / "memoriser.py", (), seed=seed,
                                config={"episode": episode, **options}, confinement=PLAIN)  # fmt: skip
            rewards.add(round(result.report["score"]["reward"], 6))
        assert rewards == {0.994}, (episode, rewards)
    # The control: on a variant whose amounts it has not seen, the memoriser finds nothing.
    unseen = run_policy(evaluate.new_env(), HOSTILE / "memoriser.py", (), seed=None,
                        config={"episode": "teaching_b_p5"}, confinement=PLAIN)  # fmt: skip
    assert unseen.report["counts"] == {"tp": 0, "fp": 0, "fn": 1} and unseen.report["score"]["reward"] == -1.0


@pytest.mark.skipif(STRONGEST.backend == "none", reason="no confinement backend on this machine")
def test_a_child_cannot_be_left_behind_under_a_real_boundary() -> None:
    """Under seatbelt the fork is denied; under setuid the child is killed with its process group."""
    import time

    started = time.monotonic()
    result = run_policy(evaluate.new_env(), HOSTILE / "grandchild.py", ("/nonexistent/child.pid",), seed=None,
                        config={"episode": FAULTY, "wall_time_limit_s": 30}, confinement=STRONGEST)  # fmt: skip
    assert time.monotonic() - started < 6 and result.report["termination_cause"] == "policy_exit"


def test_policy_aware_reconciliation_is_the_regression_test_for_the_failed_trajectory(tmp_path) -> None:
    """Prompt H. The naive run failed on policy, not on facts: same three tool calls, different arithmetic."""
    naive = evaluate.run("reconciliation_naive", FAULTY, confinement=PLAIN)
    patched = evaluate.run("reconciliation", FAULTY, confinement=PLAIN)
    assert [t["action"] for t in naive.trajectory[1:4]] == [
        t["action"] for t in patched.trajectory[1:4]
    ]  # same evidence
    assert naive.report["counts"] == {"tp": 0, "fp": 2, "fn": 1} and naive.report["score"]["reward"] == -1.0
    assert patched.report["counts"] == {"tp": 1, "fp": 0, "fn": 0}
    assert patched.report["score"]["reward"] == pytest.approx(0.994)
    (claim,) = patched.trajectory[-1]["action"]["args"]["findings"]["findings"]
    assert (claim["affected_ids"], claim["claimed_amount_minor"]) == (["I7", "P9"], 100_000)
    assert score("reconciliation", CLEAN) == (0, 0, 0, 0.994, 3)  # and no false alarm on the decoy
    assert score("reconciliation", "teaching_b_p5") == (1, 0, 0, 0.994, 3)
    assert score("reconciliation", "teaching_b_both") == (2, 0, 0, 0.994, 3)


def test_policy_aware_reconciliation_needs_the_open_balance_rule_and_holds_under_perturbation(tmp_path) -> None:
    from genesis_audit import teaching
    from genesis_audit.env import AuditEnv, DirectorySource

    for episode in (FAULTY, "teaching_b_both"):
        for seed in range(1, 6):
            check = evaluate.perturbed_policy_check("reconciliation", episode, seed, STRONGEST)
            assert check["same"] and check["twin"][1:3] == (0, 0), check
    # An episode it has never been run on: the first receipt of a split is under-allocated, so the
    # second receipt must be judged against what the first was required to settle.
    latent = {**teaching.LATENT, "row_ids": {**teaching.LATENT["row_ids"], "pay:P2:unapplied": "L30"}}
    public, truth, provenance = teaching.build_from(
        latent, "ep-p2", [{"invoice_id": "I3", "payment_id": "P2", "applied_minor": 100_000}]
    )
    from genesis_audit.store import render_public

    for directory, files in (
        (tmp_path / "public" / "variant", render_public(public)),
        (
            tmp_path / "private" / "variant",
            {
                "truth.json": json.dumps({"issues": [i.to_json() for i in truth]}),
                "provenance.json": json.dumps(provenance),
            },
        ),
    ):
        directory.mkdir(parents=True)
        for filename, text in files.items():
            (directory / filename).write_text(text)
    env = AuditEnv(DirectorySource(tmp_path / "public", tmp_path / "private"))
    result = run_policy(env, paths.REPO_ROOT / "policies" / "reconciliation.py", (), seed=None,
                        config={"episode": "variant"}, confinement=PLAIN)  # fmt: skip
    assert result.report["counts"] == {"tp": 1, "fp": 0, "fn": 0}
    (claim,) = result.trajectory[-1]["action"]["args"]["findings"]["findings"]
    assert (claim["affected_ids"], claim["claimed_amount_minor"]) == (["I3", "P2"], 50_000)


def test_investigator_check_passes_and_can_fail(monkeypatch) -> None:
    result = evaluate.investigator_check(PLAIN, seeds=(1, 2))
    assert result["ok"] and not result["investigator_missed"]
    assert result["investigator_worst_reward"] == pytest.approx(0.896)  # the largest company: 52 calls to read it
    assert (result["memoriser_on_unseen_variant"], result["abstain_on_unseen_variant"]) == (-1.0, -1.0)
    monkeypatch.setattr(evaluate, "INVESTIGATOR", "reconciliation_naive")  # the shortcut does not pass for a solver
    assert not evaluate.investigator_check(PLAIN, seeds=(1,))["ok"]


BROKEN_SUBMITS = [
    '{"action":"submit","args":1e999}',  # valid JSON text whose number overflows
    '{"action":"submit","args":{"findings":{"episode_id":"EPISODE","findings":[NaN]}}}',
    '{"action":"submit","args":null,"action":"submit"}',  # duplicate key
    '{"action":"list_records","args":{"table":"ledger"},"action":"submit"}',  # a top-level "action": "submit"
    '{"action":"submit","args":' + "[" * 2000 + "]" * 2000 + "}",  # deeper than any parser here will follow
    '{"action":"submit","args":' + "9" * 4301 + "}",  # an integer CPython refuses to parse
]


@each_backend
@pytest.mark.parametrize("line", BROKEN_SUBMITS)
def test_a_recognisable_submit_that_fails_strict_parsing_is_malformed(confinement: Confinement, line: str) -> None:
    """Grader, defect 4 (SPEC PC-19): it must not slip into the inspection branch and be scored as doing nothing."""
    result = run_policy(evaluate.new_env(), HOSTILE / "send_line.py", (line, "ep-a27d35"), seed=None,
                        config={"episode": CLEAN, "max_steps": 1}, confinement=confinement)  # fmt: skip
    assert result.report["termination_cause"] == "malformed_submission"
    assert result.report["score"]["reward"] == -1.0 and result.report["submitted"] is True


@each_backend
def test_a_final_line_without_a_newline_is_still_an_action(confinement: Confinement) -> None:
    """Grader, defect 8: a valid submission used to be dropped when its newline was missing."""
    line = '{"action":"submit","args":{"findings":{"episode_id":"EPISODE","findings":[]}}}'
    for extra in ((), ("no-newline",)):
        result = run_policy(evaluate.new_env(), HOSTILE / "send_line.py", (line, "ep-a27d35", *extra), seed=None,
                            config={"episode": CLEAN}, confinement=confinement)  # fmt: skip
        assert (result.report["termination_cause"], result.report["score"]["reward"]) == ("submitted", 1.0)


def snoop_through_a_shell(arguments: str, seed: int, environment: dict) -> list[str]:
    """Run the CLI under `sh -c`, as a wrapper would, with a policy that reads every process's command line."""
    import subprocess
    import sys

    # "; exit $?" keeps the shell alive as the parent, the way `uv run`, `make` or a job runner stays alive
    done = subprocess.run(["/bin/sh", "-c", f'"{sys.executable}" -m genesis_audit run {arguments}; exit $?'],
                          capture_output=True, text=True, check=False, cwd=paths.REPO_ROOT, env=environment)  # fmt: skip
    assert done.returncode == 0, done.stderr
    report = json.loads(done.stdout)
    assert report["report"]["seed"] == seed and report["report"]["termination_cause"] == "submitted"
    return json.loads(report["process"]["stderr_head"])


def test_a_job_file_keeps_the_episode_and_seed_off_every_command_line(tmp_path) -> None:
    """Grader, defect 1. A launcher keeps what was typed after it, and a policy can read that.

    The control shows the leak is real when the name and seed are typed as arguments. The job
    file, in a place the policy cannot read, is how they are given when they must stay private.
    The episode name and the seed are random here, so no unrelated process can hold them by chance.
    """
    import os
    import secrets
    import shutil

    name, seed = f"heldout_{secrets.token_hex(6)}", 100_000_000 + secrets.randbelow(800_000_000)
    for half in ("public", "private"):
        shutil.copytree(paths.REPO_ROOT / "episodes" / half / CLEAN, tmp_path / half / name)
        (tmp_path / half).chmod(0o700)
    environment = {**os.environ, "GENESIS_AUDIT_PUBLIC_ROOT": str(tmp_path / "public"),
                   "GENESIS_AUDIT_PRIVATE_ROOT": str(tmp_path / "private")}  # fmt: skip
    snoop, needles = HOSTILE / "snoop.py", [name, str(seed)]
    typed = f'--script "{snoop}" {" ".join(needles)} --episode {name} --seed {seed} --perturb --confine none'
    assert snoop_through_a_shell(typed, seed, environment) == needles  # visible through the shell that launched us
    job = tmp_path / "job.json"
    job.write_text(json.dumps({"script": str(snoop), "script_args": needles, "episode": name, "seed": seed,
                               "perturb": True, "confine": STRONGEST.backend}))  # fmt: skip
    job.chmod(0o600)
    assert snoop_through_a_shell(f'--job "{job}"', seed, environment) == []  # nothing to find, under the real boundary


def test_submit_recognition_does_not_depend_on_the_interpreter() -> None:
    """Grader, R-1 and R-2: a second lenient parse made the branch depend on recursion and integer limits."""
    from genesis_audit import canon
    from genesis_audit.env import BROKEN_SUBMIT

    recognised = {
        '{"action":"submit","args":1e999}': True,
        ' {"args": [1, {"action":"submit"}], "action":"list_records"}': False,  # nested, not top-level
        '{"args": {"action":"submit"}}': False,
        '["action","submit"]': False,
        '{"action":"list_records","args":{},"action":"submit"}': True,
        '{"action":"submit","args":' + "[" * 2000 + "]" * 2000 + "}": True,
        '{"action":"submit","args":' + "9" * 4301 + "}": True,
        "not json": False,
        "": False,
        '{"x":"action","y":"submit"}': False,
        '{"action":"submitx"}': False,
        '{"action":"list_records","args":{"table":"submit"}}': False,
        '{"note":"\\\\","action":"submit"}': True,  # an escaped backslash before the closing quote
    }
    assert {text: canon.is_submission_attempt(text) for text in recognised} == recognised
    assert decode_action(b'{"action":"submit","args":' + b"[" * 2000 + b"]" * 2000 + b"}") == BROKEN_SUBMIT
    assert decode_action(b'{"action":"submit","args":' + b"9" * 4301 + b"}") == BROKEN_SUBMIT
    assert decode_action(b'{"action":"get_document","args":' + b"[" * 2000 + b"]" * 2000 + b"}") == {
        BRIDGE_REJECT: "invalid_action"
    }


def test_a_job_file_the_policy_could_read_is_refused(tmp_path, capsys) -> None:
    """Grader, R-4: a job file next to the policy script would be readable by the policy."""
    job = HOSTILE / "job_for_test.json"
    try:
        job.write_text(json.dumps({"script": str(HOSTILE / "snoop.py"), "episode": CLEAN, "seed": 5, "perturb": True}))
        assert cli.main(["run", "--job", str(job)]) == 2
        assert "inside the policy's own directory" in capsys.readouterr().err
    finally:
        job.unlink(missing_ok=True)
    bad = tmp_path / "job.json"
    bad.write_text(json.dumps({"policy": "flag_all", "script": "x.py"}))
    assert cli.main(["run", "--job", str(bad)]) == 2  # exactly one of policy and script
