"""Settings shared by the fetcher, the backtest and the results page."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RESULTS = ROOT / "results"

VENUE = "kalshi"
RESOLUTION = "1h"

#: The settled Kalshi events the backtest runs on: the Fed's rate after its July and
#: September 2026 meetings. Each event is a ladder of "above X%" contracts.
EVENTS = ("KXFED-26JUL", "KXFED-26SEP")
#: A still-open event, used by --free: the free plan reads only the last 7 days.
FREE_EVENT = "KXFED-26OCT"

#: Money and sizing. One account per contract keeps every contract's result separate.
CASH_PER_CONTRACT = 100.0
LOT = 100.0

CREDITS_PER_CATALOG_READ = 1
CREDITS_PER_HISTORY_READ = 5

PLANS = (
    {"plan": "Free", "price": "$0", "credits": 25_000, "history": "7 days"},
    {"plan": "Builder", "price": "$48.88 a month", "credits": 500_000, "history": "12 months"},
    {"plan": "Pro", "price": "$149 a month", "credits": 5_000_000, "history": "unlimited"},
)
UPGRADE_URL = (
    "https://predictefy.com/en/api?utm_source=youtube&utm_medium=video"
    "&utm_campaign=kalshi-backtest&utm_content=upgrade"
)
KEYS_URL = "https://portal.predictefy.com/keys"
PLACEHOLDER_KEY = "pk_live_your_key_here"

#: Kalshi's own public market record carries the settlement result. No key is needed.
KALSHI_PUBLIC = "https://api.elections.kalshi.com/trade-api/v2"


def load_env(path: Path | None = None) -> None:
    """Read KEY=value lines from .env into the process environment (existing values win)."""
    file = path or ROOT / ".env"
    if not file.exists():
        return
    for line in file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        os.environ.setdefault(name.strip(), value.strip().strip('"').strip("'"))


def api_key() -> str:
    """The Predictefy key, or a clear exit when it is missing or still the placeholder."""
    load_env()
    key = os.environ.get("PREDICTEFY_API_KEY", "").strip()
    if not key or key == PLACEHOLDER_KEY:
        raise SystemExit(
            "PREDICTEFY_API_KEY is not set.\n"
            f"Create a key at {KEYS_URL}, copy .env.example to .env and paste the key into it."
        )
    return key
