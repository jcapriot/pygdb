"""
Shared pytest fixtures.

`samples/` holds real, publicly-sourced .gdb/.grd survey files used to
develop and validate this reader -- see docs/provenance/notes.md for
exact provenance. They are intentionally **not** committed to this
repository (redistribution rights are unclear for most of them), so any
test that needs them must be able to run -- by skipping cleanly, not
failing -- in a fresh clone that doesn't have that directory populated.
"""

from __future__ import annotations

import glob
import os

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLES_DIR = os.path.join(REPO_ROOT, "samples")


def _find_gdb_files():
    return sorted(glob.glob(os.path.join(SAMPLES_DIR, "**", "*.gdb"), recursive=True))


@pytest.fixture(autouse=True)
def _fresh_unseen_feature_notices(monkeypatch):
    """Unseen-feature notices are reported once per file per process;
    start every test with none reported, and with notices on."""
    from pygdb import unseen
    unseen._reported.clear()
    monkeypatch.delenv("PYGDB_UNSEEN_FEATURE_NOTICES", raising=False)


@pytest.fixture(scope="session")
def samples_dir():
    if not os.path.isdir(SAMPLES_DIR) or not _find_gdb_files():
        pytest.skip(
            "samples/ not present locally (real sample .gdb files are not "
            "committed to this repository -- see docs/provenance/notes.md "
            "for how to re-download them if you want to run this test)"
        )
    return SAMPLES_DIR


@pytest.fixture(scope="session")
def all_gdb_sample_paths(samples_dir):
    return _find_gdb_files()
