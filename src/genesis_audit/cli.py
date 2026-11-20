"""Command-line entry point: python -m genesis_audit <command>."""

from __future__ import annotations

import argparse
import gzip
import json
import os
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from . import canon, evaluate, paths, shipped, teaching, tutor
from .bridge import run_policy
from .env import AuditEnv, DirectorySource
from .episodes import _EPISODE_NAME as EPISODE_NAME
from .errors import EpisodeError, LifecycleError
from .prng import DEV_SECRET
from .sandbox import DOCKER_IMAGE_VARIABLE, Confinement, ConfinementError
from .store import load_public
from .tutor.paper import render_paper_episode

DOCS_TUTORING = paths.REPO_ROOT / "docs" / "tutoring"
RESULTS_DOC = paths.REPO_ROOT / "docs" / "RESULTS.md"
DIGESTS_DOC = paths.REPO_ROOT / "docs" / "DIGESTS.json"
SPLITS_FILE = paths.REPO_ROOT / "episodes" / "splits.json"
TRAJECTORIES_DOC = paths.REPO_ROOT / "docs" / "trajectories.jsonl.gz"
SCALE_DOC = paths.REPO_ROOT / "docs" / "measurements" / "scale.json"
SWEEP_DOC = paths.REPO_ROOT / "docs" / "measurements" / "random_inspector_sweep.json"
CHECKER = paths.REPO_ROOT / "tools" / "independent_checker.py"
TUTOR_DOCS = {"A": "A_socratic_tutor.md", "B": "B_paper_episode.md", "C": "C_reward.md", "D": "D_grpo_debugger.md"}
PAPER_EPISODE = "teaching_b"
PAIRED_SEEDS = range(1, 21)


def _out(text: str = "") -> None:
    sys.stdout.write(text + "\n")
    sys.stdout.flush()


def _ask(prompt: str) -> str:
    sys.stdout.write(prompt)
    sys.stdout.flush()
    line = sys.stdin.readline()
    if not line:
        raise EOFError
    return line.rstrip("\n")


def _private_paths() -> tuple[Path, ...]:
    """Everything a policy must not read: all of the repository except the policy code, the episode
    roots wherever they are, and the evaluator's key. Not only truth: the records cost steps, and
    the source, tests and documents hold answers. The only way to learn anything is the bridge."""
    inside = [entry for entry in sorted(paths.REPO_ROOT.iterdir()) if entry.name != "policies"]
    outside = [root for root in (paths.PUBLIC_ROOT, paths.PRIVATE_ROOT) if paths.REPO_ROOT not in root.parents]
    secret = os.environ.get("GENESIS_AUDIT_SECRET_FILE")
    return (*inside, *(root for root in outside if root.exists()), *([Path(secret)] if secret else []))


def _confinement(name: str, *, allow_none: bool = False, also_private: Sequence[Path] = ()) -> Confinement:
    """Resolve --confine. 'auto' never falls back to no boundary unless the caller asks to see that case."""
    private = (*_private_paths(), *also_private)
    if name != "auto":
        return Confinement(name, private, os.environ.get(DOCKER_IMAGE_VARIABLE))
    chosen = Confinement.strongest(private)
    if chosen.backend == "none" and not allow_none:
        raise ConfinementError("no confinement backend is available here; pass --confine none to run with no boundary")
    return chosen


# ----------------------------------------------------------------------- tutoring


def tutor_page(prompt: str) -> str:
    """The worked markdown page for a tutoring prompt."""
    if prompt == "B":
        return render_paper_episode(load_public(paths.PUBLIC_ROOT / PAPER_EPISODE), PAPER_EPISODE)
    return tutor.render_markdown(tutor.banks()[prompt])


def cmd_tutor(args: argparse.Namespace) -> int:
    if args.render:
        target = DOCS_TUTORING / TUTOR_DOCS[args.prompt]
        target.write_text(tutor_page(args.prompt), encoding="utf-8")
        _out(f"wrote {target.relative_to(paths.REPO_ROOT)}")
        return 0
    if args.prompt == "B":
        return cmd_play(argparse.Namespace(episode=PAPER_EPISODE))
    try:
        tutor.run_session(tutor.banks()[args.prompt], _ask, _out)
    except EOFError:
        _out("\nSession ended before the last question; nothing was scored.")
        return 1
    return 0


def cmd_build_fixtures(args: argparse.Namespace) -> int:
    secret = paths.evaluator_secret()
    written = teaching.write_all(paths.PUBLIC_ROOT, paths.PRIVATE_ROOT, secret)
    written += shipped.write_all(paths.PUBLIC_ROOT, paths.PRIVATE_ROOT, secret)
    SPLITS_FILE.write_text(evaluate.splits_document(), encoding="utf-8")
    _out(
        f"wrote {len(written)} files for {len(teaching.VARIANTS) + len(shipped.NAMES)} episodes, and {SPLITS_FILE.name}"
    )
    return 0


PLAY_HELP = """Commands (each tool call costs one step):
  list <table> [cursor] [limit]   tables: ledger, invoices, payments, fx
  get <table> <id>                one record by row_id / invoice_id / payment_id / fx key
  doc <doc_id>                    one supporting document
  calc <expression>               decimal arithmetic, for example: calc 250000-150000
  submit <file.json>              findings file: {"episode_id": ..., "findings": [...]} - ends the episode
  raw <json>                      send any JSON action as-is
  help | quit"""


def _play_action(line: str) -> object | None:
    """Translate one typed command into an action. None means 'not an action'."""
    parts = line.split()
    if not parts:
        return None
    head, rest = parts[0], parts[1:]
    if head == "list" and 1 <= len(rest) <= 3:
        args: dict[str, object] = {"table": rest[0]}
        for token in rest[1:]:
            args["limit" if token.isdigit() else "cursor"] = int(token) if token.isdigit() else token
        return {"action": "list_records", "args": args}
    if head == "get" and len(rest) == 2:
        return {"action": "get_record", "args": {"table": rest[0], "id": rest[1]}}
    if head == "doc" and len(rest) == 1:
        return {"action": "get_document", "args": {"doc_id": rest[0]}}
    if head == "calc" and rest:
        return {"action": "calculator", "args": {"expression": line.split(None, 1)[1]}}
    if head == "submit" and len(rest) == 1:
        return {"action": "submit", "args": {"findings": canon.loads_strict(Path(rest[0]).read_text(encoding="utf-8"))}}
    if head == "raw" and rest:
        return canon.loads_strict(line.split(None, 1)[1])
    return None


def cmd_play(args: argparse.Namespace) -> int:
    """Play one episode by hand. The answer is checked only when you submit.

    The human at the keyboard is trusted here: this command runs in the evaluator's
    process and is a teaching aid, not an isolation boundary.
    """
    env = AuditEnv(DirectorySource(paths.PUBLIC_ROOT, paths.PRIVATE_ROOT))
    observation, _ = env.reset(config={"episode": args.episode, "wall_time_limit_s": None})
    _out(json.dumps(observation, indent=2))
    _out(PLAY_HELP)
    while True:
        try:
            line = _ask("\n> ").strip()
        except EOFError:
            _out("\nLeft without submitting; nothing was scored.")
            return 1
        if line in ("quit", "exit"):
            _out("Left without submitting; nothing was scored.")
            return 1
        try:
            action = _play_action(line)
        except (OSError, ValueError) as error:
            _out(f"Could not read that: {type(error).__name__}")
            continue
        if action is None:
            _out(PLAY_HELP)
            continue
        observation, reward, terminated, truncated, _ = env.step(action)
        _out(json.dumps(observation, indent=2))
        if terminated or truncated:
            _out("\nEpisode over. Evaluator feedback (shown only now, after the final submission):")
            _out(json.dumps({"reward": reward, **env.evaluator_report()}, indent=2))
            return 0


# --------------------------------------------------------------------- evaluation


def cmd_run(args: argparse.Namespace) -> int:
    """Run one policy on one episode and print the evaluator's report."""
    also_private: tuple[Path, ...] = ()
    if args.job:  # a file in a private place: nothing about the run appears on any command line
        job_path = Path(args.job).resolve()
        also_private = (job_path,)  # the boundary must deny it, wherever it lies
        job = canon.loads_strict(job_path.read_text(encoding="utf-8"))
        allowed = {"policy", "script", "script_args", "episode", "seed", "perturb", "mode", "confine"}
        if not isinstance(job, dict) or not set(job) <= allowed or ("policy" in job) == ("script" in job):
            raise LifecycleError(
                f"a job file is an object with exactly one of policy/script and only {sorted(allowed)}"
            )
        for key, value in job.items():
            setattr(args, key, value)
        script_directory = Path(args.script).resolve().parent if args.script else evaluate.POLICY_DIR
        if job_path.parent == script_directory or script_directory in job_path.parents:
            raise ConfinementError("the job file is inside the policy's own directory, which the policy can read")
    extra: dict[str, object] = {"mode": args.mode}
    if args.perturb:
        extra["perturb"] = {"rename_ids": True, "shuffle_rows": True}
    if args.script:  # any policy script, for example one of your own
        config = {"episode": args.episode, **extra}
        done = run_policy(evaluate.new_env(), Path(args.script).resolve(), args.script_args, seed=args.seed,
                          config=config, confinement=_confinement(args.confine, also_private=also_private))  # fmt: skip
        _out(json.dumps({"report": done.report, "process": done.process}, indent=2))
        return 0
    confinement = _confinement(args.confine, also_private=also_private)
    record = evaluate.run(args.policy, args.episode, confinement=confinement, seed=args.seed, extra_config=extra)
    _out(json.dumps({"report": record.report, "process": record.process}, indent=2))
    return 0


def cmd_baselines(args: argparse.Namespace) -> int:
    """Run every baseline on every episode; write trajectories, evaluator reports and the result sheet."""
    confinement = _confinement(args.confine)
    records = evaluate.run_matrix(confinement)
    rows = [evaluate.sheet_row(record) for record in records]
    sheet = evaluate.render_results(rows, evaluate.family_rows(records))
    out = Path(args.out)
    public, private = out / "public", out / "evaluator"
    public.mkdir(parents=True, exist_ok=True)
    private.mkdir(parents=True, exist_ok=True)
    private.chmod(0o700)
    log = "".join(line + "\n" for line in evaluate.trajectory_lines(records))
    (public / "trajectories.jsonl").write_text(log, encoding="utf-8")
    (public / "results.md").write_text(sheet, encoding="utf-8")
    reports = [{"policy": r.policy, "episode": r.episode, "seed": r.seed, "config": r.config, "report": r.report,
                "process": r.process} for r in records]  # fmt: skip
    (private / "reports.json").write_text(json.dumps(reports, indent=2), encoding="utf-8")
    if args.write_docs:
        RESULTS_DOC.write_text(sheet, encoding="utf-8")
        DIGESTS_DOC.write_text(json.dumps(evaluate.digest_rows(records), indent=2) + "\n", encoding="utf-8")
        with gzip.GzipFile(TRAJECTORIES_DOC, "wb", compresslevel=9, mtime=0) as archive:  # no clock time in the file
            archive.write(log.encode("utf-8"))
        _out(f"wrote {RESULTS_DOC.relative_to(paths.REPO_ROOT)} and {DIGESTS_DOC.relative_to(paths.REPO_ROOT)}")
    _out(sheet)
    _out(f"confinement backend for scripted policies: {confinement.backend}")
    _out(f"policy-visible trajectories: {public / 'trajectories.jsonl'}; evaluator reports: {private / 'reports.json'}")
    return 0


def _read_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _same_text(path: Path, text: str) -> bool:
    return path.is_file() and path.read_text(encoding="utf-8") == text


def _checker_ok(name: str) -> tuple[bool, str]:
    argv = [sys.executable, "-I", "-S", "-B", str(CHECKER), "--public", str(paths.PUBLIC_ROOT / name),
            "--private", str(paths.PRIVATE_ROOT / name)]  # fmt: skip
    done = subprocess.run(argv, capture_output=True, text=True, check=False, timeout=120)
    try:
        document = json.loads(done.stdout)
    except ValueError:
        return False, f"exit {done.returncode}, unreadable output"
    return done.returncode == 0 and document["ok"] is True, f"{len(document['derived_issues'])} issue(s) re-derived"


Recorder = Callable[[bool, str, str], None]


def _recorder(results: list[tuple[bool, str, str]]) -> Recorder:
    def record(ok: bool, name: str, detail: str) -> None:
        results.append((ok, name, detail))
        _out(f"{'PASS' if ok else 'FAIL'}  {name}: {detail}")

    return record


def _boundary(record: Recorder, confinement: Confinement) -> None:
    probe = evaluate.probe_boundary(confinement)
    gaps = probe.get("known_gaps") or []
    through = {name: probe["attempts"][name] for name in probe.get("must_fail", [])
               if not str(probe.get("attempts", {}).get(name, "")).startswith("denied")}  # fmt: skip
    if confinement.backend == "none":
        detail = "NO CONFINEMENT BACKEND AVAILABLE on this machine; truth is not isolated from policy processes"
    elif not probe.get("held"):  # say exactly what got through, or why the probe could not be read
        detail = f"got through: {through}" if through else f"probe did not report: {probe.get('error', 'no detail')}"
    else:
        detail = f"hostile probe denied on all {len(probe.get('must_fail', []))} attempts that must fail" + (
            f"; known gap, not closable on this backend: {', '.join(gaps)}" if gaps else ""
        )
    record(
        bool(probe.get("held")) and confinement.backend != "none",
        f"boundary holds under '{confinement.backend}'",
        detail,
    )


def _harness(record: Recorder, confinement: Confinement) -> list[evaluate.RunRecord]:
    """What holds for any episode root: checker, baselines, replay, leaks, pairs, a truth-blind solver."""
    names = list(evaluate.catalogue())  # whatever is under the episode root, not a fixed list
    source, broken = DirectorySource(paths.PUBLIC_ROOT, paths.PRIVATE_ROOT), []
    for name in names:
        try:
            source.load(name)
        except EpisodeError as refusal:
            broken.append(f"{name}: {refusal}")
    record(not broken and bool(names), "every episode loads: files consistent, posting structure holds, truth expressible",
           f"{len(names)} episodes" if not broken else "; ".join(broken)[:400])  # fmt: skip
    if broken or not names:
        return []  # nothing else can be measured on a root that does not load
    agreed = [(name, *_checker_ok(name)) for name in names]
    wrong = [f"{name}: {detail}" for name, ok, detail in agreed if not ok]
    issues = sum(int(detail.split()[0]) for _, ok, detail in agreed if ok)
    record(not wrong, "independent checker re-derives the truth of every episode from public records",
           f"{len(names)} episodes, {issues} issues re-derived" if not wrong else "; ".join(wrong))  # fmt: skip

    records = evaluate.run_matrix(confinement, names)
    by_key = {(run.policy, run.episode): run.report for run in records}
    ceiling = [name for name in names if by_key[("oracle", name)]["score"]["reward"] != 1.0
               or by_key[("oracle_fetching", name)]["score"].get("f1") != 1.0]  # fmt: skip
    record(not ceiling, "the oracle scores 1.0 everywhere, and fetching every evidence record fits the step budget",
           f"{len(names)} episodes, most evidence fetches in one episode: "
           f"{max(by_key[('oracle_fetching', name)]['inspection_steps'] for name in names)}" if not ceiling else str(ceiling))  # fmt: skip
    replays = [evaluate.replay(run) for run in records]
    record(
        all(r["match"] for r in replays), "every run replays to the same digest and score", f"{len(replays)} replays"
    )
    leaked = evaluate.leaked_tokens(records)
    record(
        not leaked,
        "nothing private in policy-visible trajectories",
        "no private token found" if not leaked else str(leaked),
    )

    pairs = [evaluate.paired_check(name, seed) for name in names
             for seed in (PAIRED_SEEDS if name in evaluate.TEACHING else (1,))]  # fmt: skip
    failed = [(p["episode"], p["seed"]) for p in pairs if not p["ok"]]
    generated = sum(1 for p in pairs if evaluate.labels_of(p["episode"])["split"] not in evaluate.HAND_BUILT)
    record(not failed, "id-renaming and row-order pairs preserve oracle findings and reward",
           f"{len(pairs)} pairs, {generated} of them on generated episodes" if not failed else f"failed: {failed}")  # fmt: skip

    solved = evaluate.investigator_check(confinement, names=names)
    control = (f"; memoriser {solved['memoriser_on_unseen_variant']:.3f} vs abstain {solved['abstain_on_unseen_variant']:.3f} "
               "on the variant it has not seen" if "memoriser_on_unseen_variant" in solved else "")  # fmt: skip
    record(solved["ok"], "a truth-blind investigator finds every issue on every episode"
           + (", and a memoriser fails the control" if control else ""),
           f"F1 = 1 on {solved['runs']} runs incl. perturbed twins, worst reward {solved['investigator_worst_reward']:.3f} "
           f"(reading cost only){control}" if solved["ok"] else str(solved))  # fmt: skip
    return records


def _finish(results: list[tuple[bool, str, str]]) -> int:
    passed = sum(1 for ok, _, _ in results if ok)
    _out(f"\n{passed}/{len(results)} checks passed")
    return 0 if passed == len(results) else 1


def cmd_harness(args: argparse.Namespace) -> int:
    """The evaluation harness on whatever is under the episode root: shipped or held-out. Exit 0 only if all holds."""
    results: list[tuple[bool, str, str]] = []
    record = _recorder(results)
    confinement = _confinement(args.confine, allow_none=True)
    _boundary(record, confinement)
    records = _harness(record, confinement)
    if args.sheet:
        _out(
            "\n" + evaluate.render_results([evaluate.sheet_row(run) for run in records], evaluate.family_rows(records))
        )
    return _finish(results)


def cmd_check(args: argparse.Namespace) -> int:
    """One command that re-measures everything this repository reports. Exit 0 only if all of it holds."""
    results: list[tuple[bool, str, str]] = []
    record = _recorder(results)
    secret = paths.evaluator_secret()

    renderers = [(name, teaching.render) for name in teaching.VARIANTS] + [
        (name, shipped.render) for name in shipped.NAMES
    ]
    drift = []
    for name, render in renderers:
        try:
            halves = render(name, secret)
        except EpisodeError as refusal:  # under another key a shipped preset is another company, and may not build
            drift.append(f"{name}: refused ({refusal})")
            continue
        drift += [f"{name}/{filename}" for root, files in zip((paths.PUBLIC_ROOT, paths.PRIVATE_ROOT), halves, strict=True)
                  for filename, text in files.items() if not _same_text(root / name / filename, text)]  # fmt: skip
    if not _same_text(SPLITS_FILE, evaluate.splits_document()):
        drift.append(SPLITS_FILE.name)
    record(not drift, "every shipped episode regenerates byte for byte from its seed or its hand-written history",
           f"{len(renderers)} episodes, no drift" if not drift else f"drift in {len(drift)} files, first: {drift[:3]}")  # fmt: skip

    names = evaluate.episode_names()
    counts = ", ".join(
        f"{split} {sum(1 for e in evaluate.EPISODES.values() if e['split'] == split)}" for split in evaluate.SPLITS
    )
    record(
        set(evaluate.EPISODES) <= set(names),
        "the episode root holds every shipped episode",
        f"{len(names)} found; {counts}",
    )

    confinement = _confinement(args.confine, allow_none=True)  # with no backend the next line fails
    _boundary(record, confinement)
    records = _harness(record, confinement)
    if not records:
        return _finish(results)

    rows = [evaluate.sheet_row(run) for run in records]
    committed = RESULTS_DOC.read_text(encoding="utf-8") if RESULTS_DOC.exists() else ""
    record(evaluate.render_results(rows, evaluate.family_rows(records)) == committed,
           "docs/RESULTS.md is reproduced exactly", f"{len(rows)} runs re-measured")  # fmt: skip
    committed_digests = json.loads(DIGESTS_DOC.read_text(encoding="utf-8")) if DIGESTS_DOC.exists() else []
    record(evaluate.digest_rows(records) == committed_digests, "docs/DIGESTS.json is reproduced exactly",
           f"{len(records)} transition digests and exact rewards")  # fmt: skip

    shipped_log = gzip.decompress(TRAJECTORIES_DOC.read_bytes()).decode("utf-8") if TRAJECTORIES_DOC.exists() else ""
    lines = evaluate.trajectory_lines(records)
    record(shipped_log == "".join(line + "\n" for line in lines), "docs/trajectories.jsonl.gz is reproduced exactly",
           f"{len(lines)} transitions of {len(records)} runs, policy-visible fields only")  # fmt: skip

    stored = _read_json(SCALE_DOC)
    measured = evaluate.scale_measurements(confinement)
    record(measured["within_envelope"] and evaluate.scale_facts(stored) == evaluate.scale_facts(measured),
           "docs/measurements/scale.json agrees with a fresh measurement, and that is inside the envelope",
           f"{measured['most_steps_to_read_everything']} steps at most to read an episode in full; slowest solver episode "
           f"{measured['slowest_solver_episode_seconds']:.2f} s of 60; clock and memory readings are not compared")  # fmt: skip
    record(evaluate.sweep_agrees(_read_json(SWEEP_DOC), confinement),
           "docs/measurements/random_inspector_sweep.json is consistent with a re-run of its first seeds",
           "12 seeds on each teaching episode, each reward found in the stored histogram")  # fmt: skip

    deterministic = [name for name in evaluate.SCRIPTED if name != "random_inspector"]
    teaching_present = [episode for episode in evaluate.TEACHING if episode in names]
    moved = [check for name in deterministic for episode in teaching_present for seed in (1, 2, 3)
             if not (check := evaluate.perturbed_policy_check(name, episode, seed, confinement))["same"]]  # fmt: skip
    record(not moved, "truth-blind policies keep their counts and steps under id renaming and row shuffling",
           f"{len(deterministic)} policies x {len(teaching_present)} teaching episodes x 3 seeds" if not moved else str(moved))  # fmt: skip
    return _finish(results)


def cmd_generate(args: argparse.Namespace) -> int:
    """Generate episodes from a job file into the configured roots. Seeds and settings never touch a command line."""
    job_path = Path(args.job).resolve()
    if evaluate.POLICY_DIR in (job_path.parent, *job_path.parents):
        raise ConfinementError("the job file is inside the policies directory, which a policy can read")
    try:
        job = canon.loads_strict(job_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise LifecycleError(f"the job file is not readable strict JSON ({type(error).__name__})") from error
    entries = job.get("episodes") if isinstance(job, dict) and set(job) == {"episodes"} else None
    allowed, needed = {"name", "seed", "config", "inject", "split"}, {"name", "seed"}
    if not isinstance(entries, list) or not all(isinstance(e, dict) and needed <= set(e) <= allowed for e in entries):
        raise LifecycleError(
            f'a generate job is {{"episodes": [...]}}, each with {sorted(needed)} and optionally {sorted(allowed - needed)}'
        )
    names = [entry["name"] for entry in entries]
    for name in names:
        if not isinstance(name, str) or not EPISODE_NAME.fullmatch(name) or name in evaluate.EPISODES:
            raise LifecycleError(
                "an episode name is a lower-case token of letters, digits and _ that no shipped episode uses"
            )
        if (paths.PUBLIC_ROOT / name).exists() or (paths.PRIVATE_ROOT / name).exists():
            raise LifecycleError(
                "an episode of that name already exists under the episode root; generate never overwrites"
            )
    if len(set(names)) != len(names):
        raise LifecycleError("two episodes in the job share a name")
    secret = paths.evaluator_secret()
    built = []
    for entry in entries:  # build everything first: one refused entry means nothing is written
        if not isinstance(entry.get("config", {}), dict) or not isinstance(entry.get("inject", {}), dict):
            raise LifecycleError("config and inject are objects")
        public, truth, provenance = shipped.generate(entry["seed"], entry.get("config", {}), entry.get("inject", {}),
                                                     secret=secret, variant=entry["name"])  # fmt: skip
        provenance["split"] = str(entry.get("split", "held_out"))
        built.append((entry["name"], public, shipped.books.render(public, truth, provenance)))
    for name, public, halves in built:
        for root, files in zip((paths.PUBLIC_ROOT, paths.PRIVATE_ROOT), halves, strict=True):
            (root / name).mkdir(parents=True, exist_ok=True)
            for filename, text in files.items():
                (root / name / filename).write_text(text, encoding="utf-8")
        counts = public.manifest["counts"]
        _out(f"generated one episode: {counts['ledger_rows']} ledger rows, {counts['documents']} documents")
    if secret == DEV_SECRET:
        sys.stderr.write("note: no GENESIS_AUDIT_SECRET_FILE is set, so these episodes were made with the public development key. "
                         "Anyone with this repository can regenerate them and their answers from candidate seeds.\n")  # fmt: skip
    return 0


def cmd_probe(args: argparse.Namespace) -> int:
    """Launch the hostile probe under a backend and print what it managed to do.

    It starts a fresh evaluator carrying a needle on its command line and one in its environment,
    so the two process-metadata attempts mean something.
    """
    report = evaluate.probe_boundary(_confinement(args.confine, allow_none=True))
    _out(json.dumps(report, indent=2))
    return 0 if report.get("held") else 1


def cmd_probe_child(args: argparse.Namespace) -> int:
    """The evaluator that `probe` starts. Not for direct use."""
    confinement = _confinement(args.confine, allow_none=True)
    needle_environment = os.environ.get(evaluate.PROBE_NEEDLE_VARIABLE, "")
    report = evaluate.probe_in_process(confinement, args.needle, needle_environment)
    _out(json.dumps(report, indent=2))
    return 0 if report["held"] else 1


def cmd_replay(args: argparse.Namespace) -> int:
    """Replay every run that `baselines` saved, and check the set of runs against the committed digests.

    Replaying binds each run's log to its report. The comparison with docs/DIGESTS.json binds the
    directory as a whole: a missing run, an extra one or two swapped labels show up there.
    """
    try:
        records = evaluate.load_records(Path(args.directory))
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        _out(f"MISMATCH  the saved directory cannot be read as runs ({type(error).__name__})")
        return 1
    results = [evaluate.replay(record) for record in records]
    for result in results:
        _out(f"{'MATCH   ' if result['match'] else 'MISMATCH'}  {result['policy']} on {result['episode']}")
    _out(f"{sum(r['match'] for r in results)}/{len(results)} runs replay exactly")
    committed = _read_json(DIGESTS_DOC)
    try:
        same_set = committed is not None and evaluate.digest_rows(records) == committed
    except (KeyError, TypeError, AttributeError):
        same_set = False  # a saved report without its digest or score is not one of the committed runs
    _out(f"{'MATCH   ' if same_set else 'MISMATCH'}  the saved runs are exactly the runs in docs/DIGESTS.json")
    return 0 if results and all(result["match"] for result in results) and same_set else 1


def cmd_sweep(args: argparse.Namespace) -> int:
    """Run the random inspector over many of its own seeds and report the reward spread and flat-group share."""
    result = evaluate.random_sweep(range(args.seeds), _confinement(args.confine), episodes=evaluate.TEACHING)
    _out(json.dumps(result, indent=2))
    return 0


def cmd_measure(args: argparse.Namespace) -> int:
    """Measure reading cost, time and memory on every episode; exit 1 if anything is outside the envelope."""
    result = evaluate.scale_measurements(_confinement(args.confine))
    _out(json.dumps(result, indent=2))
    return 0 if result["within_envelope"] else 1


COMMANDS: dict[str, Callable[[argparse.Namespace], int]] = {
    "measure": cmd_measure,
    "sweep": cmd_sweep,
    "probe": cmd_probe,
    "probe-child": cmd_probe_child,
    "replay": cmd_replay,
    "tutor": cmd_tutor,
    "build-fixtures": cmd_build_fixtures,
    "play": cmd_play,
    "run": cmd_run,
    "baselines": cmd_baselines,
    "check": cmd_check,
    "harness": cmd_harness,
    "generate": cmd_generate,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="genesis-audit", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    tutor_parser = commands.add_parser("tutor", help="run a tutoring prompt as an interactive quiz")
    tutor_parser.add_argument("prompt", choices=sorted(TUTOR_DOCS))
    tutor_parser.add_argument("--render", action="store_true", help="write the worked markdown version instead")
    commands.add_parser("build-fixtures", help="rebuild every shipped episode from its seed or hand-written history")
    generate = commands.add_parser("generate", help="generate episodes from a job file into the configured roots")
    generate.add_argument("--job", required=True, help='JSON: {"episodes": [{"name", "seed", "config", "inject"}]}')
    play = commands.add_parser("play", help="play an episode by hand through the tools")
    play.add_argument("--episode", default=PAPER_EPISODE)
    confine_choices = ["auto", "seatbelt", "setuid", "docker", "none"]
    run = commands.add_parser("run", help="run one policy on one episode")
    which = run.add_mutually_exclusive_group(required=True)
    which.add_argument("--policy", choices=[*evaluate.SCRIPTED, *evaluate.ORACLES])
    which.add_argument("--script", help="path to a policy script of your own (it must live in a directory it may read)")
    which.add_argument(
        "--job",
        help="JSON file with the run's settings. Use it for anything that must stay private: what is typed "
        "on a command line is visible to every process through the launching shell",
    )
    run.add_argument("script_args", nargs="*", help="arguments passed to --script")
    run.add_argument("--episode", default=PAPER_EPISODE, help="any episode under the public root")
    run.add_argument("--mode", default="train", choices=["train", "eval"])
    run.add_argument("--seed", type=int, default=None)
    run.add_argument("--perturb", action="store_true", help="rename ids and shuffle rows (needs --seed)")
    run.add_argument("--confine", default="auto", choices=confine_choices)
    baselines = commands.add_parser("baselines", help="run all baselines and write the result sheet")
    baselines.add_argument("--out", default=str(paths.REPO_ROOT / "out" / "results"))
    baselines.add_argument("--write-docs", action="store_true", help="also refresh docs/RESULTS.md")
    baselines.add_argument("--confine", default="auto", choices=confine_choices)
    probe = commands.add_parser("probe", help="run the hostile boundary probe and print what it could do")
    probe.add_argument("--confine", default="auto", choices=confine_choices)
    child = commands.add_parser("probe-child")
    child.add_argument("--confine", default="auto", choices=confine_choices)
    child.add_argument("--needle", default="")
    replay = commands.add_parser("replay", help="replay the runs saved by `baselines` and compare digests")
    replay.add_argument("directory", nargs="?", default=str(paths.REPO_ROOT / "out" / "results"))
    measure = commands.add_parser("measure", help="measure paging cost, time and memory on every episode")
    measure.add_argument("--confine", default="auto", choices=confine_choices)
    sweep = commands.add_parser("sweep", help="measure the random inspector over many seeds")
    sweep.add_argument("--seeds", type=int, default=400)
    sweep.add_argument("--confine", default="auto", choices=confine_choices)
    check = commands.add_parser("check", help="re-measure everything this repository reports")
    check.add_argument("--confine", default="auto", choices=confine_choices)
    harness = commands.add_parser("harness", help="run the evaluation harness on whatever is under the episode root")
    harness.add_argument("--confine", default="auto", choices=confine_choices)
    harness.add_argument("--sheet", action="store_true", help="also print the result sheet")
    return parser


ARGUMENTS_FD_VARIABLE = "GENESIS_AUDIT_ARGUMENTS_FD"


def _arguments_off_the_command_line() -> list[str]:
    """Return this process's arguments, after making sure they are not on its command line.

    A policy process can read the command lines of other processes (through /proc on Linux, through
    kern.procargs2 on macOS), and `run --episode ... --seed ...` would put an evaluator-side episode
    name and a seed there. So the first invocation hands its arguments to a copy of itself through
    a pipe and replaces itself with `python -m genesis_audit`, which shows nothing.
    """
    inherited = os.environ.pop(ARGUMENTS_FD_VARIABLE, None)
    if inherited is not None:
        with os.fdopen(int(inherited), "rb") as handle:
            return json.loads(handle.read())
    payload = json.dumps(sys.argv[1:]).encode("utf-8")
    if len(sys.argv) <= 1 or len(payload) > 32_000 or os.name != "posix":
        return sys.argv[1:]
    read_end, write_end = os.pipe()
    os.write(write_end, payload)
    os.close(write_end)
    os.set_inheritable(read_end, True)
    environment = {**os.environ, ARGUMENTS_FD_VARIABLE: str(read_end)}
    os.execve(sys.executable, [sys.executable, "-m", "genesis_audit"], environment)  # noqa: S606 - re-running ourselves
    raise AssertionError("unreachable")


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(_arguments_off_the_command_line() if argv is None else argv)
    try:
        return COMMANDS[args.command](args)
    except (ConfinementError, EpisodeError, LifecycleError) as error:
        sys.stderr.write(f"genesis-audit: {type(error).__name__}: {error}\n")
        return 2
