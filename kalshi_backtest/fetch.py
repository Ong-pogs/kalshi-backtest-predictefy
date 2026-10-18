"""Pull hourly Kalshi candles through Predictefy and save them for offline backtests.

    python fetch.py              the last 12 months (needs the Builder plan)
    python fetch.py --all        everything the API has for these contracts
    python fetch.py --free       the last 7 days of the open October contracts (free plan)

One catalog read per event (1 credit) and one history read per contract (5 credits).
Everything is written under data/ so the backtest itself never touches the network.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import httpx
from predictefy import Predictefy
from predictefy.errors import PredictefyError

from . import config
from .data import by_month, coverage, label_counts, split_usable, to_replay_row

MAX_CANDLES = 5000


class CreditMeter(httpx.HTTPTransport):
    """Counts what each Predictefy call was charged, from the x-credits-charged header."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[dict[str, Any]] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        response = super().handle_request(request)
        charged = response.headers.get("x-credits-charged")
        self.calls.append(
            {
                "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "path": request.url.path,
                "query": {k: v for k, v in request.url.params.items()},
                "status": response.status_code,
                "credits": int(charged) if charged and charged.isdigit() else 0,
            }
        )
        return response


def iso(ms: Optional[int]) -> Optional[str]:
    return None if ms is None else datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat(timespec="minutes")


def parse_ms(text: Optional[str]) -> Optional[int]:
    if not text:
        return None
    return int(datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp() * 1000)


def plan_message(error: PredictefyError, mode: str) -> str:
    """What to tell someone whose plan cannot read this far back."""
    lines = [
        "",
        f"Predictefy answered {error.status} {error.code}: {error.message}",
        "",
        "The free plan reads 7 days of price history. Builder reads 12 months, Pro reads all of it.",
        f"Upgrade here: {config.UPGRADE_URL}",
    ]
    if mode != "free":
        lines.append("Or try the pipeline on the free plan first:  python fetch.py --free")
    return "\n".join(lines)


def read_candles(client: Predictefy, outcome_id: str, start: Optional[str], end: Optional[str]) -> tuple[list[dict], list[Any]]:
    """Every hourly candle in the window, following the 5,000-candle page limit."""
    candles: list[dict] = []
    provenance: list[Any] = []
    cursor = start
    while True:
        params: dict[str, Any] = {"outcomeId": outcome_id, "resolution": config.RESOLUTION, "limit": MAX_CANDLES}
        if cursor:
            params["start"] = cursor
        if end:
            params["end"] = end
        for attempt in range(4):
            try:
                body = client.kalshi.fetch_ohlcv(params)
                break
            except PredictefyError as error:
                # The history store answers a retryable 503 now and then; plan and input errors are final.
                if not error.retryable or attempt == 3:
                    raise
                time.sleep(5 * (attempt + 1))
        page = body.get("data") or []
        provenance.append((body.get("meta") or {}).get("provenance"))
        candles.extend(page)
        if len(page) < MAX_CANDLES:
            return candles, provenance
        cursor = datetime.fromtimestamp(page[-1]["timestamp"] / 1000 + 1, tz=timezone.utc).isoformat()


def read_settlements(tickers: list[str]) -> dict[str, dict[str, Any]]:
    """Kalshi's public record of how each contract settled. Recently settled markets sit
    on /markets, older ones on /historical/markets; both are read without a key."""
    found: dict[str, dict[str, Any]] = {}
    with httpx.Client(timeout=30) as http:
        for route in ("markets", "historical/markets"):
            missing = [t for t in tickers if t not in found]
            for at in range(0, len(missing), 20):
                url = f"{config.KALSHI_PUBLIC}/{route}"
                try:
                    response = http.get(url, params={"tickers": ",".join(missing[at : at + 20]), "limit": 100})
                    rows = response.json().get("markets") or [] if response.status_code == 200 else []
                except (httpx.HTTPError, ValueError):
                    rows = []
                for row in rows:
                    result = row.get("result") or None
                    found[row["ticker"]] = {
                        "result": result if result in ("yes", "no") else None,
                        "status": row.get("status"),
                        "expirationValue": row.get("expiration_value") or None,
                        "openTime": row.get("open_time"),
                        "closeTime": row.get("close_time"),
                        "settledAt": row.get("settlement_ts"),
                        "lastPrice": float(row["last_price_dollars"]) if row.get("last_price_dollars") else None,
                        "lifetimeVolume": float(row["volume_fp"]) if row.get("volume_fp") else None,
                        "source": f"{url}?tickers={row['ticker']}",
                    }
    return found


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--months", type=int, default=12, help="how many months back to read (default 12, the Builder window)")
    parser.add_argument("--all", action="store_true", help="read everything the API has (older than 12 months needs Pro)")
    parser.add_argument("--free", action="store_true", help="the last 7 days of the open October contracts")
    parser.add_argument("--out", type=Path, default=None, help="folder to write (default data/, or data-free/ with --free)")
    args = parser.parse_args(argv)

    now = datetime.now(timezone.utc)
    if args.free:
        mode, events = "free", (config.FREE_EVENT,)
        start: Optional[str] = (now - timedelta(days=7) + timedelta(hours=1)).isoformat(timespec="seconds")
    elif args.all:
        mode, events, start = "all", config.EVENTS, None
    else:
        mode, events = f"{args.months} months", config.EVENTS
        start = (now - timedelta(days=round(args.months * 365 / 12)) + timedelta(days=1)).isoformat(timespec="seconds")
    end = now.isoformat(timespec="seconds") if start else None
    out = args.out or (config.ROOT / "data-free" if args.free else config.DATA)
    (out / "raw").mkdir(parents=True, exist_ok=True)
    (out / "candles").mkdir(parents=True, exist_ok=True)

    meter = CreditMeter()
    client = Predictefy(api_key=config.api_key(), transport=meter, timeout=150.0)
    markets: list[dict[str, Any]] = []
    try:
        for event in events:
            page = client.kalshi.fetch_markets({"eventId": event, "status": "all", "limit": 50})
            rows = sorted(page, key=lambda m: m["marketId"])
            print(f"{event}: {len(rows)} contracts in Predictefy's catalog")
            for market in rows:
                yes = market.get("yes") or market["outcomes"][0]
                markets.append(
                    {
                        "ticker": market["marketId"],
                        "outcomeId": yes["outcomeId"],
                        "event": event,
                        "title": market.get("title"),
                        "strike": float(market["marketId"].rsplit("-T", 1)[1]) if "-T" in market["marketId"] else None,
                        "status": market.get("status"),
                        "resolutionDate": market.get("resolutionDate"),
                        "lastPrice": yes.get("price"),
                        "url": market.get("url"),
                    }
                )
        if not markets:
            print("No contracts found for these events.")
            return 1

        settlements = read_settlements([m["ticker"] for m in markets])
        window_start = parse_ms(start)
        window_end = int(now.timestamp() * 1000)
        for market in markets:
            candles, provenance = read_candles(client, market["outcomeId"], start, end)
            (out / "raw" / f"{market['ticker']}.json").write_text(
                json.dumps({"fetchedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"), "request": {"outcomeId": market["outcomeId"], "resolution": config.RESOLUTION, "start": start, "end": end}, "provenance": provenance, "data": candles}),
                encoding="utf-8",
            )
            usable, dropped = split_usable(candles)
            with (out / "candles" / f"{market['ticker']}.ndjson").open("w", encoding="utf-8", newline="\n") as handle:
                for candle in usable:
                    handle.write(json.dumps(to_replay_row(candle, config.RESOLUTION)) + "\n")
            settled = settlements.get(market["ticker"], {})
            market.update({k: settled.get(k) for k in ("result", "expirationValue", "openTime", "closeTime", "settledAt", "lifetimeVolume")})
            market["settlementSource"] = settled.get("source")
            stamps = [c["timestamp"] for c in usable]
            listed = parse_ms(market.get("openTime"))
            closes = parse_ms(market.get("closeTime")) or parse_ms(market.get("resolutionDate")) or window_end
            span_start = max(x for x in (listed, window_start, min(stamps) if not listed and stamps else None, 0) if x is not None)
            market["candles"] = {
                "returned": len(candles),
                "usable": len(usable),
                "dropped": dict(dropped),
                "labels": label_counts(candles),
                "usableLabels": label_counts(usable),
                "provenance": sorted({str(p) for p in provenance}),
                "coverage": coverage(stamps, span_start, min(closes, window_end)),
                "byMonth": by_month(stamps),
                "volume": round(sum(c["volume"] for c in usable), 2),
            }
            first, last = (iso(stamps[0]), iso(stamps[-1])) if stamps else (None, None)
            print(f"  {market['ticker']:<20} {len(candles):>5} candles  {len(usable):>5} usable  {first} to {last}  result {market.get('result') or 'not settled'}")
    except PredictefyError as error:
        if error.status in (402, 403) or error.code in ("PLAN_REQUIRED", "INSUFFICIENT_CREDITS"):
            print(plan_message(error, mode))
            (out / "plan-required.json").write_text(json.dumps({"at": now.isoformat(timespec="seconds"), "status": error.status, "code": error.code, "message": error.message, "upgradeUrl": config.UPGRADE_URL}, indent=1), encoding="utf-8")
            return 2
        raise
    finally:
        client.close()

    catalog_reads = sum(1 for c in meter.calls if c["path"].endswith("fetchMarkets") and c["status"] == 200)
    history_reads = sum(1 for c in meter.calls if c["path"].endswith("fetchOHLCV") and c["status"] == 200)
    manifest = {
        "fetchedAt": now.isoformat(timespec="seconds"),
        "mode": mode,
        "window": {"start": start, "end": end},
        "venue": config.VENUE,
        "resolution": config.RESOLUTION,
        "events": list(events),
        "sdk": "predictefy 1.0.0b9 (Python)",
        "credits": {
            "charged": sum(c["credits"] for c in meter.calls),
            "catalogReads": catalog_reads,
            "historyReads": history_reads,
            "byWeight": catalog_reads * config.CREDITS_PER_CATALOG_READ + history_reads * config.CREDITS_PER_HISTORY_READ,
        },
        "calls": meter.calls,
        "markets": markets,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    plan_note = out / "plan-required.json"
    if plan_note.exists():
        plan_note.unlink()
    total = sum(m["candles"]["usable"] for m in markets)
    print(f"\n{len(markets)} contracts, {total:,} usable hourly candles, {manifest['credits']['charged']} credits. Saved under {out.name}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
