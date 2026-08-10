#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

"""Release test planner for Fenix - entry point.

Maps a git range to the Fenix features it touches, checks what UI automation
exists for those features, scores the risk with FMEA, and produces both a
recommended test run and the manual-testing gap.

    ./plan.py analyze --repo /path/to/firefox --range v1..v2 --budget 240 --open
    ./plan.py serve --repo /path/to/firefox --live --open

Stdlib only - no install step, no API key. See README.md.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from testplanner.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
