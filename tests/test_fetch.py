import unittest

from predictefy.errors import PredictefyError

from kalshi_backtest import config
from kalshi_backtest.fetch import MAX_CANDLES, plan_message, read_candles


class FakeKalshi:
    def __init__(self, pages):
        self.pages, self.calls = list(pages), []

    def fetch_ohlcv(self, params):
        self.calls.append(dict(params))
        return {"data": self.pages.pop(0), "meta": {"provenance": "predictefy-store"}}


class FakeClient:
    def __init__(self, pages):
        self.kalshi = FakeKalshi(pages)


class Paging(unittest.TestCase):
    def test_a_full_page_is_followed_by_another_request(self):
        first = [{"timestamp": i * 3_600_000} for i in range(MAX_CANDLES)]
        client = FakeClient([first, [{"timestamp": MAX_CANDLES * 3_600_000}]])
        candles, provenance = read_candles(client, "KXTEST", "1970-01-01T00:00:00+00:00", "1971-01-01T00:00:00+00:00")
        self.assertEqual(len(candles), MAX_CANDLES + 1)
        self.assertEqual(len(client.kalshi.calls), 2)
        self.assertGreater(client.kalshi.calls[1]["start"], client.kalshi.calls[0]["start"])
        self.assertEqual(provenance, ["predictefy-store", "predictefy-store"])

    def test_no_window_means_no_start_or_end_is_sent(self):
        client = FakeClient([[]])
        read_candles(client, "KXTEST", None, None)
        self.assertNotIn("start", client.kalshi.calls[0])
        self.assertNotIn("end", client.kalshi.calls[0])


class PlanGate(unittest.TestCase):
    def test_the_message_names_the_plans_and_links_the_upgrade(self):
        error = PredictefyError(status=403, code="PLAN_REQUIRED", message="history window requires Builder")
        text = plan_message(error, "12 months")
        self.assertIn("403 PLAN_REQUIRED", text)
        self.assertIn("7 days", text)
        self.assertIn(config.UPGRADE_URL, text)
        self.assertIn("--free", text)
        self.assertNotIn("--free", plan_message(error, "free"))


if __name__ == "__main__":
    unittest.main()
