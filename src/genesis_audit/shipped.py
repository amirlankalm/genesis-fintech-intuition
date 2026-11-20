"""The case-stage episodes this repository ships: seven hand-built fixtures, ten train, ten dev.

Fixtures are one small invented company, written by hand, with one variant per family and per
interaction scenario. Their answers are worked by hand in `episodes/private/fixture_clean/ANSWER_KEY.md`
and pinned in the tests. Train and dev episodes come from the seeded generator. A twin pair (a clean
company and the same company with errors) always sits in one split, and the two splits share no seed.

Everything here is evaluator-side. Seeds, settings and what was injected go to the private half only.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from . import books, world
from .errors import EpisodeError
from .families import ALLOCATION, CUTOFF, DUPLICATE, FX
from .prng import DEV_SECRET
from .store import PublicEpisode
from .truth import TruthIssue

_KZT = "+05:00"


def _lines(description: str, quantity: int, unit: int) -> list[dict[str, Any]]:
    return [
        {"description": description, "quantity": quantity, "unit_price_minor": unit, "amount_minor": quantity * unit}
    ]


def _invoice(doc: str, invoice: str, entity: str, issued: str, due: str, currency: str, lines: list[dict[str, Any]],
             posted: str) -> dict[str, Any]:  # fmt: skip
    return {"key": "invoice:" + invoice, "doc_id": doc, "invoice_id": invoice, "entity_id": entity, "issued_at": issued,
            "due_at": due, "currency": currency, "line_items": lines, "posted_at": posted}  # fmt: skip


def _payment(doc: str, payment: str, timestamp: str, currency: str, amount: int, refs: list[str]) -> dict[str, Any]:
    return {"key": "payment:" + payment, "doc_id": doc, "payment_id": payment, "timestamp": timestamp,
            "currency": currency, "amount_minor": amount, "invoice_refs": refs}  # fmt: skip


# One invented company, October 2026, books kept in KZT at UTC+05:00. KZT and USD have two decimals, JPY none.
FIXTURE_WORLD: Mapping[str, Any] = {
    "tag": "case-fixture/1",
    "base_currency": "KZT",
    "currencies": {"KZT": {"exponent": 2}, "USD": {"exponent": 2}, "JPY": {"exponent": 0}},
    "timezone": "Asia/Almaty",
    "period_start": "2026-10-01T00:00:00" + _KZT,
    "period_end": "2026-10-31T23:59:59" + _KZT,
    "invoices": [
        _invoice("D41", "I21", "E3", "2026-10-05T10:00:00+05:00", "2026-10-19T10:00:00+05:00", "KZT",
                 _lines("Equipment rental day", 3, 100000), "2026-10-05T10:20:00+05:00"),
        # settled by a USD receipt whose local date differs from the date written on it
        _invoice("D12", "I08", "E5", "2026-10-09T15:00:00+05:00", "2026-10-30T15:00:00+05:00", "KZT",
                 _lines("Curriculum design day", 2, 2500000), "2026-10-09T16:00:00+05:00"),
        # a weekly plan: three invoices with identical lines, one week apart. Not duplicates.
        _invoice("D33", "I17", "E3", "2026-10-07T09:00:00+05:00", "2026-10-14T09:00:00+05:00", "KZT",
                 _lines("Support plan week", 1, 80000), "2026-10-07T09:15:00+05:00"),
        _invoice("D07", "I26", "E3", "2026-10-14T09:00:00+05:00", "2026-10-21T09:00:00+05:00", "KZT",
                 _lines("Support plan week", 1, 80000), "2026-10-14T09:15:00+05:00"),
        _invoice("D52", "I02", "E3", "2026-10-21T09:00:00+05:00", "2026-10-28T09:00:00+05:00", "KZT",
                 _lines("Support plan week", 1, 80000), "2026-10-21T09:15:00+05:00"),
        # issued two hours before the period ends, and posted before it ends
        _invoice("D29", "I11", "E7", "2026-10-31T22:00:00+05:00", "2026-11-14T22:00:00+05:00", "KZT",
                 _lines("Lab access pass", 4, 30000), "2026-10-31T22:30:00+05:00"),
        # written as 1 November at UTC+09:00, which is 31 October 23:15 at the company's offset: inside the period
        _invoice("D16", "I30", "E9", "2026-11-01T03:15:00+09:00", "2026-11-15T03:15:00+09:00", "KZT",
                 _lines("Consulting hour", 2, 100000), "2026-10-31T23:40:00+05:00"),
        # issued and posted after the period: next period's revenue, correctly
        _invoice("D45", "I19", "E7", "2026-11-02T10:00:00+05:00", "2026-11-16T10:00:00+05:00", "KZT",
                 _lines("Lab access pass", 3, 30000), "2026-11-02T10:20:00+05:00"),
        # a JPY invoice settled by a KZT receipt: the rate is quoted JPY to KZT, so the translation divides
        _invoice("D38", "I24", "E6", "2026-10-15T12:00:00+05:00", "2026-11-05T12:00:00+05:00", "JPY",
                 _lines("Software licence seat", 2, 29412), "2026-10-15T12:30:00+05:00"),
    ],
    "payments": [
        _payment("D61", "P14", "2026-10-12T11:00:00+05:00", "KZT", 300000, ["I21"]),
        _payment("D03", "P31", "2026-10-20T21:30:00+00:00", "USD", 10000, ["I08"]),  # 21 October, 02:30 local
        _payment("D48", "P05", "2026-10-09T10:00:00+05:00", "KZT", 80000, ["I17"]),
        _payment("D25", "P22", "2026-10-16T10:00:00+05:00", "KZT", 80000, ["I26"]),
        _payment("D56", "P09", "2026-10-23T10:00:00+05:00", "KZT", 50000, ["I02"]),  # split payment, first part
        _payment("D10", "P18", "2026-10-27T10:00:00+05:00", "KZT", 30000, ["I02"]),  # split payment, second part
        _payment("D64", "P27", "2026-11-03T10:00:00+05:00", "KZT", 230000, ["I30"]),  # overpaid by 30,000
        _payment("D19", "P40", "2026-10-25T14:00:00+05:00", "KZT", 20000000, ["I24"]),
    ],
    "refunds": [{"payment_id": "P27", "timestamp": "2026-11-05T12:00:00+05:00", "amount_minor": 30000}],
    "entries": [
        {"key": "entry:rent", "timestamp": "2026-10-01T09:00:00+05:00", "debit_account": "rent_expense",
         "credit_account": "bank", "amount_minor": 150000, "currency": "KZT", "entity_id": "E2"},
        {"key": "entry:fees", "timestamp": "2026-10-31T18:00:00+05:00", "debit_account": "bank_fees",
         "credit_account": "bank", "amount_minor": 2500, "currency": "KZT", "entity_id": None},
    ],
    "fx": [
        {"date": "2026-10-20", "source_currency": "USD", "target_currency": "KZT", "rate": "490.00"},
        {"date": "2026-10-21", "source_currency": "USD", "target_currency": "KZT", "rate": "500.00"},
        {"date": "2026-10-24", "source_currency": "JPY", "target_currency": "KZT", "rate": "3.36"},
        {"date": "2026-10-25", "source_currency": "JPY", "target_currency": "KZT", "rate": "3.40"},
    ],
}  # fmt: skip

_COPY_OF_I26 = {"invoice_id": "I33", "doc_id": "D58", "posted_at": "2026-10-14T11:05:00+05:00"}
_COPY_OF_I11 = {"invoice_id": "I35", "doc_id": "D60", "posted_at": "2026-10-31T22:45:00+05:00"}
_USD_AT_20_OCT = {"family": FX, "payment_id": "P31", "rate": "490.00", "rate_source": "2026-10-20"}
FIXTURES: Mapping[str, list[dict[str, Any]]] = {
    "fixture_clean": [],
    "fixture_duplicate": [{"family": DUPLICATE, "invoice_id": "I26", "copy": _COPY_OF_I26}],
    "fixture_allocation": [{"family": ALLOCATION, "payment_id": "P22", "invoice_id": "I26", "applied_minor": 0}],
    "fixture_fx": [
        _USD_AT_20_OCT,
        {"family": FX, "payment_id": "P40", "rate": "3.36", "rate_source": "2026-10-24"},
    ],
    "fixture_cutoff": [{"family": CUTOFF, "invoice_id": "I11", "posted_at": "2026-11-01T09:00:00+05:00"}],
    "fixture_x_fx_allocation": [
        _USD_AT_20_OCT,
        {"family": ALLOCATION, "payment_id": "P31", "invoice_id": "I08", "applied_minor": 4000000},
    ],
    "fixture_x_duplicate_cutoff": [
        {"family": DUPLICATE, "invoice_id": "I11", "copy": _COPY_OF_I11},
        {"family": CUTOFF, "invoice_id": "I35", "posted_at": "2026-11-01T08:30:00+05:00"},
    ],
}


def _company(
    seed: int, base: str, foreign: list[str], zone: str, period: str, invoices: int, rows: int
) -> dict[str, Any]:
    return {"seed": seed, "config": {"base_currency": base, "foreign_currencies": foreign, "timezone": zone,
                                     "period": period, "invoices": invoices, "ledger_rows": rows}}  # fmt: skip


_TRAIN_TWINS = _company(101, "KZT", ["USD"], "Asia/Almaty", "2026-10", 24, 220)
_DEV_TWINS = _company(203, "GBP", ["USD", "EUR"], "Asia/Kolkata", "2026-03", 45, 450)
_X1, _X2, _X3 = world.INTERACTIONS
# name -> (company, what the clerk got wrong). Dev uses base currencies, exponents and offsets train never shows.
GENERATED: Mapping[str, tuple[Mapping[str, Any], Mapping[str, Any]]] = {
    "train_01": (_TRAIN_TWINS, {}),
    "train_02": (_TRAIN_TWINS, {ALLOCATION: 2}),
    "train_03": (_company(103, "USD", ["EUR", "KZT"], "America/Bogota", "2026-07", 40, 400), {DUPLICATE: 1, CUTOFF: 1}),
    "train_04": (_company(104, "KZT", ["USD", "JPY"], "Asia/Almaty", "2026-Q3", 55, 600), {FX: 2}),
    "train_05": (_company(105, "EUR", ["USD"], "UTC", "2026-02", 30, 300), {CUTOFF: 2}),
    "train_06": (_company(106, "KZT", ["USD", "EUR"], "Asia/Almaty", "2026-05", 70, 800),
                 {DUPLICATE: 1, ALLOCATION: 1, FX: 1, CUTOFF: 1}),
    "train_07": (_company(107, "USD", ["JPY"], "UTC", "2026-08", 45, 500), {DUPLICATE: 1, "interactions": [_X1]}),
    "train_08": (_company(108, "EUR", ["GBP", "USD"], "Africa/Lagos", "2026-04", 35, 350), {"interactions": [_X2]}),
    "train_09": (_company(109, "KZT", ["USD"], "Asia/Almaty", "2026-Q2", 90, 1200), {}),
    "train_10": (_company(110, "USD", ["KZT", "EUR"], "America/Bogota", "2026-11", 105, 2000),
                 {FX: 1, "interactions": [_X3]}),
    "dev_01": (_company(201, "JPY", ["USD"], "Asia/Tokyo", "2026-09", 28, 260), {DUPLICATE: 2}),
    "dev_02": (_company(202, "USD", ["KWD"], "Asia/Dubai", "2026-06", 80, 900), {}),
    "dev_03": (_DEV_TWINS, {}),
    "dev_04": (_DEV_TWINS, {ALLOCATION: 1, FX: 1, CUTOFF: 1}),
    "dev_05": (_company(205, "KZT", ["EUR"], "Asia/Almaty", "2026-12", 60, 700), {ALLOCATION: 3}),
    "dev_06": (_company(206, "JPY", ["USD", "EUR"], "Asia/Tokyo", "2026-Q1", 85, 1000), {"interactions": [_X1, _X2]}),
    "dev_07": (_company(207, "USD", ["KZT"], "UTC", "2026-01", 30, 320), {DUPLICATE: 1, FX: 1}),
    "dev_08": (_company(208, "KWD", ["USD"], "Asia/Dubai", "2026-10", 100, 1500), {CUTOFF: 1, "interactions": [_X1]}),
    "dev_09": (_company(209, "EUR", ["USD", "JPY", "GBP"], "UTC", "2026-Q4", 100, 2000),
               {DUPLICATE: 3, ALLOCATION: 3, FX: 3, CUTOFF: 3}),
    "dev_10": (_company(210, "JPY", ["KZT"], "Asia/Tokyo", "2026-05", 20, 240), {}),
}  # fmt: skip
SPLITS: Mapping[str, tuple[str, ...]] = {
    "fixture": tuple(FIXTURES),
    "train": tuple(name for name in GENERATED if name.startswith("train_")),
    "dev": tuple(name for name in GENERATED if name.startswith("dev_")),
}
NAMES: tuple[str, ...] = (*FIXTURES, *GENERATED)


_SCENARIO_FAMILIES = {_X1: (FX, ALLOCATION), _X2: (DUPLICATE, CUTOFF), _X3: (CUTOFF, ALLOCATION)}


def labels(name: str) -> dict[str, Any]:
    """Split, status and families of a shipped episode, from its definition alone (nothing is built)."""
    if name in FIXTURES:
        return {"split": "fixture", **describe(FIXTURES[name], int("_x_" in name))}
    inject = GENERATED[name][1]
    scenarios = inject.get("interactions", ())
    present = {family for family, count in inject.items() if family != "interactions" and count}
    present.update(family for scenario in scenarios for family in _SCENARIO_FAMILIES[scenario])
    status = "clean" if not present else "interaction" if scenarios else "faulty"
    return {"split": split_of(name), "status": status, "families": sorted(present)}


def describe(errors: list[dict[str, Any]] | list[Mapping[str, Any]], interactions: int) -> dict[str, Any]:
    """Evaluator-side labels for the result sheet: status and the families present."""
    families = sorted({error["family"] for error in errors})
    status = "clean" if not errors else "interaction" if interactions else "faulty"
    return {"status": status, "families": families}


def generate(seed: int, config: Mapping[str, Any], inject: Mapping[str, Any], *, secret: bytes = DEV_SECRET,
             variant: str = "generated") -> tuple[PublicEpisode, tuple[TruthIssue, ...], dict[str, Any]]:  # fmt: skip
    """A generated episode: a seeded company, seeded errors, and the size envelope of the draft case enforced."""
    company = world.generate_world(seed, config, secret)
    errors = world.plan_errors(company, inject, secret)
    public, truth, provenance = books.build(company, errors, secret=secret, variant=variant, envelope=True)
    # Settings in full and in a fixed order, so the file does not depend on how the caller wrote them.
    provenance["generator"] = {
        "seed": seed,
        "config": world.validate_config(config),
        "inject": world.normal_inject(inject),
    }
    provenance.update(describe(errors, len(inject.get("interactions", ()))))
    return public, truth, provenance


CONFIG_SECTIONS = ("generator", "inject")


def parse_config(config: Mapping[str, Any] | None) -> tuple[dict[str, Any], dict[str, Any]]:
    """`{"generator": {...}, "inject": {...}}`, both optional, as (world settings, inject), each checked in full.

    One parser for `generate_episode(config)` and a train-mode `team_config`. Unknown keys at the top, in
    `generator` or in `inject` are refused with the reason; so are counts and settings out of range. The schema is
    docs/schemas/generator_config.schema.json.
    """
    config = {} if config is None else config
    if not isinstance(config, Mapping):
        raise EpisodeError(f"the generator config must be an object with {list(CONFIG_SECTIONS)}; got {config!r}")
    unknown = sorted(set(config) - set(CONFIG_SECTIONS))
    if unknown:
        raise EpisodeError(f"unknown generator config keys {unknown}: only {list(CONFIG_SECTIONS)} are accepted")
    sections = {name: {} if config.get(name) is None else config[name] for name in CONFIG_SECTIONS}
    for name, section in sections.items():
        if not isinstance(section, Mapping):
            raise EpisodeError(f"config.{name} must be an object; got {section!r}")
    settings, inject = dict(sections["generator"]), dict(sections["inject"])
    world.validate_config(settings)
    world.validate_inject(inject)  # every key, count and interaction entry, and the issue total
    return settings, inject


def generate_files(
    seed: int, config: Mapping[str, Any] | None, *, secret: bytes = DEV_SECRET, variant: str = "generated"
) -> dict[str, str]:
    """The eight files of one generated episode, flat: six public, truth.json and provenance.json."""
    settings, inject = parse_config(config)
    public_files, private_files = books.render(*generate(seed, settings, inject, secret=secret, variant=variant))
    return {**public_files, **private_files}


def split_of(name: str) -> str:
    for split, names in SPLITS.items():
        if name in names:
            return split
    raise EpisodeError(f"not a shipped case episode: {name}")


def build(name: str, secret: bytes = DEV_SECRET) -> tuple[PublicEpisode, tuple[TruthIssue, ...], dict[str, Any]]:
    """Build one shipped episode by its evaluator-side name."""
    split = split_of(name)
    if name in FIXTURES:
        errors = FIXTURES[name]
        public, truth, provenance = books.build(FIXTURE_WORLD, errors, secret=secret, variant=name)
        provenance.update(describe(errors, int("_x_" in name)))
    else:
        company, inject = GENERATED[name]
        public, truth, provenance = generate(company["seed"], company["config"], inject, secret=secret, variant=name)
    provenance["split"] = split
    return public, truth, provenance


def render(name: str, secret: bytes = DEV_SECRET) -> tuple[dict[str, str], dict[str, str]]:
    return books.render(*build(name, secret))


def write_all(public_root: Path, private_root: Path, secret: bytes = DEV_SECRET) -> list[Path]:
    """Write every shipped case episode. Returns the files written."""
    written = []
    for name in NAMES:
        public_files, private_files = render(name, secret)
        for root, files in ((public_root, public_files), (private_root, private_files)):
            directory = root / name
            directory.mkdir(parents=True, exist_ok=True)
            for filename, text in files.items():
                (directory / filename).write_text(text, encoding="utf-8")
                written.append(directory / filename)
    return written
