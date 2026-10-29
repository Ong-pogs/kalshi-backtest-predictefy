# Kalshi Backtesting with the Predictefy API and Python SDK

A small, honest backtest for Kalshi. It pulls real hourly price history through the [Predictefy API](https://predictefy.com/en/prediction-market-api?utm_source=github&utm_medium=repo&utm_campaign=kalshi-backtest&utm_content=github), replays a simple strategy over it with the backtester that ships in Predictefy's Python package, settles what is left at the real result, and shows everything on a local results page: the account value over time, every order, the fees, and where the data is thin.

Use this example to learn the [Predictefy Python SDK](https://docs.predictefy.com/guides/python-sdk/), the [historical candle API](https://docs.predictefy.com/api/operations/fetchohlcv/) and the [candle backtesting workflow](https://docs.predictefy.com/guides/cookbook/backtest-on-candles/). The [API and SDK guide](docs/api-and-sdk.md) maps the Python calls to their REST endpoints and explains which parts run offline.

[![Tests](https://github.com/Ong-pogs/kalshi-backtest-predictefy/actions/workflows/test.yml/badge.svg)](https://github.com/Ong-pogs/kalshi-backtest-predictefy/actions/workflows/test.yml)

It runs on your own computer. It never places an order and never asks for a Kalshi login.

![Results page](docs/dashboard.png)

> A backtest replays the past under stated assumptions. It is not advice and it does not predict what happens next.

## What it does

1. Lists the contracts in two settled Kalshi events: the Fed's rate after its July and September 2026 meetings, 11 rate levels each, 22 contracts.
2. Pulls hourly candles for each contract through [`fetchOHLCV`](https://docs.predictefy.com/api/operations/fetchohlcv/), follows pagination when needed, and saves them to disk. Coverage depends on the requested window and available data.
3. Reads the labels on every candle (`source`, `sourceType`, `quality`, `isTrueCandle`), drops candles that cannot be traded against, and counts what it dropped.
4. Replays two strategies with `predictefy.backtest`, one candle at a time, with Kalshi's fees and Fill Model v1.
5. Settles anything still held at the real result: $1 a contract for Yes, $0 for No.

## Quick start

You need [Python](https://www.python.org) 3.10 or newer and a Predictefy API key from [portal.predictefy.com/keys](https://portal.predictefy.com/keys).

```bash
git clone https://github.com/Ong-pogs/kalshi-backtest-predictefy
cd kalshi-backtest-predictefy
python -m venv .venv
source .venv/bin/activate      # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env           # Windows PowerShell: Copy-Item .env.example .env
```

Open `.env`, paste your key after `PREDICTEFY_API_KEY=`, then run three commands:

```bash
python fetch.py       # pull the candles (112 credits)
python backtest.py    # replay both strategies from disk (0 credits)
python serve.py       # open the results page
```

Open the address it prints, `http://127.0.0.1:8816`.

The direct dependency is the [`predictefy` Python package](https://pypi.org/project/predictefy/), pinned to `1.0.0b9` because it is a beta line. It installs its own dependency, `httpx`. See the [SDK installation guide](https://docs.predictefy.com/guides/python-sdk/) and [API quickstart](https://docs.predictefy.com/quickstart/) for the client and authentication setup.

## The recorded backtest

The video uses data collected on **October 8, 2026**: 22 contracts across two Fed events and 5,366 hourly candles, spanning approximately 13 months. The buy-the-dip run started at $2,200 and ended at **$2,201.14 after fees**. This is a historical backtest result, not funded trading performance.

The repository contains the source and tests. Local API responses, candle archives, `.env` files and generated results are excluded. Fetch your own data to run the full pipeline; the rolling window, available data and results can differ from the recording. The unit tests use local fixtures and need no API key.

## Which plan you need

| Plan | Price | History it reads | What happens here |
|---|---|---|---|
| Free | $0 | 7 days | These contracts settled more than 7 days ago, so `fetch.py` is refused with `403 PLAN_REQUIRED` and prints the upgrade link. `python fetch.py --free` works. |
| Builder | $48.88 a month | 12 months | `python fetch.py` works as it is. |
| Pro | $149 a month | unlimited | `python fetch.py --all` also reads the few candles older than 12 months. |

Plans and prices above were checked on October 18, 2026. Check [Predictefy pricing](https://predictefy.com/en/pricing) and the [API credits and history-window rules](https://docs.predictefy.com/guides/credits/) before collecting data. The free plan includes 25,000 credits a month; its history window limits access to these older contracts.

To try the whole pipeline on the free plan:

```bash
python fetch.py --free                                   # last 7 days of the open October contracts (56 credits)
python backtest.py --data data-free --out results-free
python serve.py --results results-free
```

The free example targets the October 2026 event, which was still open when recorded. It reads a rolling seven-day window. Once that event ages outside the window, choose a current event by updating `FREE_EVENT` in `kalshi_backtest/config.py`; see [finding contracts with the market API](https://docs.predictefy.com/api/operations/fetchmarkets/). Unsettled positions use the last traded price and are labelled accordingly.

## What this costs to run

| Request | Calls | Credits each | Credits |
|---|---|---|---|
| List the contracts in an event (`GET /api/kalshi/fetchMarkets`) | 2 | 1 | 2 |
| Hourly candles for one contract (`GET /api/kalshi/fetchOHLCV`) | 22 | 5 | 110 |
| **The whole backtest** | 24 | | **112** |
| Run the strategies again from the saved candles | 0 | | 0 |

The table describes the recorded collection, not a guaranteed bill for every future run. Pagination, retries and a different set of contracts can change the request count. `fetch.py` counts the `x-credits-charged` header on every response and writes the total to `data/manifest.json`. See [credit headers and action costs](https://docs.predictefy.com/guides/credits/). `python peek.py` requests a candle sample, normally 5 credits.

## The strategies

| Name | Rule |
|---|---|
| Buy the dip | Buy 100 contracts when the hourly close is 40¢ or lower. Sell them when it is back at 60¢ or higher. |
| Back the favourite | Buy 100 contracts when the hourly close is 85¢ or higher, and hold them until the market settles. |

Both are in [`kalshi_backtest/strategies.py`](kalshi_backtest/strategies.py), about 25 lines each. A strategy sees one candle at a time, after that hour has closed, and an order it places can fill no earlier than the next candle. Each contract gets its own $100 account, so every contract's result stands alone.

## What the result rests on

`predictefy.backtest` prints its assumptions with every report, and the results page shows them in full. The main ones:

- **No queue position.** A resting order fills only when the price trades through it, never on a touch.
- **No price improvement.** A resting order gets its own limit price, never a better one.
- **No market impact.** An order may take at most a quarter of what a candle traded.
- **No latency.** There is no delay between deciding and arriving, but nothing fills before the next candle.
- **Fees.** Kalshi's published taker fee, `0.07 x contracts x price x (1 - price)`, on every fill, rounded up.

Added by this project: settlement at the real result (the engine stops at the last candle), and a loader that drops candles with no volume, a zero price, a `suspect` label or a book-derived price.

## What it cannot tell you

- **It is a small sample.** 22 contracts are two Fed decisions seen from 11 rate levels each. They move together.
- **It only buys the Yes side.**
- **Hourly candles are sparse.** A candle exists only for an hour in which the contract traded. Far-dated contracts go weeks without one, and an order cannot fill in an hour nobody traded.
- **An account value in the middle of the run is not cash.** Open positions are valued at the last traded price, which in a thin market can be a few contracts at an odd price.
- **Settlement results come from Kalshi's public market record**, not from Predictefy: the market stops trading before the Fed announces, so the last candle does not show the outcome.
- **It is the past.** A flat or good result says nothing certain about the next year.

## Build it yourself

[`build-prompt.txt`](build-prompt.txt) is the full specification: the endpoints, the candle checks, the two rules, the settlement step and the results page. Paste it into an AI coding tool in an empty folder.

## Tests

```bash
python -m unittest
```

The GitHub Actions workflow runs the tests on Windows, macOS and Linux with Python 3.10 and 3.12. It does not collect API data or place orders.

## Predictefy API and SDK resources

### Start building

| Resource | Use it for |
|---|---|
| [Predictefy prediction market API](https://predictefy.com/en/prediction-market-api?utm_source=github&utm_medium=repo&utm_campaign=kalshi-backtest&utm_content=resources) | Product overview and getting access to the API |
| [Predictefy documentation](https://docs.predictefy.com/) | Guides, SDKs and endpoint reference |
| [API quickstart](https://docs.predictefy.com/quickstart/) | Your first authenticated request |
| [Create a Predictefy API key](https://portal.predictefy.com/keys) | The key used by this project's fetcher |
| [API-key guide](https://docs.predictefy.com/guides/api-keys/) | Authentication and key handling |
| [Python SDK](https://docs.predictefy.com/guides/python-sdk/) | The Python client used here |
| [TypeScript SDK](https://docs.predictefy.com/guides/sdk/) | An alternative client if you build in TypeScript; this project uses Python |

### Understand the data and the run

| Resource | Use it for |
|---|---|
| [Backtest a strategy on candles](https://docs.predictefy.com/guides/cookbook/backtest-on-candles/) | The SDK's strategy, feed and fill model |
| [Historical market data](https://docs.predictefy.com/guides/history/) | Candle sources, provenance and coverage |
| [Market catalog API](https://docs.predictefy.com/api/operations/fetchmarkets/) | Finding Kalshi contracts and outcome IDs |
| [OHLCV candle API](https://docs.predictefy.com/api/operations/fetchohlcv/) | Reading hourly history for an outcome |
| [Venue coverage](https://docs.predictefy.com/reference/venues/) | Checking what each venue supports before adapting the example |
| [API reference](https://docs.predictefy.com/api/) | Request parameters and response schemas |

### Operate the collector

- [Pricing and plans](https://predictefy.com/en/pricing) and [API credits](https://docs.predictefy.com/guides/credits/): distinguish a history entitlement from a credit allowance.
- [Rate limits and retries](https://docs.predictefy.com/guides/rate-limits/): pace requests and handle temporary failures.
- [API errors](https://docs.predictefy.com/guides/errors/): understand authentication, plan and data-availability responses.
- [API best practices](https://docs.predictefy.com/guides/best-practices/): structure data collection and retain evidence for repeatable analysis.

Further reading: [prediction market historical data APIs](https://blog.predictefy.com/prediction-market-historical-data-api), [Kalshi SDKs](https://blog.predictefy.com/kalshi-sdk), [Kalshi API vs Polymarket API](https://blog.predictefy.com/kalshi-api-vs-polymarket-api), and [getting started with a prediction market API](https://blog.predictefy.com/how-do-i-make-my-first-prediction-market-api-call).

Questions about the API or SDK: [Predictefy Discord](https://discord.gg/KVrWkhD8S).

## License

MIT. See [LICENSE](LICENSE).
