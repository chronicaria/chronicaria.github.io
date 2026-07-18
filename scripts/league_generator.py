#!/usr/bin/env python3
"""
Generate a simple static HTML basketball league site from a Basketball GM-style JSON export.

Usage:
    python3 basketball_site_generator_v3.py 2029preseason.json --out docs

The generated site is static HTML/CSS/JS. Re-run this script whenever the JSON changes.
"""

from __future__ import annotations

from smp.core import *  # noqa: F401,F403
from smp.finance import *  # noqa: F401,F403
from smp.simmodel import *  # noqa: F401,F403
from smp.charts import *  # noqa: F401,F403
from smp.pages.home import *  # noqa: F401,F403
from smp.pages.team import *  # noqa: F401,F403
from smp.pages.player import *  # noqa: F401,F403
from smp.pages.game import *  # noqa: F401,F403
from smp.pages.league import *  # noqa: F401,F403
from smp.pages.compare import *  # noqa: F401,F403
from smp.pages.trade import *  # noqa: F401,F403
from smp.build import *  # noqa: F401,F403

if __name__ == "__main__":
    main()
