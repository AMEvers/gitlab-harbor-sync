#!/usr/bin/env python3
"""Compatibility wrapper for running directly from a source checkout."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from gitlab_harbor_sync.cli import main  # noqa: E402

raise SystemExit(main())
