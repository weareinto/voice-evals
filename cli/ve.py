#!/usr/bin/env python3
"""Run the voice-evals CLI straight from the plugin folder (no install needed)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from voice_evals.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
