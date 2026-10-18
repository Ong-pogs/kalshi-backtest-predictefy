import unittest

from predictefy.backtest import CandleEvent, parse_event

from kalshi_backtest.data import HOUR_MS, by_month, coverage, label_counts, split_usable, to_replay_row, why_unusable


def candle(ts=0, close=0.42, volume=10, **over):
    row = {"timestamp": ts, "open": close, "high": close, "low": close, "close": close, "volume": volume,
           "source": "official", "sourceType": "true-candle", "quality": "ok", "isTrueCandle": True}
    row.update(over)
    return row


class UsableCandles(unittest.TestCase):
    def test_a_traded_candle_is_kept(self):
        self.assertIsNone(why_unusable(candle()))

    def test_a_zero_priced_candle_labelled_ok_is_dropped(self):
        # Seen on open contracts: official, true-candle, quality ok, and every price zero.
        self.assertEqual(why_unusable(candle(close=0, volume=0)), "no-trades")

    def test_missing_volume_is_not_treated_as_tradable(self):
        self.assertEqual(why_unusable(candle(volume=None)), "no-trades")

    def test_suspect_and_book_derived_are_dropped(self):
        self.assertEqual(why_unusable(candle(quality="suspect")), "suspect")
        self.assertEqual(why_unusable(candle(sourceType="book-derived")), "book-derived")

    def test_a_price_outside_zero_to_one_is_dropped(self):
        self.assertEqual(why_unusable(candle(close=1.2)), "bad-price")

    def test_split_sorts_and_counts_reasons(self):
        kept, dropped = split_usable([candle(ts=2 * HOUR_MS), candle(ts=HOUR_MS, close=0, volume=0), candle(ts=0)])
        self.assertEqual([c["timestamp"] for c in kept], [0, 2 * HOUR_MS])
        self.assertEqual(dict(dropped), {"no-trades": 1})


class Labels(unittest.TestCase):
    def test_counts_every_label(self):
        counts = label_counts([candle(), candle(source="derived", sourceType="trade-derived", isTrueCandle=False)])
        self.assertEqual(counts["source"], {"official": 1, "derived": 1})
        self.assertEqual(counts["isTrueCandle"], {"true": 1, "false": 1})

    def test_replay_row_is_what_the_backtester_parses(self):
        event = parse_event(to_replay_row(candle(ts=7 * HOUR_MS, close=0.31, volume=5), "1h"))
        self.assertIsInstance(event, CandleEvent)
        self.assertEqual((event.ts, event.close, event.volume, event.is_true_candle), (7 * HOUR_MS, 0.31, 5.0, True))


class Coverage(unittest.TestCase):
    def test_share_and_longest_gap(self):
        stamps = [0, HOUR_MS, 5 * HOUR_MS]
        got = coverage(stamps, 0, 10 * HOUR_MS)
        self.assertEqual((got["hours"], got["withCandle"]), (10, 3))
        self.assertAlmostEqual(got["share"], 0.3)
        self.assertEqual(got["longestGapHours"], 4)          # hours 6, 7, 8 and 9
        self.assertEqual(got["longestGapFrom"], 6 * HOUR_MS)

    def test_candles_outside_the_window_do_not_count(self):
        self.assertEqual(coverage([-HOUR_MS, 0, 99 * HOUR_MS], 0, 10 * HOUR_MS)["withCandle"], 1)

    def test_by_month_uses_utc(self):
        self.assertEqual(by_month([0, 31 * 24 * HOUR_MS]), {"1970-01": 1, "1970-02": 1})


if __name__ == "__main__":
    unittest.main()
