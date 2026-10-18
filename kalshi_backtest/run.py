"""Run the strategies over the saved candles with predictefy.backtest, then settle.

    python backtest.py            both strategies, every contract under data/
    python backtest.py --data data-free

The engine replays one contract at a time, one candle at a time. It stops at the last
candle, so anything still held is settled here at the real result: $1 a contract if
the market resolved Yes, $0 if it resolved No. Reads no network and spends no credits.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from predictefy.backtest import Backtest, NdjsonFileFeed

from . import config
from .data import HOUR_MS
from .strategies import STRATEGIES


def parse_ms(text: Optional[str]) -> Optional[int]:
    if not text:
        return None
    return int(datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp() * 1000)


def settle(position: float, cash: float, avg_cost: float, result: Optional[str], mark: Optional[float]) -> dict[str, Any]:
    """What an account is worth once the market has paid out.

    A settled contract pays $1 (Yes) or $0 (No) and Kalshi charges no fee for that. A
    contract with no published result yet stays at its last traded price, and says so.
    """
    if result in ("yes", "no"):
        value = 1.0 if result == "yes" else 0.0
        basis = "settled"
    else:
        value = mark if mark is not None else avg_cost
        basis = "last-price"
    payout = position * value
    return {
        "basis": basis,
        "valuePerContract": value,
        "held": position,
        "payout": payout,
        "pnlOnHeld": (value - avg_cost) * position if position else 0.0,
        "finalCash": cash + payout,
    }


def run_contract(market: dict[str, Any], candles: Path, strategy_name: str) -> dict[str, Any]:
    """One contract, one strategy: the engine's run plus the settlement step."""
    strategy = STRATEGIES[strategy_name](lot=config.LOT)
    result = Backtest(NdjsonFileFeed(candles), strategy, venue=config.VENUE, initial_cash=config.CASH_PER_CONTRACT).run()
    report = result.report()
    portfolio = result.portfolio
    settled = settle(portfolio.position, portfolio.cash, portfolio.avg_cost, market.get("result"), portfolio.mark)
    orders = [
        {
            "id": order.order_id,
            "side": order.side,
            "price": order.price,
            "size": order.size,
            "filled": round(order.filled, 6),
            "status": order.status,
            "placedAt": order.placed_ts,
            "rejectReason": order.reject_reason,
        }
        for order in result.orders
    ]
    fills = [
        {
            "ticker": market["ticker"],
            "ts": fill.ts,
            "orderId": fill.order_id,
            "side": fill.side,
            "price": fill.price,
            "size": round(fill.size, 6),
            "fee": round(fill.fee, 4),
            "feeModel": fill.fee_model,
            "rule": fill.rule,
            "liquidity": fill.liquidity,
        }
        for fill in result.fills
    ]
    trades = [
        {"ticker": market["ticker"], "ts": t.ts, "size": round(t.size, 6), "entry": round(t.entry_price, 4), "exit": t.exit_price, "fee": round(t.fee, 4), "pnl": round(t.pnl, 4), "how": "sold"}
        for t in portfolio.closed_trades
    ]
    if settled["held"] > 0:
        closes = parse_ms(market.get("closeTime")) or (result.end_ts or 0)
        trades.append({"ticker": market["ticker"], "ts": closes, "size": round(settled["held"], 6), "entry": round(portfolio.avg_cost, 4), "exit": settled["valuePerContract"], "fee": 0.0, "pnl": round(settled["pnlOnHeld"], 4), "how": settled["basis"]})
    buys = [f for f in fills if f["side"] == "buy"]
    sells = [f for f in fills if f["side"] == "sell"]
    bought, sold = sum(f["size"] for f in buys), sum(f["size"] for f in sells)
    return {
        "ticker": market["ticker"],
        "event": market["event"],
        "strike": market.get("strike"),
        "result": market.get("result"),
        "candles": report["counts_by_kind"].get("candle", 0),
        "bought": round(bought, 4),
        "avgBuy": round(sum(f["size"] * f["price"] for f in buys) / bought, 4) if bought else None,
        "sold": round(sold, 4),
        "avgSell": round(sum(f["size"] * f["price"] for f in sells) / sold, 4) if sold else None,
        "notional": round(sum(f["size"] * f["price"] for f in fills), 4),
        "orders": orders,
        "fills": fills,
        "trades": trades,
        "feesPaid": round(report["fees_paid"], 4),
        "markedEquity": round(report["final_equity"], 4),
        "finalCash": round(settled["finalCash"], 4),
        "pnl": round(settled["finalCash"] - config.CASH_PER_CONTRACT, 4),
        "settlement": settled,
        "engine": {k: report[k] for k in ("degraded_bars", "no_liquidity_bars", "stale_skips", "no_book_events", "replayed_rows", "discarded_rows", "rejected_orders")},
        "assumptions": report["assumptions"],
        "curve": [(point.ts, round(point.equity, 4)) for point in result.equity_curve],
        "settleAt": parse_ms(market.get("closeTime")),
    }


def combine_curves(runs: list[dict[str, Any]], start_cash: float) -> list[list[float]]:
    """Total equity across every account over time: each account keeps its last value
    until its next candle, and steps to its settled cash when its market closes."""
    events: list[tuple[int, int, float]] = []
    for index, run in enumerate(runs):
        for ts, equity in run["curve"]:
            events.append((ts, index, equity))
        last = run["curve"][-1][0] if run["curve"] else 0
        events.append((max(run["settleAt"] or last, last + 1), index, run["finalCash"]))
    events.sort()
    latest = [start_cash] * len(runs)
    total = start_cash * len(runs)
    out: list[list[float]] = []
    for ts, index, equity in events:
        total += equity - latest[index]
        latest[index] = equity
        if out and out[-1][0] == ts:
            out[-1][1] = round(total, 4)
        else:
            out.append([ts, round(total, 4)])
    return out


def summarise(name: str, runs: list[dict[str, Any]]) -> dict[str, Any]:
    cls = STRATEGIES[name]
    start = config.CASH_PER_CONTRACT * len(runs)
    orders = [o for r in runs for o in r["orders"]]
    fills = sorted((f for r in runs for f in r["fills"]), key=lambda f: (f["ts"], f["ticker"]))
    trades = sorted((t for r in runs for t in r["trades"]), key=lambda t: (t["ts"], t["ticker"]))
    final = sum(r["finalCash"] for r in runs)
    curve = combine_curves(runs, config.CASH_PER_CONTRACT)
    peak, drawdown = start, 0.0
    for _, equity in curve:
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    asked = sum(o["size"] for o in orders if o["side"] == "buy")
    bought = sum(f["size"] for f in fills if f["side"] == "buy")
    winners = [t for t in trades if t["pnl"] > 0]
    notes: list[str] = []
    for run in runs:
        for note in run["assumptions"]:
            # Per-run counts differ between contracts; keep the wording, drop the repeats.
            if not note[0].isdigit() and note not in notes:
                notes.append(note)
    return {
        "name": name,
        "label": cls.label,
        "rule": cls.rule,
        "startCash": start,
        "finalCash": round(final, 2),
        "pnl": round(final - start, 2),
        "returnPct": round((final / start - 1) * 100, 2),
        "feesPaid": round(sum(r["feesPaid"] for r in runs), 2),
        "pnlBeforeFees": round(final - start + sum(r["feesPaid"] for r in runs), 2),
        "maxDrawdown": round(drawdown, 2),
        "tradedNotional": round(sum(r["notional"] for r in runs), 2),
        "contractsUp": sum(1 for r in runs if r["pnl"] > 0.005),
        "contractsDown": sum(1 for r in runs if r["pnl"] < -0.005),
        "contractsFlat": sum(1 for r in runs if abs(r["pnl"]) <= 0.005),
        "sumUp": round(sum(r["pnl"] for r in runs if r["pnl"] > 0), 2),
        "sumDown": round(sum(r["pnl"] for r in runs if r["pnl"] < 0), 2),
        "orders": {
            "placed": len(orders),
            "filledInFull": sum(1 for o in orders if o["filled"] >= o["size"] - 1e-6),
            "filledInPart": sum(1 for o in orders if 0 < o["filled"] < o["size"] - 1e-6),
            "neverFilled": sum(1 for o in orders if o["filled"] == 0 and o["status"] != "rejected"),
            "rejected": sum(1 for o in orders if o["status"] == "rejected"),
            "contractsAskedToBuy": round(asked, 2),
            "contractsBought": round(bought, 2),
        },
        "fills": len(fills),
        "contractsTraded": sum(1 for r in runs if r["fills"]),
        "trades": {"count": len(trades), "winners": len(winners), "sold": sum(1 for t in trades if t["how"] == "sold"), "settled": sum(1 for t in trades if t["how"] != "sold")},
        "engine": {key: sum(r["engine"][key] for r in runs) for key in runs[0]["engine"]} if runs else {},
        "assumptions": notes,
        "curve": curve,
        "fillRows": fills,
        "tradeRows": trades,
        "contracts": [{k: r[k] for k in ("ticker", "event", "strike", "result", "candles", "bought", "avgBuy", "sold", "avgSell", "feesPaid", "markedEquity", "finalCash", "pnl", "settlement", "orders")} | {"fills": len(r["fills"])} for r in runs],
    }


def live_check(data: Path) -> Optional[dict[str, Any]]:
    """What the same request returned for contracts that are still open, when
    `fetch.py --free` has been run: the labels there are not the labels of settled history."""
    folder = data.parent / "data-free"
    manifest_file = folder / "manifest.json"
    if data.name == "data-free" or not manifest_file.exists():
        return None
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    labels: dict[str, dict[str, int]] = {}
    usable_labels: dict[str, dict[str, int]] = {}
    dropped: dict[str, int] = {}
    zero = real = None
    zero_true = 0
    for market in manifest["markets"]:
        for target, key in ((labels, "labels"), (usable_labels, "usableLabels")):
            for label, counts in market["candles"][key].items():
                for value, count in counts.items():
                    target.setdefault(label, {})[value] = target.get(label, {}).get(value, 0) + count
        for reason, count in market["candles"]["dropped"].items():
            dropped[reason] = dropped.get(reason, 0) + count
        raw_file = folder / "raw" / f"{market['ticker']}.json"
        if not raw_file.exists():
            continue
        for candle in json.loads(raw_file.read_text(encoding="utf-8"))["data"]:
            empty = candle.get("close") == 0 and not candle.get("volume")
            if empty and candle.get("isTrueCandle"):
                zero_true += 1
                zero = zero or candle
            if real is None and candle.get("volume"):
                real = candle
    return {
        "fetchedAt": manifest["fetchedAt"],
        "window": manifest["window"],
        "events": manifest["events"],
        "contracts": len(manifest["markets"]),
        "returned": sum(m["candles"]["returned"] for m in manifest["markets"]),
        "usable": sum(m["candles"]["usable"] for m in manifest["markets"]),
        "dropped": dropped,
        "zeroPricedLabelledTrue": zero_true,
        "labels": labels,
        "usableLabels": usable_labels,
        "sampleZero": zero,
        "sampleReal": real,
        "credits": manifest["credits"]["charged"],
    }


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data", type=Path, default=config.DATA, help="folder written by fetch.py (default data/)")
    parser.add_argument("--out", type=Path, default=config.RESULTS, help="folder for results.json and the fills CSVs")
    args = parser.parse_args(argv)

    manifest_file = args.data / "manifest.json"
    if not manifest_file.exists():
        print(f"No candles under {args.data.name}/. Run  python fetch.py  first.")
        return 1
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    listed = manifest["markets"]
    markets = [m for m in listed if m["candles"]["usable"] > 0]
    args.out.mkdir(parents=True, exist_ok=True)

    strategies = []
    for name in STRATEGIES:
        runs = [run_contract(market, args.data / "candles" / f"{market['ticker']}.ndjson", name) for market in markets]
        summary = summarise(name, runs)
        strategies.append(summary)
        with (args.out / f"fills-{name}.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["time_utc", "contract", "side", "price", "contracts", "fee", "fee_model", "fill_rule"])
            for fill in summary["fillRows"]:
                writer.writerow([datetime.fromtimestamp(fill["ts"] / 1000, tz=timezone.utc).isoformat(timespec="minutes"), fill["ticker"], fill["side"], fill["price"], fill["size"], fill["fee"], fill["feeModel"], fill["rule"]])
        o = summary["orders"]
        print(f"{summary['label']:<20} ${summary['startCash']:,.0f} -> ${summary['finalCash']:,.2f}  ({summary['returnPct']:+.2f}%)  fees ${summary['feesPaid']:.2f}  "
              f"orders {o['placed']} (full {o['filledInFull']}, part {o['filledInPart']}, none {o['neverFilled']})  fills {summary['fills']}")

    fetched = datetime.fromisoformat(manifest["fetchedAt"])
    builder_cutoff = int((fetched - timedelta(days=365)).timestamp() * 1000)
    free_cutoff = int((fetched - timedelta(days=7)).timestamp() * 1000)
    series, stamps, labels, dropped, by_month = {}, [], {}, {}, {}
    for market in listed:
        rows = [json.loads(line) for line in (args.data / "candles" / f"{market['ticker']}.ndjson").read_text(encoding="utf-8").splitlines() if line.strip()]
        series[market["ticker"]] = [[row["ts"], row["close"], row["volume"]] for row in rows]
        stamps.extend(row["ts"] for row in rows)
        for label, counts in market["candles"]["labels"].items():
            for value, count in counts.items():
                labels.setdefault(label, {})[value] = labels.get(label, {}).get(value, 0) + count
        for reason, count in market["candles"]["dropped"].items():
            dropped[reason] = dropped.get(reason, 0) + count
        for month, count in market["candles"]["byMonth"].items():
            by_month[month] = by_month.get(month, 0) + count
    hours = sum(m["candles"]["coverage"]["hours"] for m in listed)
    sample = next((json.loads(line) for m in markets for line in (args.data / "candles" / f"{m['ticker']}.ndjson").read_text(encoding="utf-8").splitlines()[:1]), None)
    results = {
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "engine": "predictefy.backtest (predictefy 1.0.0b9), Fill Model v1",
        "venue": config.VENUE,
        "resolution": manifest["resolution"],
        "cashPerContract": config.CASH_PER_CONTRACT,
        "lot": config.LOT,
        "data": {
            "fetchedAt": manifest["fetchedAt"],
            "mode": manifest["mode"],
            "window": manifest["window"],
            "events": manifest["events"],
            "contracts": len(listed),
            "contractsWithCandles": len(markets),
            "candlesReturned": sum(m["candles"]["returned"] for m in listed),
            "sampleCandle": sample,
            "volume": round(sum(m["candles"]["volume"] for m in listed), 2),
            "lifetimeVolume": round(sum(m.get("lifetimeVolume") or 0 for m in listed), 2),
            "candlesUsable": len(stamps),
            "dropped": dropped,
            "labels": labels,
            "firstCandle": min(stamps) if stamps else None,
            "lastCandle": max(stamps) if stamps else None,
            "spanDays": round((max(stamps) + HOUR_MS - min(stamps)) / 86_400_000, 1) if stamps else 0,
            "contractHours": hours,
            "shareOfHoursWithCandle": round(len(stamps) / hours, 4) if hours else None,
            "byMonth": dict(sorted(by_month.items())),
            "olderThanBuilderWindow": sum(1 for s in stamps if s < builder_cutoff),
            "insideFreeWindow": sum(1 for s in stamps if s >= free_cutoff),
            "builderCutoff": builder_cutoff,
            "credits": manifest["credits"],
        },
        "plans": list(config.PLANS),
        "upgradeUrl": config.UPGRADE_URL,
        "markets": [
            {k: m.get(k) for k in ("ticker", "event", "title", "strike", "status", "result", "expirationValue", "openTime", "closeTime", "lifetimeVolume", "lastPrice", "url", "settlementSource")}
            | {"candles": m["candles"], "series": series[m["ticker"]]}
            for m in listed
        ],
        "liveCheck": live_check(args.data),
        "strategies": strategies,
    }
    (args.out / "results.json").write_text(json.dumps(results), encoding="utf-8")
    print(f"\nSaved {args.out.name}/results.json. Open the results page with  python serve.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
