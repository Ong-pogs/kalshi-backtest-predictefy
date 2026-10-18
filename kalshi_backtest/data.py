"""Candle checks that run before any backtest: labels, usable rows, and gaps.

Everything here is a pure function over the candles Predictefy returned, so the tests
need no network.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Iterable, Mapping, Optional

HOUR_MS = 3_600_000
LABELS = ("source", "sourceType", "quality", "isTrueCandle")


def why_unusable(candle: Mapping[str, Any]) -> Optional[str]:
    """None when a candle can be traded against, otherwise the reason it is dropped.

    The first two rules follow Predictefy's cookbook: never mix in buckets flagged
    `suspect` or rebuilt from the order book. The other two came from the data itself:
    an hour with no trades can come back as a candle priced at zero and still be
    labelled `ok`, and a price outside 0-1 is not a prediction-market price.
    """
    if candle.get("quality") == "suspect":
        return "suspect"
    if candle.get("sourceType") == "book-derived":
        return "book-derived"
    volume = candle.get("volume")
    if volume is None or volume <= 0:
        return "no-trades"
    prices = [candle.get(k) for k in ("open", "high", "low", "close")]
    if any(p is None or not 0 < p < 1 for p in prices):
        return "bad-price"
    return None


def split_usable(candles: Iterable[Mapping[str, Any]]) -> tuple[list[dict], Counter]:
    """The candles that pass `why_unusable`, oldest first, and a count of each drop reason."""
    kept: list[dict] = []
    dropped: Counter = Counter()
    for candle in sorted(candles, key=lambda c: c["timestamp"]):
        reason = why_unusable(candle)
        if reason:
            dropped[reason] += 1
        else:
            kept.append(dict(candle))
    return kept, dropped


def label_counts(candles: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, int]]:
    """How many candles carry each value of each provenance label."""
    counts: dict[str, Counter] = {label: Counter() for label in LABELS}
    for candle in candles:
        for label in LABELS:
            counts[label][str(candle.get(label)).lower() if label == "isTrueCandle" else str(candle.get(label))] += 1
    return {label: dict(counter) for label, counter in counts.items()}


def to_replay_row(candle: Mapping[str, Any], resolution: str) -> dict[str, Any]:
    """One fetchOHLCV candle in the row shape `predictefy.backtest` reads from disk."""
    return {
        "k": "candle",
        "ts": int(candle["timestamp"]),
        "resolution": resolution,
        "open": candle["open"],
        "high": candle["high"],
        "low": candle["low"],
        "close": candle["close"],
        "volume": candle.get("volume"),
        "source": candle["source"],
        "sourceType": candle["sourceType"],
        "quality": candle["quality"],
        "isTrueCandle": candle["isTrueCandle"],
    }


def coverage(timestamps: Iterable[int], window_start: int, window_end: int, step_ms: int = HOUR_MS) -> dict[str, Any]:
    """How much of a window has a candle, and where the longest silence is.

    A missing hour is an hour in which nothing traded (or nothing was recorded). A
    backtest cannot fill an order there, so the share of covered hours is a ceiling on
    how often the strategy could have acted.
    """
    stamps = sorted(t for t in set(timestamps) if window_start <= t < window_end)
    hours = max(0, (window_end - window_start) // step_ms)
    longest, longest_from = 0, None
    previous = window_start - step_ms
    for stamp in stamps + [window_end]:
        silent = (stamp - previous) // step_ms - 1
        if silent > longest:
            longest, longest_from = silent, previous + step_ms
        previous = stamp
    return {
        "hours": int(hours),
        "withCandle": len(stamps),
        "share": (len(stamps) / hours) if hours else None,
        "first": stamps[0] if stamps else None,
        "last": stamps[-1] if stamps else None,
        "longestGapHours": int(longest),
        "longestGapFrom": longest_from,
    }


def by_month(timestamps: Iterable[int]) -> dict[str, int]:
    """Candle counts per calendar month (UTC), for the coverage strip on the results page."""
    from datetime import datetime, timezone

    counts: Counter = Counter()
    for stamp in timestamps:
        counts[datetime.fromtimestamp(stamp / 1000, tz=timezone.utc).strftime("%Y-%m")] += 1
    return dict(sorted(counts.items()))
