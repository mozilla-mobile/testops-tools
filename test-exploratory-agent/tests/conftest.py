"""
Shared pytest setup.

Adds the project root to sys.path so tests can import `agent.*` and `config.*`
without needing an editable install.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
