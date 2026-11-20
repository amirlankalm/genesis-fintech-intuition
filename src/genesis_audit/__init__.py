"""Synthetic financial-audit RL environment: an engine, four error families, a seeded generator and a harness.

Everything here is synthetic. The parameters that come from the case specification
(step budget, caps, reward formula) conform to the official evaluation envelope.
"""

__version__ = "0.2.0"
ENV_VERSION = f"genesis-audit-env/{__version__}"
SCHEMA_VERSION = "genesis-fintech-draft-2026-11-12/teaching-1"
