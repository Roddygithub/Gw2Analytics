"""Durable repository safety boundaries.

These assertions replace the BMAD/Codex/Herdr framework tests that were removed
with the obsolete agent-workflow infrastructure (``test_bmad_framework.py``,
``test_agentic_infrastructure.py``). Only the product-relevant rules encoded by
those tests are kept:

* the private WvW combat corpus must never be tracked by Git;
* privileged host-mutating executors/installers must not exist in the repo;
* the obsolete agent-workflow frameworks must not be reintroduced.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

# Privileged or framework artifacts intentionally removed by the refoundation.
REMOVED_ARTIFACTS = (
    # obsolete agent-workflow frameworks
    "_bmad",
    "_bmad-output",
    ".codex",
    ".agents/gw2-pipeline.ts",
    "docs/agentic",
    "ops/gw2a",
    # privileged host-mutating installers/executors
    "tools/setup-host.sh",
    "tools/install-gw2a-lifecycle.sh",
    "tools/install-private-corpus-executor.sh",
    "tools/install-gw2analytics-admin.sh",
)


def test_gitignore_protects_local_wvw_corpus() -> None:
    """The private WvW corpus must never be committable."""
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "/WvW/" in gitignore


@pytest.mark.parametrize("relpath", REMOVED_ARTIFACTS)
def test_removed_infrastructure_is_not_reintroduced(relpath: str) -> None:
    assert not (ROOT / relpath).exists(), (
        f"{relpath!r} is privileged or obsolete infrastructure and must not "
        "be reintroduced into the repository."
    )
