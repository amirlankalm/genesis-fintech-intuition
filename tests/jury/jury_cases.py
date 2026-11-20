"""Block 2 matrix: D01-D20 built through the documented generator config (ADAPTER.md section 3).

Seeds are the jury's own (base 7_310_000 + 100*k); if the company cannot hold a request the generator refuses
with a reason and the next seed is tried (at most 25), which ADAPTER.md documents as normal behaviour.
"""

from __future__ import annotations

from typing import Any

import judge_adapter

SEED_BASE = 7_310_000

D_CASES: dict[str, dict[str, Any]] = {
    # five clean companies
    "D01": {"scenario": "clean_ordinary", "expect": [], "config": {"generator": {"ledger_rows": 330, "invoices": 30}}},
    "D02": {
        "scenario": "clean_split_payment",
        "expect": [],
        "config": {"generator": {"invoices": 70, "ledger_rows": 650, "foreign_currencies": ["USD", "EUR"]}},
    },
    "D03": {
        "scenario": "clean_refund",
        "expect": [],
        "config": {
            "generator": {
                "base_currency": "EUR",
                "foreign_currencies": ["USD", "GBP"],
                "timezone": "Africa/Lagos",
                "period": "2027-02",
            }
        },
    },
    "D04": {
        "scenario": "clean_repeated_amounts",
        "expect": [],
        "config": {
            "generator": {
                "base_currency": "JPY",
                "foreign_currencies": ["USD"],
                "timezone": "Asia/Tokyo",
                "period": "2026-Q2",
                "invoices": 60,
                "ledger_rows": 700,
            }
        },
    },
    "D05": {
        "scenario": "clean_fx_and_period_boundary",
        "expect": [],
        "config": {
            "generator": {
                "base_currency": "USD",
                "foreign_currencies": ["KWD", "KZT"],
                "timezone": "America/Bogota",
                "head_days": 12,
                "tail_days": 12,
            }
        },
    },
    # duplicates
    "D06": {
        "scenario": "duplicate",
        "expect": ["duplicate_invoice"],
        "config": {"generator": {}, "inject": {"duplicate_invoice": 1}},
    },
    "D07": {
        "scenario": "duplicate",
        "expect": ["duplicate_invoice"],
        "config": {
            "generator": {
                "base_currency": "GBP",
                "foreign_currencies": ["EUR"],
                "timezone": "UTC",
                "period": "2025-12",
            },
            "inject": {"duplicate_invoice": 1},
        },
    },
    "D08": {
        "scenario": "duplicate",
        "expect": ["duplicate_invoice"],
        "config": {
            "generator": {
                "base_currency": "KWD",
                "foreign_currencies": ["USD"],
                "timezone": "Asia/Dubai",
                "invoices": 90,
                "ledger_rows": 900,
            },
            "inject": {"duplicate_invoice": 1},
        },
    },
    # allocation
    "D09": {
        "scenario": "allocation_missing",
        "expect": ["payment_allocation"],
        "config": {"generator": {}, "inject": {"payment_allocation_missing": 1}},
    },
    "D10": {
        "scenario": "allocation_partial",
        "expect": ["payment_allocation"],
        "config": {
            "generator": {"base_currency": "USD", "foreign_currencies": ["KZT"], "timezone": "UTC"},
            "inject": {"payment_allocation_partial": 1},
        },
    },
    "D11": {
        "scenario": "allocation_any",
        "expect": ["payment_allocation"],
        "config": {
            "generator": {"timezone": "Asia/Kolkata", "base_currency": "EUR", "foreign_currencies": ["JPY"]},
            "inject": {"payment_allocation": 1},
        },
    },
    # fx
    "D12": {
        "scenario": "fx_date",
        "expect": ["fx_mismatch"],
        "config": {"generator": {"foreign_currencies": ["USD", "EUR"]}, "inject": {"fx_mismatch_date": 1}},
    },
    "D13": {
        "scenario": "fx_rate",
        "expect": ["fx_mismatch"],
        "config": {
            "generator": {"base_currency": "GBP", "foreign_currencies": ["JPY", "USD"], "timezone": "Asia/Tokyo"},
            "inject": {"fx_mismatch_rate": 1},
        },
    },
    # period
    "D14": {
        "scenario": "cutoff",
        "expect": ["cutoff"],
        "config": {
            "generator": {"timezone": "Asia/Kolkata", "base_currency": "USD", "foreign_currencies": ["EUR"]},
            "inject": {"cutoff": 1},
        },
    },
    "D15": {
        "scenario": "cutoff",
        "expect": ["cutoff"],
        "config": {
            "generator": {
                "timezone": "America/Bogota",
                "period": "2026-Q3",
                "tail_days": 12,
                "invoices": 50,
                "ledger_rows": 500,
            },
            "inject": {"cutoff": 1},
        },
    },
    # interaction 1
    "D16": {
        "scenario": "cutoff_and_allocation",
        "expect": ["cutoff", "payment_allocation"],
        "params": {"boundary": "end", "allocation": "partial", "receipt_currency": "foreign"},
        "config": {
            "generator": {"tail_days": 12},
            "inject": {
                "interactions": [
                    {
                        "name": "cutoff_and_allocation",
                        "boundary": "end",
                        "allocation": "partial",
                        "receipt_currency": "foreign",
                    }
                ]
            },
        },
    },
    "D17": {
        "scenario": "cutoff_and_allocation",
        "expect": ["cutoff", "payment_allocation"],
        "params": {"boundary": "start", "allocation": "missing", "receipt_currency": "same"},
        "config": {
            "generator": {"head_days": 12, "base_currency": "USD", "foreign_currencies": ["KZT"], "timezone": "UTC"},
            "inject": {
                "interactions": [
                    {
                        "name": "cutoff_and_allocation",
                        "boundary": "start",
                        "allocation": "missing",
                        "receipt_currency": "same",
                    }
                ]
            },
        },
    },
    "D18": {
        "scenario": "cutoff_and_allocation",
        "expect": ["cutoff", "payment_allocation"],
        "params": {"boundary": "end", "allocation": "missing", "receipt_currency": "foreign"},
        "config": {
            "generator": {
                "tail_days": 12,
                "base_currency": "EUR",
                "foreign_currencies": ["GBP"],
                "timezone": "Africa/Lagos",
            },
            "inject": {
                "interactions": [
                    {
                        "name": "cutoff_and_allocation",
                        "boundary": "end",
                        "allocation": "missing",
                        "receipt_currency": "foreign",
                    }
                ]
            },
        },
    },
    # interaction 2
    "D19": {
        "scenario": "duplicate_then_cutoff",
        "expect": ["cutoff", "duplicate_invoice"],
        "params": {"boundary": "start", "copy_offset": "same"},
        "config": {
            "generator": {"head_days": 10},
            "inject": {"interactions": [{"name": "duplicate_then_cutoff", "boundary": "start", "copy_offset": "same"}]},
        },
    },
    "D20": {
        "scenario": "duplicate_then_cutoff",
        "expect": ["cutoff", "duplicate_invoice"],
        "params": {"boundary": "end", "copy_offset": "other"},
        "config": {
            "generator": {
                "tail_days": 12,
                "base_currency": "USD",
                "foreign_currencies": ["JPY"],
                "timezone": "Asia/Tokyo",
            },
            "inject": {"interactions": [{"name": "duplicate_then_cutoff", "boundary": "end", "copy_offset": "other"}]},
        },
    },
}


def generate_with_seed_search(base: int, config: dict, out_dir: str, tries: int = 25) -> tuple[int, list[str]]:
    refusals = []
    for seed in range(base, base + tries):
        try:
            judge_adapter.generate_episode(seed, config, out_dir)
            return seed, refusals
        except judge_adapter.AdapterError as exc:  # documented refusal: "... left to ..."
            refusals.append(f"seed {seed}: {exc}")
    raise AssertionError(f"generator refused {tries} seeds for {config}: {refusals[-3:]}")
