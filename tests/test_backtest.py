import json
import tempfile
import unittest
from pathlib import Path

from predictefy.backtest import Backtest, fee_for_fill, parse_event

from kalshi_backtest.data import HOUR_MS, to_replay_row
from kalshi_backtest.run import combine_curves, run_contract, settle
from kalshi_backtest.strategies import BackTheFavourite, BuyTheDip


def row(i, close, volume=4000):
    return to_replay_row({"timestamp": i * HOUR_MS, "open": close, "high": close, "low": close, "close": close, "volume": volume,
                          "source": "official", "sourceType": "true-candle", "quality": "ok", "isTrueCandle": True}, "1h")


def run(strategy, closes, volume=4000):
    """Hourly true candles, one an hour, flat inside each bar."""
    events = [parse_event(row(i, close, volume)) for i, close in enumerate(closes)]
    return Backtest(events, strategy, venue="kalshi", initial_cash=100).run()


class BuyTheDipRules(unittest.TestCase):
    def test_buys_under_forty_and_sells_over_sixty(self):
        result = run(BuyTheDip(), [0.50, 0.38, 0.37, 0.50, 0.62, 0.63, 0.64])
        sides = [f.side for f in result.fills]
        self.assertIn("buy", sides)
        self.assertIn("sell", sides)
        self.assertEqual(result.portfolio.position, 0)
        self.assertGreater(result.portfolio.cash, 100)

    def test_an_order_never_fills_on_the_candle_that_caused_it(self):
        result = run(BuyTheDip(), [0.50, 0.38, 0.38, 0.37])
        signal_known_at = 2 * HOUR_MS             # the 0.38 bar opens at hour 1 and is known at hour 2
        self.assertTrue(result.fills)
        self.assertTrue(all(f.ts > signal_known_at for f in result.fills))

    def test_nothing_happens_between_forty_and_sixty(self):
        result = run(BuyTheDip(), [0.45, 0.50, 0.55, 0.59])
        self.assertEqual(len(result.orders), 0)

    def test_a_thin_candle_fills_only_part_of_the_order(self):
        # 16 contracts traded that hour: four marks of 4, and an order may take a quarter of each.
        result = run(BuyTheDip(), [0.50, 0.38, 0.38], volume=16)
        bought = sum(f.size for f in result.fills if f.side == "buy")
        self.assertGreater(bought, 0)
        self.assertLess(bought, 100)

    def test_the_buy_is_pulled_when_the_price_runs_away(self):
        result = run(BuyTheDip(), [0.50, 0.38, 0.55, 0.55])
        self.assertEqual(result.portfolio.position, 0)
        self.assertEqual([o.status for o in result.orders], ["canceled"])


class BackTheFavouriteRules(unittest.TestCase):
    def test_buys_at_eighty_five_and_never_sells(self):
        result = run(BackTheFavourite(), [0.70, 0.86, 0.86, 0.90, 0.30])
        self.assertTrue(result.fills)
        self.assertTrue(all(f.side == "buy" for f in result.fills))
        self.assertGreater(result.portfolio.position, 0)

    def test_ignores_anything_under_the_line(self):
        self.assertEqual(len(run(BackTheFavourite(), [0.60, 0.80, 0.84]).orders), 0)


class Fees(unittest.TestCase):
    def test_kalshi_fee_matches_the_venue_example(self):
        # Kalshi's fee-rounding page: 100 contracts at 45 cents cost $1.74 in fees.
        self.assertAlmostEqual(fee_for_fill("kalshi", 0.45, 100).fee, 1.74, places=2)


class Settlement(unittest.TestCase):
    def test_yes_pays_a_dollar_and_no_pays_nothing(self):
        self.assertAlmostEqual(settle(100, 60.0, 0.40, "yes", 0.9)["finalCash"], 160.0)
        self.assertAlmostEqual(settle(100, 60.0, 0.40, "no", 0.9)["finalCash"], 60.0)
        self.assertAlmostEqual(settle(100, 60.0, 0.40, "no", 0.9)["pnlOnHeld"], -40.0)

    def test_an_unsettled_market_stays_at_the_last_price_and_says_so(self):
        got = settle(100, 60.0, 0.40, None, 0.55)
        self.assertEqual(got["basis"], "last-price")
        self.assertAlmostEqual(got["finalCash"], 115.0)

    def test_run_contract_settles_what_is_still_held(self):
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder) / "T.ndjson"
            file.write_text("\n".join(json.dumps(row(i, close)) for i, close in enumerate([0.5, 0.3, 0.3, 0.29, 0.2])), encoding="utf-8")
            lost = run_contract({"ticker": "T", "event": "E", "result": "no"}, file, "buy-the-dip")
            won = run_contract({"ticker": "T", "event": "E", "result": "yes"}, file, "buy-the-dip")
        self.assertLess(lost["pnl"], -25)             # about 100 contracts at 30 cents, worth nothing
        self.assertGreater(won["pnl"], 60)            # the same contracts, worth a dollar each
        self.assertEqual(lost["trades"][-1]["how"], "settled")


class CombinedCurve(unittest.TestCase):
    def test_accounts_add_up_and_step_to_their_settled_cash(self):
        runs = [
            {"curve": [(10, 100.0), (20, 110.0)], "settleAt": 30, "finalCash": 150.0},
            {"curve": [(15, 90.0)], "settleAt": 40, "finalCash": 60.0},
        ]
        self.assertEqual(combine_curves(runs, 100.0), [[10, 200.0], [15, 190.0], [20, 200.0], [30, 240.0], [40, 210.0]])


if __name__ == "__main__":
    unittest.main()
