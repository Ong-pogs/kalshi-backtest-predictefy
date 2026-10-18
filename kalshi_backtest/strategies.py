"""The two strategies, written for predictefy.backtest.

A strategy sees one hourly candle at a time, after that hour has closed. Whatever it
orders can fill no earlier than the next candle, so it never trades on a price it
could not have seen.
"""

from __future__ import annotations

from predictefy.backtest import Strategy

#: A partial fill can leave a sliver of a contract behind. Anything smaller than this
#: counts as holding nothing, so the strategy neither sells dust nor waits on it.
DUST = 0.01


class BuyTheDip(Strategy):
    """Buy a contract when its hourly close is 40 cents or lower; sell at 60 or higher."""

    name = "buy-the-dip"
    label = "Buy the dip"
    rule = "Buy 100 contracts when the hourly close is 40¢ or lower. Sell them when it is back at 60¢ or higher."

    def __init__(self, buy_at: float = 0.40, sell_at: float = 0.60, lot: float = 100.0) -> None:
        self.buy_at, self.sell_at, self.lot = buy_at, sell_at, lot

    def on_event(self, ev, ctx) -> None:
        if ev.k != "candle":
            return
        price = ev.close
        if ctx.open_orders:
            # One order at a time. If the price has moved away from the signal, pull it.
            for order in ctx.open_orders:
                gone = price > self.buy_at if order.side == "buy" else price < self.sell_at
                if gone:
                    ctx.cancel(order.order_id)
            return
        if ctx.position < DUST and price <= self.buy_at:
            ctx.buy(size=self.lot, price=price)
        elif ctx.position >= DUST and price >= self.sell_at:
            ctx.sell(size=ctx.position, price=price)


class BackTheFavourite(Strategy):
    """Buy a contract when its hourly close is 85 cents or higher, and hold it to settlement."""

    name = "back-the-favourite"
    label = "Back the favourite"
    rule = "Buy 100 contracts when the hourly close is 85¢ or higher, and hold them until the market settles."

    def __init__(self, buy_at: float = 0.85, lot: float = 100.0) -> None:
        self.buy_at, self.lot = buy_at, lot
        self.entered = False

    def on_event(self, ev, ctx) -> None:
        if ev.k != "candle":
            return
        price = ev.close
        if ctx.open_orders:
            if price < self.buy_at:
                for order in ctx.open_orders:
                    ctx.cancel(order.order_id)
                # Nothing bought yet: the next close above the line may try again.
                self.entered = ctx.position >= DUST
            return
        if not self.entered and ctx.position < DUST and price >= self.buy_at:
            ctx.buy(size=self.lot, price=price)
            self.entered = True


STRATEGIES = {cls.name: cls for cls in (BuyTheDip, BackTheFavourite)}
