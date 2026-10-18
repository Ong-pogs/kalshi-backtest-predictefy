# Security and credentials

Keep your Predictefy API key in a local `.env` file or the process environment. Never commit `.env`, upload it in an issue, or include it in a screenshot. The repository contains only `.env.example` with a placeholder.

The results page binds to `127.0.0.1` and is meant to run on your own computer. It serves a saved `results.json` and makes no upstream requests, so the browser never sees the key. Do not expose it to the internet without adding authentication.

This project reads public market data. It does not need a Kalshi login, an API key for Kalshi, a private key or order permission. Do not add any of these to its configuration.

If you expose an API key, revoke or rotate it at [portal.predictefy.com/keys](https://portal.predictefy.com/keys). Removing it from the latest file alone does not remove it from Git history.

For a suspected vulnerability, use the repository's private vulnerability reporting option under **Security → Report a vulnerability**. Use synthetic values in reproductions and avoid publishing credentials. Ordinary bugs can be reported in public issues with redacted output.
