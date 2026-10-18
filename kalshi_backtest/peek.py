"""Print one raw candle exactly as Predictefy returns it, so you can see what the backtest reads.

    python peek.py            the last traded hour of a settled Fed contract (needs the Builder plan)
    python peek.py --open     the last 7 days of a contract that is still open (free plan)

One history read, 5 credits.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from typing import Optional

from predictefy import Predictefy
from predictefy.errors import PredictefyError

from . import config
from .data import label_counts, split_usable
from .fetch import CreditMeter, plan_message

SETTLED = "KXFED-26SEP-T3.75"
OPEN = "KXFED-26OCT-T4.00"


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--open", action="store_true", help="read the last 7 days of an open contract")
    parser.add_argument("--contract", default=None, help="a Kalshi ticker to read")
    args = parser.parse_args(argv)

    ticker = args.contract or (OPEN if args.open else SETTLED)
    params = {"outcomeId": ticker, "resolution": config.RESOLUTION, "limit": 5000}
    if args.open:
        now = datetime.now(timezone.utc)
        params["start"] = (now - timedelta(days=7) + timedelta(hours=1)).isoformat(timespec="seconds")
        params["end"] = now.isoformat(timespec="seconds")
    meter = CreditMeter()
    client = Predictefy(api_key=config.api_key(), transport=meter, timeout=150.0)
    try:
        body = client.kalshi.fetch_ohlcv(params)
    except PredictefyError as error:
        if error.status in (402, 403):
            print(plan_message(error, "free" if args.open else "12 months"))
            return 2
        raise
    finally:
        client.close()

    candles = body.get("data") or []
    usable, dropped = split_usable(candles)
    print(f"GET /api/kalshi/fetchOHLCV  outcomeId={ticker}  resolution={config.RESOLUTION}")
    print(f"{len(candles):,} candles, {sum(c['credits'] for c in meter.calls)} credits")
    if not candles:
        print("No candles in that window.")
        return 0
    counts = label_counts(candles)
    for label in ("source", "sourceType", "quality", "isTrueCandle"):
        print(f"  {label:<13}" + ", ".join(f"{value} x {count:,}" for value, count in counts[label].items()))
    if dropped:
        print(f"with trades: {len(usable):,}   without: {sum(dropped.values()):,}")
    shown = usable[-1] if usable else candles[-1]
    when = datetime.fromtimestamp(shown["timestamp"] / 1000, tz=timezone.utc).strftime("%d %b %Y, %H:%M UTC")
    print(f"\nThe last hour with a trade in it ({when}):" if usable else "\nThe newest candle:")
    print(json.dumps(shown, indent=2))
    if dropped and not args.contract:
        empty = next(c for c in reversed(candles) if not c.get("volume"))
        print("\nAn hour with no trade in it:")
        print(json.dumps(empty))
    return 0


if __name__ == "__main__":
    sys.exit(main())
