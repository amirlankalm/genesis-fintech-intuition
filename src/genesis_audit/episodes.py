"""Episode loading for the evaluator.

Two layouts:

* DirectorySource: our own episodes, public and private halves under different roots, loaded by
  name and always strictly validated (`check`, the shipped and generated episodes).
* load_episode_dir: one flat directory holding the six public files, truth.json and optionally
  provenance.json (the jury's layout). Other files are ignored and named in the evaluator log.
  strict=True keeps every check; strict=False keeps parsing and formats but turns the contract,
  size-envelope, tolerance and truth-versus-rules checks into evaluator-log warnings, so a
  hand-built fixture loads and is scored against its own truth.
* load_public_dir: the public half of that flat directory only (empty truth). The closed-mode jury
  environment is built from it, so the object a policy talks to never holds truth or provenance.

Nothing here ever reaches a policy.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Protocol

from . import canon
from .errors import EpisodeError
from .families import CONTRACTS, validate_contract, verify_truth
from .store import PUBLIC_FILES, Checks, PublicEpisode, load_public, parse_public, read_texts
from .truth import TruthIssue, parse_truth, validate_truth

LOG = logging.getLogger("genesis_audit.loader")

_EPISODE_NAME = re.compile(r"[a-z0-9_]{1,64}")
TRUTH_FILE, PROVENANCE_FILE = "truth.json", "provenance.json"
PRIVATE_FILES = (TRUTH_FILE, PROVENANCE_FILE, "ANSWER_KEY.md")
EPISODE_FILES = (*PUBLIC_FILES, TRUTH_FILE, PROVENANCE_FILE)
# What a rule evaluation may raise on books our generator would never write. In a non-strict load
# this means "our rules cannot judge this fixture", which is a warning, not a refusal.
_RULE_FAILURES = (EpisodeError, LookupError, TypeError, ValueError, ArithmeticError)


@dataclass(frozen=True)
class LoadedEpisode:
    public: PublicEpisode
    truth: tuple[TruthIssue, ...]
    provenance: Mapping[str, Any] | None = None
    warnings: tuple[str, ...] = ()  # consistency checks a non-strict load let through (evaluator-only)

    def tolerance(self) -> dict[str, int]:
        """Per-currency amount tolerance (tau) for matching: the manifest's declaration.

        A currency the manifest does not declare (only a non-strict load can have one in truth)
        is compared exactly, tau 0, the official default. Scoring must never fail on it.
        """
        declared = self.public.manifest["amount_tolerance_minor"]
        return {**{issue.currency: 0 for issue in self.truth}, **declared}


class EpisodeSource(Protocol):
    """Anything that hands the environment a loaded episode for a name."""

    def load(self, name: str) -> LoadedEpisode: ...


class InMemorySource:
    """A source for one already loaded episode. The name passed to load() is not used."""

    def __init__(self, loaded: LoadedEpisode) -> None:
        self.loaded = loaded

    def load(self, name: str) -> LoadedEpisode:
        return self.loaded


class DirectorySource:
    """Loads episodes by name. The name is evaluator-side and is never shown to a policy."""

    def __init__(self, public_root: Path, private_root: Path) -> None:
        self.public_root = Path(public_root)
        self.private_root = Path(private_root)

    def load(self, name: str) -> LoadedEpisode:
        if not isinstance(name, str) or not _EPISODE_NAME.fullmatch(name):
            raise EpisodeError("episode name must be a lower-case token")
        public = _published_policy(load_public(self.public_root / name))
        validate_contract(public)  # the files of an episode cannot change the rules it is judged by
        private = self.private_root / name
        truth = read_truth(private / TRUTH_FILE)
        validate_truth(truth, public)
        provenance = read_provenance(private / PROVENANCE_FILE)
        try:
            extra = sorted(entry.name for entry in private.iterdir() if entry.name not in PRIVATE_FILES)
        except OSError as exc:
            raise EpisodeError(f"cannot read the private half of the episode: {exc}") from exc
        if extra:
            raise EpisodeError(f"the private half holds {sorted(PRIVATE_FILES)} and nothing else; found {extra}")
        verify_truth(public, truth)  # the posting structure, and truth as the published rules derive it
        return LoadedEpisode(public=public, truth=truth, provenance=provenance)


def _list_episode_dir(directory: Path) -> list[str]:
    try:
        present = sorted(entry.name for entry in directory.iterdir())
    except OSError as exc:
        raise EpisodeError(f"cannot read the episode directory: {exc}") from exc
    ignored = [name for name in present if name not in EPISODE_FILES]
    if ignored:
        LOG.info("episode directory %s: ignoring files %s", directory, ignored)
    return present


def _public_half(directory: Path, checks: Checks) -> PublicEpisode:
    public = _published_policy(parse_public(read_texts(directory, PUBLIC_FILES), checks))
    _judge(checks, "contract", validate_contract, public)
    return public


def load_public_dir(path: str | Path, *, strict: bool) -> LoadedEpisode:
    """Only the six public files of a flat episode directory, with empty truth and no provenance.

    This is what the environment a policy talks to needs in closed mode. truth.json and provenance.json are
    never opened here; it only checks that truth.json is present, so a directory without it is still refused
    up front. The jury reads the private half later with load_episode_dir, after the episode has ended.
    """
    directory = Path(path)
    present = _list_episode_dir(directory)
    if TRUTH_FILE not in present:
        raise EpisodeError(f"the episode directory has no {TRUTH_FILE}")
    checks = Checks(strict=strict)
    public = _public_half(directory, checks)
    return LoadedEpisode(public=public, truth=(), provenance=None, warnings=tuple(checks.warnings))


def load_episode_dir(path: str | Path, *, strict: bool) -> LoadedEpisode:
    """Load one episode from a single flat directory (the jury's layout). See the module docstring."""
    directory = Path(path)
    present = _list_episode_dir(directory)
    checks = Checks(strict=strict)
    public = _public_half(directory, checks)
    truth = read_truth(directory / TRUTH_FILE, strict=strict)
    _judge(checks, "truth against the public records", validate_truth, truth, public)
    provenance = read_provenance(directory / PROVENANCE_FILE) if PROVENANCE_FILE in present else None
    _judge(checks, "truth against the published rules", verify_truth, public, truth)
    return LoadedEpisode(public=public, truth=truth, provenance=provenance, warnings=tuple(checks.warnings))


def read_truth(path: Path, *, strict: bool = True) -> tuple[TruthIssue, ...]:
    """Parse truth.json (key order does not matter; unknown keys are refused only when strict)."""
    try:
        document = canon.loads_strict(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise EpisodeError(f"cannot load truth: {exc}") from exc
    return parse_truth(document, strict=strict)


def read_provenance(path: Path) -> Mapping[str, Any]:
    try:
        provenance = canon.loads_strict(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise EpisodeError(f"cannot read the private half of the episode: provenance.json: {exc}") from exc
    if not isinstance(provenance, dict):
        raise EpisodeError("provenance.json must hold an object")
    return provenance


def _published_policy(public: PublicEpisode) -> PublicEpisode:
    """A policy equal to a published one, whatever its key order, is shown in the published order."""
    for contract in CONTRACTS.values():
        if public.policy == contract["policy"]:
            return replace(public, policy=json.loads(json.dumps(contract["policy"])))
    return public


def _judge(checks: Checks, what: str, check: Callable[..., None], *args: Any) -> None:
    """Run one of our rule-level checks: a refusal when strict, a warning otherwise."""
    if checks.strict:
        check(*args)
        return
    try:
        check(*args)
    except _RULE_FAILURES as exc:
        checks.warn(f"{what}: {type(exc).__name__}: {exc}")
