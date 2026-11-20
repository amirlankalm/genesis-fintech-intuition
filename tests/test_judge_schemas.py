"""docs/schemas/{action,observation,findings,truth}.schema.json checked against real traffic (CRIT-machine-readable-schemas).

Every action the baselines send and every observation they receive through judge_adapter, every findings document
they submit, and every truth.json we ship or generate must validate; the findings schema must refuse exactly what
the verifier refuses as structure. The venv has no jsonschema package, so a small validator for the keywords these
schemas use is defined here; it refuses any keyword it does not know, so the schemas cannot silently outgrow it.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

import pytest

import judge_adapter
from baselines import flag_all, oracle, random_explorer, reconciliation, simple_reconciliation
from genesis_audit import paths, shipped
from genesis_audit.errors import MalformedSubmission
from genesis_audit.schemas import parse_findings_document

SCHEMAS = Path(__file__).resolve().parents[1] / "docs" / "schemas"
ANNOTATIONS = {"$schema", "$id", "$defs", "title", "description", "default", "examples"}
TYPES = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, int | float) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "null": lambda v: v is None,
}


def load(name: str) -> dict[str, Any]:
    return json.loads((SCHEMAS / name).read_text(encoding="utf-8"))


def resolve(ref: str, root: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    document, _, fragment = ref.partition("#")
    base = load(document) if document else root
    node = base
    for part in filter(None, fragment.split("/")):
        node = node[part]
    return node, base


def errors(value: Any, schema: dict[str, Any], root: dict[str, Any], where: str = "$") -> list[str]:
    unknown = set(schema) - ANNOTATIONS - set(CHECKS)
    if unknown:
        raise AssertionError(f"validator does not implement {sorted(unknown)} (at {where})")
    found: list[str] = []
    for keyword, expected in schema.items():
        if keyword in CHECKS:
            found += CHECKS[keyword](value, expected, schema, root, where)
    return found


def _ref(value: Any, ref: str, _s: dict, root: dict, where: str) -> list[str]:
    node, base = resolve(ref, root)
    return errors(value, node, base, where)


def _type(value: Any, expected: str | list[str], _s: dict, _r: dict, where: str) -> list[str]:
    names = [expected] if isinstance(expected, str) else expected
    return [] if any(TYPES[name](value) for name in names) else [f"{where}: not {expected}"]


def _properties(value: Any, props: dict, _s: dict, root: dict, where: str) -> list[str]:
    if not isinstance(value, dict):
        return []
    return [e for key, sub in props.items() if key in value for e in errors(value[key], sub, root, f"{where}.{key}")]


def _additional(value: Any, rule: bool | dict, schema: dict, root: dict, where: str) -> list[str]:
    if not isinstance(value, dict):
        return []
    extra = [key for key in value if key not in schema.get("properties", {})]
    if rule is False:
        return [f"{where}: unexpected keys {extra}"] if extra else []
    if rule is True:
        return []
    return [e for key in extra for e in errors(value[key], rule, root, f"{where}.{key}")]


def _required(value: Any, keys: list[str], _s: dict, _r: dict, where: str) -> list[str]:
    missing = [key for key in keys if isinstance(value, dict) and key not in value]
    return [f"{where}: missing {missing}"] if missing else []


def _items(value: Any, sub: dict, _s: dict, root: dict, where: str) -> list[str]:
    return (
        [e for i, item in enumerate(value) for e in errors(item, sub, root, f"{where}[{i}]")]
        if isinstance(value, list)
        else []
    )


def _bound(test: Any, label: str) -> Any:
    def check(value: Any, limit: Any, _s: dict, _r: dict, where: str) -> list[str]:
        applies = {"len": isinstance(value, str | list), "num": TYPES["number"](value)}[label[0]]
        return [f"{where}: fails {label[1]} {limit}"] if applies and not test(value, limit) else []

    return check


def _enum(value: Any, options: list, _s: dict, _r: dict, where: str) -> list[str]:
    return [] if any(value == o and type(value) is type(o) for o in options) else [f"{where}: {value!r} not in enum"]


def _const(value: Any, constant: Any, s: dict, r: dict, where: str) -> list[str]:
    return _enum(value, [constant], s, r, where)


def _pattern(value: Any, pattern: str, _s: dict, _r: dict, where: str) -> list[str]:
    return [f"{where}: does not match {pattern}"] if isinstance(value, str) and not re.search(pattern, value) else []


def _one_of(value: Any, options: list, _s: dict, root: dict, where: str) -> list[str]:
    passing = sum(not errors(value, option, root, where) for option in options)
    return [] if passing == 1 else [f"{where}: matches {passing} of oneOf"]


def _any_of(value: Any, options: list, _s: dict, root: dict, where: str) -> list[str]:
    return [] if any(not errors(value, option, root, where) for option in options) else [f"{where}: matches no anyOf"]


def _unique(value: Any, flag: bool, _s: dict, _r: dict, where: str) -> list[str]:
    dumped = [json.dumps(item, sort_keys=True) for item in value] if isinstance(value, list) else []
    return [f"{where}: repeated items"] if flag and len(set(dumped)) != len(dumped) else []


CHECKS = {
    "$ref": _ref, "type": _type, "properties": _properties, "additionalProperties": _additional,
    "required": _required, "items": _items, "enum": _enum, "const": _const, "pattern": _pattern,
    "oneOf": _one_of, "anyOf": _any_of, "uniqueItems": _unique,
    "minLength": _bound(lambda v, n: len(v) >= n, ("len", "minLength")),
    "maxLength": _bound(lambda v, n: len(v) <= n, ("len", "maxLength")),
    "minItems": _bound(lambda v, n: len(v) >= n, ("len", "minItems")),
    "maxItems": _bound(lambda v, n: len(v) <= n, ("len", "maxItems")),
    "minimum": _bound(lambda v, n: v >= n, ("num", "minimum")),
    "maximum": _bound(lambda v, n: v <= n, ("num", "maximum")),
}  # fmt: skip


def valid(value: Any, name: str) -> list[str]:
    schema = load(name)
    return errors(value, schema, schema)


# --------------------------------------------------------------------------------------------- traffic


class Tap:
    """Records every action and observation passing through a JudgeEnv."""

    def __init__(self, env: judge_adapter.JudgeEnv) -> None:
        self.env, self.actions, self.observations = env, [], []

    def step(self, action: dict) -> tuple[dict, float, bool, bool, dict]:
        self.actions.append(action)
        transition = self.env.step(action)
        self.observations.append(transition[0])
        return transition


@pytest.fixture(scope="module")
def traffic(tmp_path_factory: pytest.TempPathFactory) -> dict[str, list[Any]]:
    root = tmp_path_factory.mktemp("schemas")
    directories = []
    for name in ("fixture_x_fx_allocation", "teaching_b", "dev_04"):
        directory = root / name
        directory.mkdir()
        for half in (paths.PUBLIC_ROOT / name, paths.PRIVATE_ROOT / name):
            for entry in half.iterdir():
                if entry.name.endswith((".json", ".jsonl", ".csv")):
                    shutil.copy(entry, directory / entry.name)
        directories.append(str(directory))
    plays = [
        lambda env, obs, _d: random_explorer.run(env, obs),
        lambda env, obs, _d: simple_reconciliation.run(env, obs),
        lambda env, obs, _d: flag_all.run(env, obs),
        lambda env, obs, d: oracle.run(env, obs, episode_dir=d),
        lambda env, obs, _d: reconciliation.run(env, obs),
    ]
    seen: dict[str, list[Any]] = {"actions": [], "observations": [], "findings": []}
    for directory in directories:
        for play in plays:
            env = judge_adapter.make_env()
            first, _ = env.reset(None, {"mode": "closed", "episode_dir": directory, "team_config": {}})
            tap = Tap(env)
            play(tap, first, directory)
            seen["observations"] += [first, *tap.observations]
            seen["actions"] += tap.actions
        manual = [  # one of each error, a calculator result and a broken submit, so every branch is exercised
            {"name": "get_record", "args": {"table": "ledger", "id": "U"}},
            {"name": "nope", "args": {}},
            {"action": "x", "args": {}},
            {"name": "calculator", "args": {"expression": "1/0"}},
            {"name": "calculator", "args": {"expression": "0.1+0.2"}},
            {"name": "submit", "args": {"findings": {"findings": "x"}}},
            {"name": "calculator", "args": {"expression": "1"}},
        ]
        env = judge_adapter.make_env()
        env.reset(None, {"mode": "closed", "episode_dir": directory})
        seen["observations"] += [env.step(action)[0] for action in manual]
    seen["findings"] = [a["args"]["findings"] for a in seen["actions"] if a.get("name") == "submit"]
    return seen


def test_crit_machine_readable_schemas_actions_of_real_traffic_validate(traffic: dict[str, list[Any]]) -> None:
    assert len(traffic["actions"]) > 50
    for action in traffic["actions"]:
        assert valid(action, "action.schema.json") == [], action


def test_crit_machine_readable_schemas_observations_of_real_traffic_validate(traffic: dict[str, list[Any]]) -> None:
    codes = {o["error"]["code"] for o in traffic["observations"] if isinstance(o.get("error"), dict)}
    assert {
        "unknown_id",
        "unknown_action",
        "invalid_action",
        "calc_div_zero",
        "invalid_submission",
        "episode_over",
    } <= codes
    for observation in traffic["observations"]:
        assert valid(observation, "observation.schema.json") == [], observation


def test_crit_machine_readable_schemas_error_codes_are_the_adapters() -> None:
    enum = load("observation.schema.json")["$defs"]["error"]["properties"]["code"]["enum"]
    assert enum == list(judge_adapter.PUBLIC_ERROR_CODES)


def test_crit_machine_readable_schemas_submitted_findings_validate(traffic: dict[str, list[Any]]) -> None:
    assert len(traffic["findings"]) == 15
    for document in traffic["findings"]:
        assert valid(document, "findings.schema.json") == []


def test_crit_machine_readable_schemas_truth_of_every_shipped_and_generated_episode(tmp_path: Path) -> None:
    for name in sorted(entry.name for entry in paths.PRIVATE_ROOT.iterdir()):
        truth = json.loads((paths.PRIVATE_ROOT / name / "truth.json").read_text(encoding="utf-8"))
        assert valid(truth, "truth.schema.json") == [], name
    judge_adapter.generate_episode(5, {"inject": {"interactions": ["cutoff_and_allocation"]}}, str(tmp_path))
    assert valid(json.loads((tmp_path / "truth.json").read_text(encoding="utf-8")), "truth.schema.json") == []
    assert shipped.NAMES  # the shipped catalogue is what was iterated above, plus the teaching episodes


def finding(**overrides: Any) -> dict[str, Any]:
    base = {"type": "cutoff", "affected_ids": ["I1"], "claimed_amount_minor": 10000, "currency": "KZT",
            "evidence_ids": ["D1", "D2"], "explanation": "short"}  # fmt: skip
    return {**base, **overrides}


@pytest.mark.parametrize(
    "document",
    [
        {"findings": [finding()]},
        {"episode_id": "ep-x", "findings": [], "extra": 1},
        {"findings": [finding(type="Unknown", currency="kzt ", affected_ids=[], extra=1)]},
        {"findings": [finding(claimed_amount_minor=2**70)]},
        {"findings": [finding()] * 30},
        {"findings": [finding(evidence_ids=["D1"] * 10, explanation="é" * 1000)]},
        {"findings": [finding()] * 31},
        {"findings": [finding(evidence_ids=["D1"] * 11)]},
        {"findings": [finding(explanation="a" * 1001)]},
        {"findings": [finding(claimed_amount_minor=True)]},
        {"findings": [finding(claimed_amount_minor="10000")]},
        {"findings": [finding(claimed_amount_minor=10000.0)]},
        {"findings": [{k: v for k, v in finding().items() if k != "currency"}]},
        {"findings": [finding(affected_ids="I1")]},
        {"findings": [finding(evidence_ids=[1])]},
        {"findings": ["x"]},
        {"episode_id": 5, "findings": []},
        {"findings": {}},
        {},
        [],
    ],
)
def test_crit_machine_readable_schemas_findings_schema_refuses_what_the_verifier_refuses(document: Any) -> None:
    limits = {"max_findings": 30, "max_evidence_ids": 10, "max_explanation_chars": 1000}
    try:
        parse_findings_document(document, "ep-x", limits)
        structural = False
    except MalformedSubmission:
        structural = True
    assert (valid(document, "findings.schema.json") != []) == structural


def test_crit_machine_readable_schemas_refuse_the_core_shapes() -> None:
    """The validator bites: the internal envelope and observation shapes are not the official ones."""
    assert valid({"action": "list_records", "args": {"table": "ledger"}}, "action.schema.json") != []
    assert valid({"name": "list_records", "args": {"table": "ledger", "limit": 51}}, "action.schema.json") != []
    assert valid({"records": [], "next_cursor": None, "steps_remaining": 3}, "observation.schema.json") != []
    assert (
        valid(
            {"result": None, "error": {"code": "secret", "message": ""}, "remaining_steps": 3},
            "observation.schema.json",
        )
        != []
    )
    assert valid({"issues": [{"issue_id": "A"}]}, "truth.schema.json") != []
