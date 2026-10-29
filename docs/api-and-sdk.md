# Using the Predictefy API and Python SDK for Kalshi backtests

This guide connects the code in this repository to the official [Predictefy API](https://predictefy.com/en/prediction-market-api?utm_source=github&utm_medium=repo&utm_campaign=kalshi-backtest&utm_content=sdk-guide) and [Python SDK](https://docs.predictefy.com/guides/python-sdk/). The client reads market data; the backtest then runs locally from saved candles. It does not submit trades.

## Install and authenticate

Follow the [repository quickstart](../README.md#quick-start). The project pins [`predictefy==1.0.0b9`](https://pypi.org/project/predictefy/) so the recorded example uses a reproducible SDK version. Check the [Python SDK documentation](https://docs.predictefy.com/guides/python-sdk/) before changing versions.

Create your key in the [Predictefy key dashboard](https://portal.predictefy.com/keys), copy `.env.example` to `.env`, and set `PREDICTEFY_API_KEY`. Keep the file local. See the [API quickstart](https://docs.predictefy.com/quickstart/) and [API-key guide](https://docs.predictefy.com/guides/api-keys/) for authentication details.

## Python calls and REST endpoints

| Code in this project | REST endpoint or local operation | Reference |
|---|---|---|
| `client.kalshi.fetch_markets(...)` | `GET /api/kalshi/fetchMarkets` | [Market catalog API](https://docs.predictefy.com/api/operations/fetchmarkets/) |
| `client.kalshi.fetch_ohlcv(...)` | `GET /api/kalshi/fetchOHLCV` | [Historical OHLCV API](https://docs.predictefy.com/api/operations/fetchohlcv/) |
| `Backtest(NdjsonFileFeed(...), strategy, ...)` | Local replay; no HTTP request | [Backtesting on candles](https://docs.predictefy.com/guides/cookbook/backtest-on-candles/) |
| `python serve.py` | Local results page on `127.0.0.1` | [Results server source](../kalshi_backtest/server.py) |

The [fetcher](../kalshi_backtest/fetch.py) saves raw responses, metadata and normalized replay rows. The [loader](../kalshi_backtest/data.py) checks candle labels, prices and volume before replay. Kalshi's public market record supplies the settlement result separately; a last traded price alone is not proof of settlement.

See [historical data coverage and provenance](https://docs.predictefy.com/guides/history/) for the meaning of candle sources. Check [venue coverage](https://docs.predictefy.com/reference/venues/) before adapting this Kalshi example to another venue.

## Credits and history access

The recorded collection used two market catalog requests and twenty-two candle requests: 112 credits at the documented action costs. Running `python backtest.py` again uses the saved files and makes no API calls. Future collection costs can differ with pagination, retries and available contracts.

An available credit balance does not grant an older history window. Review [API credits and plan entitlements](https://docs.predictefy.com/guides/credits/) and [current pricing](https://predictefy.com/en/pricing). The `--free` example uses a rolling seven-day window and an event configured for the October 2026 recording; update that event when it is no longer current.

## Errors and repeatability

- `401`: check the key and the [authentication instructions](https://docs.predictefy.com/guides/api-keys/).
- `402 INSUFFICIENT_CREDITS`: consult the [credit rules](https://docs.predictefy.com/guides/credits/).
- `403 PLAN_REQUIRED`: verify that the plan includes the requested history window; the CLI prints the available alternative.
- Retry only failures marked retryable. Follow [rate limits and retries](https://docs.predictefy.com/guides/rate-limits/) and the [error reference](https://docs.predictefy.com/guides/errors/).

Save the response and its collection time before calculating results. Keep missing periods visible and distinguish last-price marks from settled cash. The [API best-practices guide](https://docs.predictefy.com/guides/best-practices/) and this project's [strategy and fill assumptions](../README.md#what-the-result-rests-on) explain the relevant boundaries.

## Other clients

This repository uses Python. If your application is in TypeScript, start with the official [Predictefy TypeScript SDK](https://docs.predictefy.com/guides/sdk/) and [API reference](https://docs.predictefy.com/api/) instead. The [API overview](https://predictefy.com/en/prediction-market-api?utm_source=github&utm_medium=repo&utm_campaign=kalshi-backtest&utm_content=sdk-guide-footer) covers the wider product.
