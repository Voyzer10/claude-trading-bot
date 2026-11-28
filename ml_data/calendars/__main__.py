"""CLI entrypoint for `python -m ml_data.calendars`."""
from __future__ import annotations

from .audit import main

if __name__ == "__main__":
    raise SystemExit(main())
