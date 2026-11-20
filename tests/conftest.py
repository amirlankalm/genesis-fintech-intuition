from __future__ import annotations

import pytest

from genesis_audit import paths
from genesis_audit.env import AuditEnv, DirectorySource


@pytest.fixture
def source() -> DirectorySource:
    return DirectorySource(paths.PUBLIC_ROOT, paths.PRIVATE_ROOT)


@pytest.fixture
def env(source: DirectorySource) -> AuditEnv:
    return AuditEnv(source)
