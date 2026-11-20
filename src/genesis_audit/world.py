"""A seeded synthetic company: the latent history that `books.derive` posts.

Nothing here is real: currencies are real codes with invented rate levels, and every
entity, invoice and receipt is drawn from a keyed stream. The same seed, config and
evaluator key give the same company on every machine and Python version; without the
key the records say nothing about the seed.

The clean company already contains every valid look-alike of the four error families:
split payments, one receipt for several invoices, part payments, overpayments with and
without a refund, a customer paying twice, unpaid invoices, unidentified receipts,
recurring invoices with identical lines, identical invoices to different customers,
receipts in another currency, timestamps written at another UTC offset, and invoices
issued minutes from a period boundary. An error is therefore never the only record
with its surface feature.
"""

from __future__ import annotations

import calendar
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta, timezone, tzinfo
from fractions import Fraction
from typing import Any

from . import canon, money
from .books import BUILDER_VERSION, ENVELOPE, Derived, derive, invoice_total, new_id, policy_rate, side, translate
from .errors import EpisodeError
from .families import ALLOCATION, CUTOFF, DUPLICATE, FX, when
from .prng import KeyedStream

# Zones with no daylight-saving time, so an episode never contains an offset change.
ZONES: Mapping[str, str] = {
    "Asia/Almaty": "+05:00", "Asia/Tokyo": "+09:00", "Asia/Dubai": "+04:00", "Asia/Kolkata": "+05:30",
    "America/Bogota": "-05:00", "Africa/Lagos": "+01:00", "UTC": "+00:00",
}  # fmt: skip
EXPONENTS: Mapping[str, int] = {"KZT": 2, "USD": 2, "EUR": 2, "GBP": 2, "JPY": 0, "KWD": 3}
# Invented, round reference values in USD per unit. They set plausible magnitudes and are not market data.
USD_VALUE: Mapping[str, Fraction] = {
    "USD": Fraction(1), "EUR": Fraction(108, 100), "GBP": Fraction(127, 100),
    "KZT": Fraction(1, 512), "JPY": Fraction(1, 151), "KWD": Fraction(325, 100),
}  # fmt: skip
CATALOGUE: Sequence[tuple[str, int]] = (  # description, price in USD cents
    ("Robotics workshop session", 9800), ("Data-literacy course seat", 24500), ("Equipment rental day", 6200),
    ("Consulting hour", 15000), ("Software licence seat", 4900), ("Maintenance visit", 31000),
    ("Training manual set", 3600), ("Lab access pass", 12800), ("Site survey", 54000),
    ("Support plan week", 17500), ("Curriculum design day", 68000), ("Certification exam fee", 21000),
)  # fmt: skip
ENTRY_KINDS: Sequence[tuple[str, str]] = (
    ("rent_expense", "bank"), ("salaries_expense", "bank"), ("utilities_expense", "accounts_payable"),
    ("accounts_payable", "bank"), ("office_supplies", "accounts_payable"), ("bank_fees", "bank"),
    ("insurance_expense", "bank"), ("equipment", "accounts_payable"), ("bank", "owner_equity"),
    ("travel_expense", "bank"),
)  # fmt: skip
DEFAULT_CONFIG: Mapping[str, Any] = {
    "base_currency": "KZT", "foreign_currencies": ["USD"], "timezone": "Asia/Almaty", "period": "2026-10",
    "invoices": 40, "ledger_rows": 400, "head_days": 6, "tail_days": 7,
}  # fmt: skip
INTERACTIONS = ("fx_then_allocation", "duplicate_then_cutoff", "cutoff_and_allocation")
# The two documented interaction scenarios, in the order the case counts them. Interaction 1 is the case's own
# example when asked for with {"allocation": "partial", "receipt_currency": "foreign"}: a part payment in another
# currency for an invoice posted on the wrong side of a period boundary. fx_then_allocation is an extra.
INTERACTION_1, INTERACTION_2 = "cutoff_and_allocation", "duplicate_then_cutoff"
DOCUMENTED_INTERACTIONS = (INTERACTION_1, INTERACTION_2)
# The parameters an interaction entry may name, and their values. A parameter left out is drawn from the seed.
SCENARIO_PARAMETERS: Mapping[str, Mapping[str, tuple[str, ...]]] = {
    "cutoff_and_allocation": {
        "boundary": ("start", "end"), "allocation": ("missing", "partial"), "receipt_currency": ("same", "foreign"),
    },
    "duplicate_then_cutoff": {"boundary": ("start", "end"), "copy_offset": ("same", "other")},
    "fx_then_allocation": {"fx_error": ("date", "rate"), "allocation": ("missing", "partial")},
}  # fmt: skip
# Inject counts that ask for one sub-kind of a family. The truth type stays the family's own.
ALLOCATION_MISSING, ALLOCATION_PARTIAL = "payment_allocation_missing", "payment_allocation_partial"
FX_DATE, FX_RATE = "fx_mismatch_date", "fx_mismatch_rate"
COUNT_KEYS = (DUPLICATE, ALLOCATION, FX, CUTOFF, ALLOCATION_MISSING, ALLOCATION_PARTIAL, FX_DATE, FX_RATE)
# Asia/Almaty has been UTC+05:00 since 2024-03-01 00:00 local time; it was UTC+06:00 before. An episode window
# that starts earlier would print an offset the zone did not have, so such a request is refused.
ALMATY_SINCE = date(2024, 3, 1)
MINUTE = timedelta(minutes=1)
# How far a clean posting may trail or precede its invoice date, in minutes. An injected cutoff error stays
# inside the same range, so the size of a lag never tells an error from a late posting: only the boundary does.
LATE_LAG, EARLY_LAG = 8640, 4320
# The draft's envelope is 200 to 2,000 ledger rows and at most 200 documents. Each company keeps its own margin
# from those edges, drawn from its seed: errors add or remove a few records, and a fixed margin would let the
# counts themselves say "errors were added" at the edges.
EDGE_MARGIN = 14


class Draw:
    """Seeded choices. Every method consumes the stream in a fixed way."""

    def __init__(self, key: bytes, label: str) -> None:
        self._stream = KeyedStream(key, label)

    def below(self, bound: int) -> int:
        return self._stream.below(bound)

    def between(self, low: int, high: int) -> int:
        return low + self._stream.below(high - low + 1)

    def chance(self, percent: int) -> bool:
        return self._stream.below(100) < percent

    def pick(self, items: Sequence[Any]) -> Any:
        return items[self._stream.below(len(items))]

    def shuffled(self, items: Sequence[Any]) -> list[Any]:
        return self._stream.shuffled(items)


def posting_lag(draw: Draw) -> int:
    """Minutes between an invoice's date and its posting: mostly hours, sometimes days, sometimes before."""
    roll = draw.below(100)
    return (
        draw.between(0, 1200)
        if roll < 80
        else draw.between(1440, LATE_LAG)
        if roll < 92
        else -draw.between(1, EARLY_LAG)
    )


def scenario_entry(entry: Any) -> tuple[str, dict[str, str]]:
    """An interaction entry as (name, parameters): a bare name, or an object with "name" and parameters."""
    if isinstance(entry, str):
        name, parameters = entry, {}
    elif isinstance(entry, Mapping) and isinstance(entry.get("name"), str):
        name, parameters = entry["name"], {key: value for key, value in entry.items() if key != "name"}
    else:
        raise EpisodeError(f"an interaction is a scenario name or an object with a 'name'; got {entry!r}")
    if name not in SCENARIO_PARAMETERS:
        raise EpisodeError(f"inject takes a count per family and interactions from {INTERACTIONS}; got {name!r}")
    allowed = SCENARIO_PARAMETERS[name]
    for key, value in parameters.items():
        if key not in allowed or not isinstance(value, str) or value not in allowed[key]:
            raise EpisodeError(f"interaction {name} takes parameters {dict(allowed)}; got {key}={value!r}")
    return name, dict(sorted(parameters.items()))


def scenario_entries(inject: Mapping[str, Any]) -> list[tuple[str, dict[str, str]]]:
    entries = inject.get("interactions", ())
    if not isinstance(entries, list | tuple):
        raise EpisodeError(f"inject.interactions must be a list of scenarios; got {entries!r}")
    return [scenario_entry(entry) for entry in entries]


def normal_inject(inject: Mapping[str, Any]) -> dict[str, Any]:
    """`inject` in one fixed spelling, so that what is recorded regenerates what was built.

    Counts of zero are dropped, and an interaction without parameters is written as its bare name, so an inject
    written before sub-kinds and parameters existed keeps its spelling, its error stream and its episode.
    """
    counts = {family: inject[family] for family in COUNT_KEYS if inject.get(family)}
    scenarios = [name if not parameters else {"name": name, **parameters}
                 for name, parameters in scenario_entries(inject)]  # fmt: skip
    return {**counts, "interactions": scenarios}


def sibling_traits(draw: Draw, first: Mapping[str, Any]) -> tuple[bool, timezone | None]:
    """How a second record at one customer and instant relates to the first, for a valid sibling and a copy alike.

    Returns (posted together with the first, the other offset it is written at or None for the same one). One
    function draws both, so posting time and offset cannot tell a copy from a valid sibling.
    """
    together = draw.chance(50)
    written = when(first["issued_at"]).tzinfo
    zones = [zone for zone in map(parse_offset, sorted(set(ZONES.values()))) if zone != written]
    return together, (draw.pick(zones) if draw.chance(40) else None)


def parse_offset(text: str) -> timezone:
    sign = -1 if text[0] == "-" else 1
    return timezone(sign * timedelta(hours=int(text[1:3]), minutes=int(text[4:6])))


def nice(amount: int) -> int:
    """Keep two significant digits: prices and part payments look typed, not computed."""
    if amount < 100:
        return max(1, amount)
    factor = 10 ** (len(str(amount)) - 2)
    return amount // factor * factor


def in_currency(usd_cents: int, currency: str) -> int:
    """A USD-cent value as minor units of `currency`, at the invented reference values."""
    exact = Fraction(usd_cents, 100) / USD_VALUE[currency] * 10 ** EXPONENTS[currency]
    return max(1, nice(money.round_fraction(exact, "half_up")))


def validate_config(config: Mapping[str, Any]) -> dict[str, Any]:
    unknown = sorted(set(config) - set(DEFAULT_CONFIG))
    if unknown:
        raise EpisodeError(f"unknown generator settings: {unknown}")
    merged = {**DEFAULT_CONFIG, **config}
    currencies = [merged["base_currency"], *merged["foreign_currencies"]]
    if (
        not merged["foreign_currencies"]
        or len(set(currencies)) != len(currencies)
        or not set(currencies) <= set(EXPONENTS)
    ):
        raise EpisodeError("the generator needs a base currency and at least one other, all from its currency table")
    if merged["timezone"] not in ZONES:
        raise EpisodeError(f"timezone must be one of {sorted(ZONES)}: zones without daylight-saving time")
    for name, low, high in (
        ("invoices", 12, 110),
        ("ledger_rows", 200, 2000),
        ("head_days", 3, 12),
        ("tail_days", 3, 12),
    ):
        value = merged[name]
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
            raise EpisodeError(f"generator setting {name} must be an integer in {low}..{high}")
    first, _ = period_bounds(merged["period"])
    if merged["timezone"] == "Asia/Almaty" and date(*first) - timedelta(days=merged["head_days"]) < ALMATY_SINCE:
        raise EpisodeError(
            "timezone Asia/Almaty is UTC+05:00 only from 2024-03-01 (it was UTC+06:00 before): the period start "
            "minus head_days must be on or after 2024-03-01, or choose another zone"
        )
    return merged


def period_bounds(period: str) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    """First and last calendar day of 'YYYY-MM' or 'YYYY-Qn'."""
    try:
        year, part = int(period[:4]), period[5:]
        first, last = (3 * int(part[1]) - 2, 3 * int(part[1])) if part.startswith("Q") else (int(part), int(part))
        if period[4] != "-" or not 1 <= first <= last <= 12 or not 2000 <= year <= 2100:
            raise ValueError(period)
    except (ValueError, IndexError) as exc:
        raise EpisodeError("period must look like 2026-10 or 2026-Q3") from exc
    return (year, first, 1), (year, last, calendar.monthrange(year, last)[1])


def _rates(draw: Draw, base: str, foreign: Sequence[str], first_day: datetime, days: int) -> list[dict[str, str]]:
    """Daily rates for each pair, quoted in one direction only, on a small random walk."""
    table = []
    for currency in foreign:
        source, target = (currency, base) if draw.chance(60) else (base, currency)
        level = USD_VALUE[source] / USD_VALUE[target]  # target units per source unit
        decimals = 2
        while level * 10**decimals < 10_000 and decimals < 9:  # at least five significant digits
            decimals += 1
        scaled = money.round_fraction(level * 10**decimals * Fraction(draw.between(970, 1030), 1000), "half_up")
        for day in range(days):
            step = scaled * draw.between(-90, 90) // 10_000
            scaled = max(1, scaled + (step or draw.pick((-1, 1))))
            digits = str(scaled).rjust(decimals + 1, "0")
            table.append({
                "date": (first_day + timedelta(days=day)).date().isoformat(), "source_currency": source,
                "target_currency": target, "rate": f"{digits[:-decimals]}.{digits[-decimals:]}",
            })  # fmt: skip
    return table


def generate_world(seed: int, config: Mapping[str, Any], secret: bytes) -> dict[str, Any]:
    """The latent company for a seed and config. Errors are not part of it: twins share one world."""
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise EpisodeError("seed must be a non-negative integer")
    settings = validate_config(config)
    tag = f"{BUILDER_VERSION}|{seed}|{canon.digest(settings)}"
    draw = Draw(secret, f"world|{tag}")
    base, foreign = settings["base_currency"], list(settings["foreign_currencies"])
    company = parse_offset(ZONES[settings["timezone"]])
    first, last = period_bounds(settings["period"])
    start = datetime(*first, 0, 0, 0, tzinfo=company)
    end = datetime(*last, 23, 59, 59, tzinfo=company)
    opens = start - timedelta(days=settings["head_days"])
    closes = end + timedelta(days=settings["tail_days"])
    window_minutes = int((closes - opens).total_seconds() // 60)
    world: dict[str, Any] = {
        "tag": tag,
        "base_currency": base,
        "currencies": {code: {"exponent": EXPONENTS[code]} for code in (base, *foreign)},
        "timezone": settings["timezone"],
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "fx": _rates(draw, base, foreign, opens - timedelta(days=2), (closes - opens).days + 6),
        "invoices": [], "payments": [], "refunds": [], "entries": [],
    }  # fmt: skip
    document_room = 200 - draw.between(0, EDGE_MARGIN)
    fewest_rows, most_rows = 200 + 2 * draw.between(0, EDGE_MARGIN), 2000 - 2 * draw.between(0, EDGE_MARGIN)
    taken: set[str] = set()

    def fresh(prefix: str, key: str) -> str:
        return new_id(secret, tag, prefix, key, taken)

    # ------------------------------------------------------------------ customers
    other_offsets = [parse_offset(text) for text in sorted(set(ZONES.values())) if parse_offset(text) != company]
    far = max(other_offsets, key=lambda zone: abs(zone.utcoffset(None) - company.utcoffset(None)))
    customers = []
    for number in range(max(6, min(30, settings["invoices"] // 4))):
        remote = number % 3 == 1 or draw.chance(20)  # forced for some, so every company has remote customers
        bills_foreign = number % 4 == 2 or (number > 0 and draw.chance(25))  # customer 0 in base, customer 2 abroad
        offset = draw.pick(other_offsets) if remote else company
        customers.append({
            "entity_id": fresh("E", f"customer:{number}"),
            "offset": offset,
            "billing_offset": offset if remote and draw.chance(50) else company,
            "currency": draw.pick(foreign) if bills_foreign else base,
            "other_currency": draw.pick(foreign),
            "pays_other_currency": number % 3 == 0 or draw.chance(10),
            "subscribes": number % 7 == 4,
        })  # fmt: skip
    vendors = [fresh("E", f"vendor:{number}") for number in range(draw.between(3, 8))]

    # ------------------------------------------------------------------- invoices
    issued: set[tuple[str, datetime]] = set()

    def add_invoice(customer: Mapping[str, Any], instant: datetime, lines: Sequence[tuple[str, int, int]], *,
                    written_at: tzinfo | None = None, terms: int | None = None, beside: bool = False) -> datetime | None:  # fmt: skip
        """Add one invoice and return its instant. `beside` allows a second invoice of one customer at one instant."""
        instant = instant.replace(second=0, microsecond=0)
        while not beside and (customer["entity_id"], instant) in issued:
            instant += MINUTE
        if not opens <= instant <= closes:
            return None
        issued.add((customer["entity_id"], instant))
        # Usually the customer's own offset, sometimes another branch's: an unusual offset is not a mark of anything.
        written_at = written_at or (draw.pick(other_offsets) if draw.chance(10) else customer["billing_offset"])
        number = len(world["invoices"])
        # Most postings follow within hours. Some are days late and some precede the invoice date, so neither a
        # long lag nor a negative one marks an error. In clean books a posting never crosses a period boundary.
        posted = instant + posting_lag(draw) * MINUTE
        if side(world, posted.isoformat()) != side(world, instant.isoformat()):
            posted = instant
        due = instant + timedelta(days=terms or draw.pick((7, 14, 21, 30)))
        world["invoices"].append({
            "key": f"invoice:{number}",
            "doc_id": fresh("D", f"invoice-doc:{number}"),
            "invoice_id": fresh("I", f"invoice:{number}"),
            "entity_id": customer["entity_id"],
            "issued_at": instant.astimezone(written_at).isoformat(),
            "due_at": due.astimezone(written_at).isoformat(),
            "currency": customer["currency"],
            "line_items": [
                {"description": text, "quantity": quantity, "unit_price_minor": price, "amount_minor": quantity * price}
                for text, quantity, price in lines
            ],
            "posted_at": posted.astimezone(company).isoformat(),
        })  # fmt: skip
        return instant

    def lines_for(customer: Mapping[str, Any], count: int) -> list[tuple[str, int, int]]:
        items = draw.shuffled(CATALOGUE)[:count]
        return [(text, draw.between(1, 9), in_currency(cents, customer["currency"])) for text, cents in items]

    # One early invoice in the base currency and one in a foreign currency, so that both can be settled by a
    # receipt in the other currency whatever else the seed brings.
    for customer in (customers[0], customers[2]):
        add_invoice(
            customer, opens + timedelta(minutes=draw.between(480, 3 * 1440)), lines_for(customer, draw.between(1, 2))
        )
    for customer in customers:  # recurring invoices: identical lines, a week apart
        if customer["subscribes"]:
            lines = lines_for(customer, 1)
            instant = opens + timedelta(days=draw.between(0, 6), hours=draw.between(8, 17))
            while instant <= closes:
                add_invoice(customer, instant, lines)
                instant += timedelta(days=7)
    remote_billers = [c for c in customers if c["billing_offset"] != company] or customers
    for boundary, minutes in ((end, -1), (end, -1), (end, 1), (end, 1), (start, -1), (start, 1)):
        customer = draw.pick(remote_billers if draw.chance(60) else customers)  # issued minutes from a boundary
        add_invoice(
            customer, boundary + minutes * draw.between(2, 300) * MINUTE, lines_for(customer, draw.between(1, 2))
        )
    # One invoice whose printed date is on the other side of the period end than its instant.
    after_midnight = end + timedelta(seconds=1)
    west = far.utcoffset(None) < company.utcoffset(None)
    customer = draw.pick(customers)
    add_invoice(
        customer,
        after_midnight + (1 if west else -1) * draw.between(5, 100) * MINUTE,
        lines_for(customer, 1),
        written_at=far,
    )
    by_currency: dict[str, list[dict[str, Any]]] = {}
    for customer in draw.shuffled(customers):
        by_currency.setdefault(customer["currency"], []).append(customer)
    sharing = [group for _, group in sorted(by_currency.items(), key=lambda item: item[0] != base) if len(group) > 1]
    for _ in range(2 if sharing else 0):  # identical invoices to two different customers at one instant
        pair = draw.shuffled(sharing[0])[:2]
        lines = lines_for(pair[0], 1)
        instant = opens + draw.between(0, window_minutes) * MINUTE
        for customer in pair:
            add_invoice(customer, instant, lines)
    guard = 0
    # How many second records a company has is drawn, not computed: a fixed number would let a count of them
    # say how many copies were added on top.
    sibling_count = draw.between(max(2, settings["invoices"] // 8), max(3, settings["invoices"] // 3))
    while len(world["invoices"]) < settings["invoices"] - sibling_count and guard < 10 * settings["invoices"]:
        guard += 1
        customer = draw.pick(customers)
        day = opens + timedelta(days=draw.between(0, (closes - opens).days))
        minute = draw.between(0, 1439) if customer["offset"] != company else draw.between(480, 1139)
        add_invoice(customer, day.replace(hour=0, minute=0) + minute * MINUTE, lines_for(customer, draw.between(1, 3)))

    # Two postings well inside a side are always late or early by days, so no company lacks that look-alike.
    week = timedelta(days=8)
    inner = [i for i in world["invoices"]
             if all(abs(when(i["issued_at"]) - boundary) >= week for boundary in (start, end))]  # fmt: skip
    for invoice, minutes in zip(
        draw.shuffled(inner)[:2], (draw.between(1440, 8640), -draw.between(60, 4320)), strict=False
    ):
        invoice["posted_at"] = (when(invoice["issued_at"]) + minutes * MINUTE).astimezone(company).isoformat()

    # Valid siblings: a second invoice of one customer at one instant that is not a duplicate. Each is made from an
    # invoice chosen at random, exactly as a copy is, and then differs from it in one of the two things the
    # duplicate rule names beyond customer, currency and instant: half have one line replaced, half have other
    # payment terms. In everything else (when it is posted, the offset it is written at, having no receipt) a
    # sibling is drawn as a copy is, and a company has more siblings than it can have copies. So the first record
    # of a pair says nothing, and only comparing lines and due date tells a copy from a sibling.
    siblings: set[str] = set()

    def obligation(invoice: Mapping[str, Any]) -> tuple[Any, ...]:
        """What the duplicate rule compares. Two clean records must never agree in all of it."""
        return (invoice["entity_id"], invoice["currency"], when(invoice["issued_at"]), when(invoice["due_at"]),
                canon.dumps(invoice["line_items"]))  # fmt: skip

    recorded = {obligation(invoice) for invoice in world["invoices"]}
    for number in range(sibling_count):
        # Any record may get a sibling, also one that has one already and a sibling itself, as any record may
        # be copied: three records of one customer at one instant are then nothing special.
        original = draw.pick(world["invoices"])
        together, elsewhere = sibling_traits(draw, original)
        instant = when(original["issued_at"])
        posted = instant + posting_lag(draw) * MINUTE
        if together or side(world, posted.isoformat()) != side(world, original["issued_at"]):
            posted = when(original["posted_at"])
        zone = elsewhere or instant.tzinfo
        for _ in range(8):  # draw the difference again if it would make the sibling identical to another record
            copied: list[dict[str, Any]] = [dict(line) for line in original["line_items"]]
            due = when(original["due_at"])
            if number % 2:
                terms = [days for days in (7, 14, 21, 30) if days != (due - instant).days]
                due = instant + timedelta(days=draw.pick(terms))
            else:
                unused = [item for item in CATALOGUE if item[0] not in {line["description"] for line in copied}]
                text, cents = draw.pick(unused)
                quantity, price = draw.between(1, 9), in_currency(cents, original["currency"])
                copied[draw.below(len(copied))] = {"description": text, "quantity": quantity, "unit_price_minor": price,
                                                 "amount_minor": quantity * price}  # fmt: skip
            key = len(world["invoices"])
            sibling = {
                "key": f"invoice:{key}",
                "doc_id": "",
                "invoice_id": "",
                "entity_id": original["entity_id"],
                "issued_at": instant.astimezone(zone).isoformat(),
                "due_at": due.astimezone(zone).isoformat(),
                "currency": original["currency"],
                "line_items": copied,
                "posted_at": posted.astimezone(company).isoformat(),
            }
            if obligation(sibling) not in recorded:
                sibling.update(doc_id=fresh("D", f"invoice-doc:{key}"), invoice_id=fresh("I", f"invoice:{key}"))
                recorded.add(obligation(sibling))
                world["invoices"].append(sibling)
                siblings.add(sibling["invoice_id"])
                break

    # ------------------------------------------------------------------- receipts
    by_entity = {customer["entity_id"]: customer for customer in customers}
    receipt_times: dict[str, set[datetime]] = {}

    def add_payment(refs: Sequence[Mapping[str, Any]], amount: int, instant: datetime, currency: str,
                    offset: timezone) -> str | None:  # fmt: skip
        instant = instant.replace(second=0, microsecond=0)
        while any(instant in receipt_times.get(ref["invoice_id"], ()) for ref in refs):
            instant += MINUTE
        if instant > closes or amount <= 0 or len(world["invoices"]) + len(world["payments"]) >= document_room:
            return None  # too late, nothing to pay, or the document envelope is full: the invoice stays open
        for ref in refs:
            receipt_times.setdefault(ref["invoice_id"], set()).add(instant)
        number = len(world["payments"])
        world["payments"].append({
            "key": f"payment:{number}",
            "doc_id": fresh("D", f"payment-doc:{number}"),
            "payment_id": fresh("P", f"payment:{number}"),
            "timestamp": instant.astimezone(offset).isoformat(),
            "currency": currency,
            "amount_minor": amount,
            "invoice_refs": [ref["invoice_id"] for ref in refs],
        })  # fmt: skip
        return world["payments"][-1]["payment_id"]

    def refund(payment_id: str | None, amount: int, instant: datetime) -> None:
        if payment_id is not None and instant <= closes:
            world["refunds"].append(
                {"payment_id": payment_id, "timestamp": instant.isoformat(), "amount_minor": amount}
            )

    ordered = sorted(world["invoices"], key=lambda i: (when(i["issued_at"]), i["invoice_id"]))
    # Every company gets each valid look-alike at least once, whatever the dice say: three receipts in another
    # currency (one printed with another date than its local one), a double payment and an overpayment that are
    # refunded, a split payment and a part payment. They go to invoices issued early enough to be settled.
    payable = [i for i in ordered if i["invoice_id"] not in siblings]
    early = [i for i in payable if when(i["issued_at"]) <= closes - timedelta(days=21)]
    if len(early) < 7:  # a very small company: take its earliest invoices, whatever room they leave
        early = payable[:7]
    early = draw.shuffled(early)
    # A base-currency invoice paid in a foreign currency and a foreign invoice paid in the base currency, on one
    # pair: whichever way the pair is quoted, one of the two translations multiplies and the other divides.
    found = [next((i for i in early if (i["currency"] == base) == in_base), None) for in_base in (True, False)]
    lead = [invoice for invoice in found if invoice is not None]
    forced_order = [i["invoice_id"] for i in (*lead, *(i for i in early if i not in lead))]
    forced = dict(zip(forced_order, (60, 60, 60, 80, 70, 50, 65), strict=False))  # the roll that selects each kind
    crossing_forced = set(forced_order[:3])
    far_cross = set(forced_order[1:3])  # two of the three, so one stays valid when an error takes the other
    pair_currency = lead[1]["currency"] if len(lead) == 2 else None
    add_payment(
        [],
        in_currency(draw.between(4_000, 90_000), base),
        opens + draw.between(0, window_minutes) * MINUTE,
        base,
        company,
    )
    batched: set[str] = set()
    for position, invoice in enumerate(ordered):
        if invoice["invoice_id"] in batched or invoice["invoice_id"] in siblings:
            continue  # a sibling stays open, as a copy does: an unpaid second record marks neither
        customer, total = by_entity[invoice["entity_id"]], invoice_total(invoice)
        offset = customer["offset"]
        must = forced.get(invoice["invoice_id"])
        crossing = customer["pays_other_currency"] if must is None else invoice["invoice_id"] in crossing_forced
        paid_at = when(invoice["issued_at"]) + timedelta(
            days=draw.between(1, 8 if must else 20), minutes=draw.between(0, 1439)
        )
        roll = draw.below(100) if must is None else must
        if invoice["invoice_id"] in far_cross:  # minutes from local midnight, written at the farthest offset
            midnight = paid_at.astimezone(company).replace(hour=0, minute=0)
            west = far.utcoffset(None) < company.utcoffset(None)
            paid_at, offset = midnight + (1 if west else -1) * draw.between(5, 100) * MINUTE, far
        if crossing and roll < 75:  # a receipt in another currency than the invoice
            currency = base if invoice["currency"] != base else customer["other_currency"]
            if must is not None and invoice["currency"] == base and pair_currency:
                currency = pair_currency
            if paid_at > closes:
                continue
            probe = {
                "payment_id": "-",
                "timestamp": paid_at.isoformat(),
                "currency": invoice["currency"],
                "amount_minor": total,
            }
            selected = policy_rate(world, probe, currency)
            amount = translate(world, probe, currency, selected["rate"], selected["source_currency"])
            add_payment(
                [invoice],
                amount * draw.between(55, 75) // 100 if must is None and draw.chance(20) else amount,
                paid_at,
                currency,
                offset,
            )
        elif roll < 44:  # one receipt for the whole invoice
            add_payment([invoice], total, paid_at, invoice["currency"], offset)
        elif roll < 60:  # split payments
            first_part = nice(total * draw.between(30, 70) // 100)
            add_payment([invoice], first_part, paid_at, invoice["currency"], offset)
            later = paid_at + timedelta(days=draw.between(1, 6), minutes=draw.between(1, 600))
            if total - first_part > 0:
                add_payment([invoice], total - first_part, later, invoice["currency"], offset)
        elif roll < 69:  # a part payment: the rest stays open, which is not an error
            add_payment([invoice], nice(total * draw.between(30, 80) // 100), paid_at, invoice["currency"], offset)
        elif roll < 77:  # an overpayment; sometimes the excess is refunded
            extra = nice(max(1, total * draw.between(5, 25) // 100))
            payment_id = add_payment([invoice], total + extra, paid_at, invoice["currency"], offset)
            if must or draw.chance(50):
                refund(payment_id, extra, paid_at + timedelta(days=draw.between(2, 5), minutes=draw.between(0, 500)))
        elif roll < 82:  # the customer pays twice; the second receipt has nothing to settle
            add_payment([invoice], total, paid_at, invoice["currency"], offset)
            again = paid_at + timedelta(days=draw.between(1, 4), minutes=draw.between(1, 700))
            payment_id = add_payment([invoice], total, again, invoice["currency"], offset)
            if must or draw.chance(70):
                refund(payment_id, total, again + timedelta(days=draw.between(1, 4), minutes=draw.between(0, 500)))
        elif roll < 90:  # one receipt for two invoices of the same customer
            partner = next((other for other in ordered[position + 1 :]
                            if other["entity_id"] == invoice["entity_id"] and other["invoice_id"] not in batched
                            and other["invoice_id"] not in forced and other["invoice_id"] not in siblings
                            and when(other["issued_at"]) - when(invoice["issued_at"]) <= timedelta(days=10)), None)  # fmt: skip
            if partner is None:
                add_payment([invoice], total, paid_at, invoice["currency"], offset)
                continue
            batched.add(partner["invoice_id"])
            paid_at = when(partner["issued_at"]) + timedelta(days=draw.between(1, 12), minutes=draw.between(0, 1439))
            second = (
                invoice_total(partner)
                if draw.chance(70)
                else nice(invoice_total(partner) * draw.between(30, 80) // 100)
            )
            refs = [invoice, partner] if draw.chance(75) else [partner, invoice]
            add_payment(refs, total + second, paid_at, invoice["currency"], offset)
        # otherwise the invoice stays unpaid: an open invoice with no receipt is not an error
    for _ in range(len(world["payments"]) // 40):  # more receipts that name no invoice (one is always there)
        instant = opens + draw.between(0, window_minutes) * MINUTE
        add_payment([], in_currency(draw.between(4_000, 90_000), base), instant, base, company)

    # ------------------------------------------------------- other journal entries
    posted_rows = len(derive(world).rows)
    # A few more or fewer than the target asks for, so the row count of clean books is no rounder than any other.
    wanted = (settings["ledger_rows"] - posted_rows) // 2 + draw.between(-7, 7)
    fewest, most = -(-(fewest_rows - posted_rows) // 2), (most_rows - posted_rows) // 2  # this company's own margins
    for number in range(max(0, fewest, min(wanted, most))):
        debit, credit = draw.pick(ENTRY_KINDS)
        currency = draw.pick(foreign) if draw.chance(8) else base
        instant = opens + timedelta(days=draw.between(0, (closes - opens).days), minutes=draw.between(480, 1139))
        world["entries"].append({
            "key": f"entry:{number}", "timestamp": min(instant, closes).isoformat(), "debit_account": debit,
            "credit_account": credit, "amount_minor": in_currency(draw.between(1_500, 600_000), currency),
            "currency": currency, "entity_id": draw.pick(vendors) if draw.chance(70) else None,
        })  # fmt: skip
    return world


# ---------------------------------------------------------------------- the clerk's errors


def _part(draw: Draw, required: int) -> int:
    """A typed-looking part of `required`, at least 1 and below it. `required` must be at least 2."""
    part = nice(required * draw.between(20, 80) // 100)
    return part if 0 < part < required else required // 2


def _partial(draw: Draw, required: int) -> int:
    """How much the clerk applied: nothing (a missing allocation) or a typed-looking part."""
    if draw.chance(30) or required < 2:
        return 0
    return _part(draw, required)


def _applied(draw: Draw, required: int, mode: str | None) -> int:
    """What the clerk applied for a requested sub-kind: "missing" applies nothing, "partial" a part, None draws."""
    if mode is None:
        return _partial(draw, required)
    return 0 if mode == "missing" else _part(draw, required)


def _swapped(digits: str, at: int) -> str:
    return digits[:at] + digits[at + 1] + digits[at] + digits[at + 2 :]


def _drawn_rates(
    draw: Draw, selected: Mapping[str, Any], table: Mapping[str, str], nearby: list[str], literal: str
) -> list[tuple[str, str]]:
    """The mixed stream of wrong rates: the printed date's, a nearby day's, or the right one mistyped."""
    candidates: list[tuple[str, str]] = []
    if literal != selected["date"] and draw.chance(70):
        candidates.append((literal, table.get(literal, "")))
    candidates += [(day, table.get(day, "")) for day in nearby]
    digits = selected["rate"]
    swaps = [
        i
        for i in range(len(digits) - 1)
        if digits[i].isdigit() and digits[i + 1].isdigit() and digits[i] != digits[i + 1]
    ]
    if swaps and draw.chance(30):
        candidates.insert(0, ("mistyped", _swapped(digits, draw.pick(swaps))))
    return candidates


def _rates_of_kind(
    draw: Draw, kind: str, selected: Mapping[str, Any], table: Mapping[str, str], nearby: list[str], literal: str
) -> list[tuple[str, str]]:
    """Wrong rates of one sub-kind: "date" is the table rate of another date, "rate" a rate on no table row."""
    if kind == "date":
        days = ([literal] if literal != selected["date"] else []) + nearby
        return [(day, table[day]) for day in days if day in table and day != selected["date"]]
    digits = selected["rate"]
    swaps = [i for i in range(len(digits) - 1) if digits[i].isdigit() and digits[i + 1].isdigit()]
    typed = [_swapped(digits, at) for at in draw.shuffled(swaps)]
    return [("mistyped", rate) for rate in typed if rate != digits and rate not in table.values()]


def _wrong_rate(
    world: Mapping[str, Any], payment: Mapping[str, Any], clean: Derived, draw: Draw, kind: str | None = None
) -> dict[str, Any] | None:
    """A rate the policy does not select for this receipt: another day's, or the right one mistyped.

    `kind` None draws among both; "date" takes another date's table rate; "rate" a mistyped rate whose
    translation no table rate of the pair gives, so the books show which of the two it is.
    """
    by_id = {invoice["invoice_id"]: invoice for invoice in world["invoices"]}
    target = by_id[payment["invoice_refs"][0]]["currency"]
    selected = policy_rate(world, payment, target)
    required = next(amount for key, _, amount in clean.translations if key == payment["payment_id"])
    pair = {selected["source_currency"], selected["target_currency"]}
    table = {
        row["date"]: row["rate"] for row in world["fx"] if {row["source_currency"], row["target_currency"]} == pair
    }
    day = datetime.fromisoformat(selected["date"])
    nearby = [(day + timedelta(days=shift)).date().isoformat() for shift in draw.shuffled((-3, -2, -1, 1, 2, 3))]
    literal = payment["timestamp"][:10]  # the date as written, at the record's own offset
    if kind is None:
        candidates = _drawn_rates(draw, selected, table, nearby, literal)
    else:
        candidates = _rates_of_kind(draw, kind, selected, table, nearby, literal)
    on_table: set[int] = set()
    if kind == "rate":
        on_table = {translate(world, payment, target, rate, selected["source_currency"]) for rate in table.values()}
    for source, rate in candidates:
        try:
            other = translate(world, payment, target, rate, selected["source_currency"])
        except ValueError:
            continue
        if 0 < other != required and other not in on_table:
            return {"family": FX, "payment_id": payment["payment_id"], "rate": rate, "rate_source": source}
    return None


def crossings(world: Mapping[str, Any], invoice: Mapping[str, Any]) -> list[tuple[str, datetime, datetime]]:
    """Where a posting of this invoice can sit on another side of the period with a lag clean postings also show.

    Each entry is (boundary, earliest, latest) in whole minutes. An invoice far from both boundaries has none.
    """
    start, end = when(world["period_start"]), when(world["period_end"])
    issued = when(invoice["issued_at"])
    earliest, latest = issued - EARLY_LAG * MINUTE, issued + LATE_LAG * MINUTE
    first_after, last_inside = end + timedelta(seconds=1), end.replace(second=0)
    where = side(world, invoice["issued_at"])
    found = []
    if where == "in" and latest >= first_after:
        found.append(("end", first_after, latest))  # posted late, into the next period
    if where == "in" and earliest < start:
        found.append(("start", earliest, start - MINUTE))  # backdated into the period before
    if where == "after" and earliest <= last_inside:
        found.append(("end", max(earliest, start), last_inside))  # backdated into the period
    if where == "before" and latest >= start:
        found.append(("start", start, min(latest, last_inside)))  # posted late, into the period
    return found


def _validated_counts(inject: Mapping[str, Any]) -> dict[str, int]:
    """The count of each inject key, refused with a reason when a key or a count is not one we know."""
    unknown = sorted(set(inject) - set(COUNT_KEYS) - {"interactions"})
    counts = {family: inject.get(family, 0) for family in COUNT_KEYS}
    if unknown or any(isinstance(n, bool) or not isinstance(n, int) or n < 0 for n in counts.values()):
        raise EpisodeError(
            f"inject takes a non-negative integer count for each of {list(COUNT_KEYS)} and interactions from "
            f"{INTERACTIONS}; got {unknown or counts}"
        )
    return counts


def validate_inject(inject: Mapping[str, Any]) -> int:
    """Checks every inject key, count and interaction entry; returns how many issues the request asks for.

    Each count gives one issue and each interaction two. More than the case envelope allows is refused here,
    with the message the built episode would give, before anything is generated.
    """
    counts = _validated_counts(inject)
    issues = sum(counts.values()) + 2 * len(scenario_entries(inject))
    low, high = ENVELOPE["issues"]
    if not low <= issues <= high:
        raise EpisodeError(f"inject: issues = {issues} is outside the case envelope {low}..{high}")
    return issues


def _boundaries(world: Mapping[str, Any], invoice: Mapping[str, Any]) -> list[str]:
    return [name for name, _, _ in crossings(world, invoice)]


def plan_errors(world: Mapping[str, Any], inject: Mapping[str, Any], secret: bytes) -> list[dict[str, Any]]:
    """Choose what the clerk got wrong: `inject` gives a count per family and a list of interaction scenarios."""
    counts = _validated_counts(inject)
    scenarios = scenario_entries(inject)
    draw = Draw(secret, f"inject|{world['tag']}|{canon.digest(normal_inject(inject))}")
    clean = derive(world)
    invoices = {invoice["invoice_id"]: invoice for invoice in world["invoices"]}
    payments = {payment["payment_id"]: payment for payment in world["payments"]}
    company = when(world["period_start"]).tzinfo
    taken = {record[name] for table, name in (("invoices", "invoice_id"), ("invoices", "doc_id"), ("payments", "doc_id"))
             for record in world[table]}  # fmt: skip
    parked = {row["payment_id"] for row in clean.rows if row["key"].endswith(":unapplied") and row["credit_minor"]}
    used_invoices: set[str] = set()
    used_payments: set[str] = set()
    # Records whose printed date misleads (another side of the period, or another day, than the instant). They are
    # the look-alikes of the cutoff and FX errors: an error may take one of them, never the last valid one.
    first_day, last_day = world["period_start"][:10], world["period_end"][:10]

    def printed_side(timestamp: str) -> str:
        return "before" if timestamp[:10] < first_day else "after" if timestamp[:10] > last_day else "in"

    misprinted_invoices = {
        key for key, i in invoices.items() if printed_side(i["issued_at"]) != side(world, i["issued_at"])
    }
    misprinted_receipts = {key for key, day, _ in clean.translations if payments[key]["timestamp"][:10] != day}

    def spare(key: str, kind: set[str], used: set[str]) -> bool:
        return key not in kind or bool(kind - used - {key})

    errors: list[dict[str, Any]] = []

    def free_allocations(source: Derived) -> list[tuple[str, str, int]]:
        return [a for a in draw.shuffled(source.allocations) if a[0] not in used_payments and a[1] not in used_invoices]

    def followed_by_credit(payment_id: str, invoice_id: str) -> bool:
        """A later receipt for the same invoice leaves unapplied credit: only the open-balance rule tells the two apart."""
        return any(other["payment_id"] in parked and invoice_id in other["invoice_refs"]
                   and when(other["timestamp"]) > when(payments[payment_id]["timestamp"]) for other in payments.values())  # fmt: skip

    def self_sufficient(allocation: tuple[str, str, int]) -> bool:
        """The required amount follows from the two documents alone: min(receipt amount, invoice total).

        True when the receipt is in the invoice's currency, names the invoice first, and no earlier receipt names it.
        """
        payment, invoice_id = payments[allocation[0]], allocation[1]
        if payment["currency"] != invoices[invoice_id]["currency"] or payment["invoice_refs"][0] != invoice_id:
            return False
        at = when(payment["timestamp"])
        return not any(invoice_id in other["invoice_refs"] and when(other["timestamp"]) < at
                       for other in payments.values())  # fmt: skip

    def receipt_currency(allocation: tuple[str, str, int]) -> str:
        """ "same" when the receipt is in its invoice's currency, else "foreign" (interaction 1's parameter)."""
        return "same" if payments[allocation[0]]["currency"] == invoices[allocation[1]]["currency"] else "foreign"

    def under_applied(
        source: Derived, pool: Sequence[tuple[str, str, int]] | None = None, mode: str | None = None
    ) -> dict[str, Any]:
        candidates = list(free_allocations(source) if pool is None else pool)
        if mode is not None:  # a requested sub-kind: a part needs at least 2 minor units to split
            candidates = [a for a in candidates if mode == "missing" or a[2] >= 2]
            candidates = [a for a in candidates if self_sufficient(a)] or candidates
        hard = [a for a in candidates if followed_by_credit(a[0], a[1])]
        if hard and draw.chance(50):
            candidates = hard
        if not candidates:
            wanted = f" as a {mode} allocation" if mode else ""
            raise EpisodeError(f"no settled invoice is left to under-apply{wanted}")
        payment_id, invoice_id, required = candidates[0]
        return {
            "family": ALLOCATION,
            "payment_id": payment_id,
            "invoice_id": invoice_id,
            "applied_minor": _applied(draw, required, mode),
        }

    def duplicate_of(original: Mapping[str, Any], offset: str | None = None) -> dict[str, Any]:
        # Posted with the original or whenever, written at its offset or another: drawn as for a valid sibling.
        together, elsewhere = sibling_traits(draw, original)
        if offset == "same":
            elsewhere = None
        elif offset == "other" and elsewhere is None:
            written = when(original["issued_at"]).tzinfo
            elsewhere = draw.pick([zone for zone in map(parse_offset, sorted(set(ZONES.values()))) if zone != written])
        posted = when(original["issued_at"]) + posting_lag(draw) * MINUTE
        if together or side(world, posted.isoformat()) != side(world, original["issued_at"]):
            posted = when(original["posted_at"])
        copy = {"invoice_id": new_id(secret, world["tag"], "I", "copy:" + original["invoice_id"], taken),
                "doc_id": new_id(secret, world["tag"], "D", "copy-doc:" + original["invoice_id"], taken),
                "posted_at": posted.astimezone(company).isoformat()}  # fmt: skip
        if (
            elsewhere is not None
        ):  # keyed from a paper printed at another offset: the same instants, written differently
            copy["issued_at"] = when(original["issued_at"]).astimezone(elsewhere).isoformat()
            copy["due_at"] = when(original["due_at"]).astimezone(elsewhere).isoformat()
        return {"family": DUPLICATE, "invoice_id": original["invoice_id"], "copy": copy}

    def wrong_rate_error(kind: str | None = None) -> dict[str, Any]:
        order = draw.shuffled(clean.translations)
        first_of_its_kind = not any(error["family"] == FX for error in errors)
        if first_of_its_kind and draw.chance(
            50
        ):  # a receipt whose printed date is not its local date: the classic mistake
            order.sort(key=lambda translation: payments[translation[0]]["timestamp"][:10] == translation[1])
        for payment_id, _, _ in order:
            free = payment_id not in used_payments and not set(payments[payment_id]["invoice_refs"]) & used_invoices
            if free and spare(payment_id, misprinted_receipts, used_payments):
                error = _wrong_rate(world, payments[payment_id], clean, draw, kind)
                if error is not None:
                    return error
        wanted = {None: "", "date": " at another date's rate", "rate": " at a rate on no table row"}[kind]
        raise EpisodeError(f"no receipt in another currency is left to mistranslate{wanted}")

    def misdated(
        invoice: Mapping[str, Any], invoice_id: str | None = None, boundary: str | None = None
    ) -> dict[str, Any] | None:
        """A posting of this invoice (or of its copy) on another side of the period, at either boundary."""
        ranges = crossings(world, invoice)
        if not ranges:
            return None
        drawn = draw.pick(("start", "end"))
        _, low, high = next((r for r in ranges if r[0] == (boundary or drawn)), ranges[0])
        moved = low + draw.between(0, int((high - low).total_seconds() // 60)) * MINUTE
        return {
            "family": CUTOFF,
            "invoice_id": invoice_id or invoice["invoice_id"],
            "posted_at": moved.astimezone(company).isoformat(),
        }

    def near_a_boundary() -> list[Mapping[str, Any]]:
        """Unused invoices close enough to a boundary to be misdated, the wanted boundary first."""
        boundary = draw.pick(("start", "end"))
        pool = [
            i
            for i in draw.shuffled(list(invoices.values()))
            if i["invoice_id"] not in used_invoices
            and crossings(world, i)
            and spare(i["invoice_id"], misprinted_invoices, used_invoices)
        ]
        return sorted(pool, key=lambda i: boundary not in _boundaries(world, i))

    def claim(error: Mapping[str, Any] | None) -> None:
        if error is None:
            raise EpisodeError("no invoice is left close enough to a period boundary to be misdated")
        errors.append(dict(error))
        used_invoices.update(i for i in (error.get("invoice_id"), error.get("copy", {}).get("invoice_id")) if i)
        if "payment_id" in error:
            used_payments.add(error["payment_id"])
            used_invoices.update(payments[error["payment_id"]]["invoice_refs"])

    def fx_then_allocation(parameters: Mapping[str, str]) -> None:
        """The receipt is mistranslated, and then under-applied as well."""
        wrong = wrong_rate_error(parameters.get("fx_error"))
        payment_id = wrong["payment_id"]
        trial = derive(world, [*errors, wrong])
        pool = [a for a in trial.allocations if a[0] == payment_id and a[2] >= 2]
        if not pool:
            raise EpisodeError("the mistranslated receipt has nothing left to under-apply")
        mode = parameters.get("allocation")
        applied = (_partial(draw, pool[0][2]) or pool[0][2] // 2) if mode is None else _applied(draw, pool[0][2], mode)
        claim(wrong)
        claim({"family": ALLOCATION, "payment_id": payment_id, "invoice_id": pool[0][1], "applied_minor": applied})

    def duplicate_then_cutoff(parameters: Mapping[str, str]) -> None:
        """The second copy is also posted on the wrong side of the period."""
        boundary = parameters.get("boundary")
        candidates = [i for i in near_a_boundary() if boundary is None or boundary in _boundaries(world, i)]
        if not candidates:
            raise EpisodeError(f"no invoice near the period {boundary or 'boundary'} is left to duplicate")
        copied = duplicate_of(candidates[0], parameters.get("copy_offset"))
        claim(copied)
        claim(misdated(candidates[0], copied["copy"]["invoice_id"], boundary))

    def cutoff_and_allocation(parameters: Mapping[str, str]) -> None:
        """One invoice, posted on the wrong side, and its receipt under-applied."""
        boundary, receipt, mode = (parameters.get(name) for name in ("boundary", "receipt_currency", "allocation"))
        pool = [a for a in free_allocations(clean) if crossings(world, invoices[a[1]])
                and spare(a[1], misprinted_invoices, used_invoices)]  # fmt: skip
        if parameters:  # asked for by parameters: only allocations that can carry them
            pool = [a for a in pool if (boundary is None or boundary in _boundaries(world, invoices[a[1]]))
                    and (mode != "partial" or a[2] >= 2)]  # fmt: skip
            if receipt is None:  # left out: drawn from the seed among the currencies the pool still offers
                offered = sorted({receipt_currency(a) for a in pool})
                receipt = draw.pick(offered) if offered else None
            pool = [a for a in pool if receipt is None or receipt_currency(a) == receipt]
            pool = [a for a in pool if self_sufficient(a)] or pool
        if not pool:
            asked = f" with {dict(parameters)}" if parameters else ""
            raise EpisodeError(
                f"no settled invoice near a period boundary is left for the cutoff-and-allocation scenario{asked}; "
                "another seed or company, or tail_days 10 to 12 for the end boundary, leaves more"
            )
        claim(misdated(invoices[pool[0][1]], boundary=boundary))
        claim(under_applied(clean, pool[:1], mode))

    run = {"fx_then_allocation": fx_then_allocation, "duplicate_then_cutoff": duplicate_then_cutoff,
           "cutoff_and_allocation": cutoff_and_allocation}  # fmt: skip
    for name, parameters in scenarios:
        run[name](parameters)

    for _ in range(counts[DUPLICATE]):
        originals = [i for i in draw.shuffled(list(invoices.values())) if i["invoice_id"] not in used_invoices]
        if not originals:
            raise EpisodeError("no invoice is left to duplicate")
        claim(duplicate_of(originals[0]))
    for _ in range(counts[ALLOCATION]):
        claim(under_applied(clean))
    for _ in range(counts[FX]):
        claim(wrong_rate_error())
    for _ in range(counts[CUTOFF]):
        claim(next((misdated(invoice) for invoice in near_a_boundary()), None))
    # Sub-kinds come after every family above, so an inject without them draws exactly what it drew before.
    for key, mode in ((ALLOCATION_MISSING, "missing"), (ALLOCATION_PARTIAL, "partial")):
        for _ in range(counts[key]):
            claim(under_applied(clean, mode=mode))
    for key, kind in ((FX_DATE, "date"), (FX_RATE, "rate")):
        for _ in range(counts[key]):
            claim(wrong_rate_error(kind))
    return errors
