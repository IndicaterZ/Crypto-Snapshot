"""WebSocket market-stream event models for Binance Thailand (M5).

Shapes were **verified live on 2026-07-09** via ``scripts/probe_ws.py`` against the
dual-host market-stream topology (GLOBAL symbols on ``/gstream``, SITE symbols on
``/nstream``), which delivers a combined ``{"stream": ..., "data": ...}`` envelope.

GLOBAL and SITE payloads are **not** identical (ADR-0011 "no parity"), so keys that
appeared for only one symbol type are modelled ``Optional``:

- ``depthUpdate`` — SITE adds ``T`` (transaction time) and ``pu`` (previous final id).
- ``trade`` / ``aggTrade`` — ``M`` (is-best-match) is GLOBAL-only.
- ``bookTicker`` — SITE adds ``e`` / ``E`` / ``T``.

``ticker`` (24hrTicker) was captured on a GLOBAL symbol only; its statistics fields
are ``Optional`` pending a SITE observation. ``kline`` was captured identically on
both. All models subclass :class:`ResponseModel` (``extra="allow"``), so any field a
future symbol adds is preserved rather than rejected.
"""

from decimal import Decimal
from typing import Any

from pydantic import Field, field_validator

from binance_th.models.base import ResponseModel
from binance_th.models.market import OrderBookEntry


def _parse_levels(value: Any) -> Any:
    """Coerce ``[[price, qty], ...]`` wire arrays into :class:`OrderBookEntry`."""
    if isinstance(value, list):
        return [OrderBookEntry.from_list(x) if isinstance(x, list) else x for x in value]
    return value


class StreamMessage(ResponseModel):
    """Combined-stream envelope ``{"stream": ..., "data": ...}`` (verified 2026-07-09)."""

    stream: str = Field(description="Stream name, e.g. 'btcthb@depth'")
    data: dict[str, Any] = Field(description="Raw event payload for the named stream")


class DepthUpdateEvent(ResponseModel):
    """Diff-depth update (``e=depthUpdate``).

    SITE symbols additionally carry ``T`` and ``pu``; GLOBAL symbols do not. ``b``/``a``
    are ``[price, quantity]`` string arrays; a quantity of ``0`` removes that level.
    """

    event_type: str = Field(alias="e", description="Event type ('depthUpdate')")
    event_time: int = Field(alias="E", description="Event time (ms)")
    transaction_time: int | None = Field(
        default=None, alias="T", description="Transaction time (ms); SITE only"
    )
    symbol: str = Field(alias="s", description="Symbol")
    first_update_id: int = Field(alias="U", description="First update id in event (U)")
    final_update_id: int = Field(alias="u", description="Final update id in event (u)")
    prev_final_update_id: int | None = Field(
        default=None,
        alias="pu",
        description="Final update id of the previous event (pu); SITE only",
    )
    bids: list[OrderBookEntry] = Field(alias="b", description="Bid deltas [price, qty]")
    asks: list[OrderBookEntry] = Field(alias="a", description="Ask deltas [price, qty]")

    _coerce_levels = field_validator("bids", "asks", mode="before")(_parse_levels)


class TradeEvent(ResponseModel):
    """Single trade (``e=trade``). ``M`` (is-best-match) is GLOBAL-only."""

    event_type: str = Field(alias="e", description="Event type ('trade')")
    event_time: int = Field(alias="E", description="Event time (ms)")
    transaction_time: int = Field(alias="T", description="Trade/transaction time (ms)")
    symbol: str = Field(alias="s", description="Symbol")
    trade_id: int = Field(alias="t", description="Trade id")
    price: Decimal = Field(alias="p", description="Price")
    quantity: Decimal = Field(alias="q", description="Quantity")
    is_buyer_maker: bool = Field(alias="m", description="True if the buyer was the maker")
    is_best_match: bool | None = Field(
        default=None, alias="M", description="Best-match flag; GLOBAL only"
    )


class AggTradeEvent(ResponseModel):
    """Aggregate trade (``e=aggTrade``). ``M`` (is-best-match) is GLOBAL-only."""

    event_type: str = Field(alias="e", description="Event type ('aggTrade')")
    event_time: int = Field(alias="E", description="Event time (ms)")
    transaction_time: int = Field(alias="T", description="Trade/transaction time (ms)")
    symbol: str = Field(alias="s", description="Symbol")
    agg_trade_id: int = Field(alias="a", description="Aggregate trade id")
    price: Decimal = Field(alias="p", description="Price")
    quantity: Decimal = Field(alias="q", description="Quantity")
    first_trade_id: int = Field(alias="f", description="First trade id in the aggregate")
    last_trade_id: int = Field(alias="l", description="Last trade id in the aggregate")
    is_buyer_maker: bool = Field(alias="m", description="True if the buyer was the maker")
    is_best_match: bool | None = Field(
        default=None, alias="M", description="Best-match flag; GLOBAL only"
    )


class KlineData(ResponseModel):
    """Nested candlestick payload (the ``k`` field of a kline event)."""

    start_time: int = Field(alias="t", description="Kline start time (ms)")
    close_time: int = Field(alias="T", description="Kline close time (ms)")
    symbol: str = Field(alias="s", description="Symbol")
    interval: str = Field(alias="i", description="Interval, e.g. '1m'")
    first_trade_id: int = Field(alias="f", description="First trade id")
    last_trade_id: int = Field(alias="L", description="Last trade id")
    open_price: Decimal = Field(alias="o", description="Open price")
    close_price: Decimal = Field(alias="c", description="Close price")
    high_price: Decimal = Field(alias="h", description="High price")
    low_price: Decimal = Field(alias="l", description="Low price")
    volume: Decimal = Field(alias="v", description="Base asset volume")
    trade_count: int = Field(alias="n", description="Number of trades")
    is_closed: bool = Field(alias="x", description="True if this kline is closed/final")
    quote_volume: Decimal = Field(alias="q", description="Quote asset volume")
    taker_buy_base_volume: Decimal = Field(alias="V", description="Taker buy base volume")
    taker_buy_quote_volume: Decimal = Field(alias="Q", description="Taker buy quote volume")
    ignore: str | None = Field(default=None, alias="B", description="Ignore field")


class KlineEvent(ResponseModel):
    """Candlestick event (``e=kline``); identical shape across GLOBAL and SITE."""

    event_type: str = Field(alias="e", description="Event type ('kline')")
    event_time: int = Field(alias="E", description="Event time (ms)")
    symbol: str = Field(alias="s", description="Symbol")
    kline: KlineData = Field(alias="k", description="Candlestick payload")


class BookTickerEvent(ResponseModel):
    """Best bid/ask (``bookTicker``). SITE adds ``e`` / ``E`` / ``T``; GLOBAL omits them."""

    update_id: int = Field(alias="u", description="Order-book update id")
    symbol: str = Field(alias="s", description="Symbol")
    bid_price: Decimal = Field(alias="b", description="Best bid price")
    bid_qty: Decimal = Field(alias="B", description="Best bid quantity")
    ask_price: Decimal = Field(alias="a", description="Best ask price")
    ask_qty: Decimal = Field(alias="A", description="Best ask quantity")
    event_type: str | None = Field(default=None, alias="e", description="'bookTicker'; SITE only")
    event_time: int | None = Field(
        default=None, alias="E", description="Event time (ms); SITE only"
    )
    transaction_time: int | None = Field(
        default=None, alias="T", description="Transaction time (ms); SITE only"
    )


class TickerEvent(ResponseModel):
    """Rolling 24h ticker (``e=24hrTicker``).

    Verified on a GLOBAL symbol; statistics fields are ``Optional`` pending a SITE
    observation, and ``extra="allow"`` preserves anything not modelled here.
    """

    event_type: str = Field(alias="e", description="Event type ('24hrTicker')")
    event_time: int = Field(alias="E", description="Event time (ms)")
    symbol: str = Field(alias="s", description="Symbol")
    price_change: Decimal | None = Field(default=None, alias="p", description="Price change")
    price_change_percent: Decimal | None = Field(
        default=None, alias="P", description="Price change percent"
    )
    weighted_avg_price: Decimal | None = Field(
        default=None, alias="w", description="Weighted average price"
    )
    prev_close_price: Decimal | None = Field(
        default=None, alias="x", description="First trade (previous close) price"
    )
    last_price: Decimal | None = Field(default=None, alias="c", description="Last price")
    last_qty: Decimal | None = Field(default=None, alias="Q", description="Last quantity")
    best_bid_price: Decimal | None = Field(default=None, alias="b", description="Best bid price")
    best_bid_qty: Decimal | None = Field(default=None, alias="B", description="Best bid quantity")
    best_ask_price: Decimal | None = Field(default=None, alias="a", description="Best ask price")
    best_ask_qty: Decimal | None = Field(default=None, alias="A", description="Best ask quantity")
    open_price: Decimal | None = Field(default=None, alias="o", description="Open price")
    high_price: Decimal | None = Field(default=None, alias="h", description="High price")
    low_price: Decimal | None = Field(default=None, alias="l", description="Low price")
    volume: Decimal | None = Field(default=None, alias="v", description="Base asset volume")
    quote_volume: Decimal | None = Field(default=None, alias="q", description="Quote asset volume")
    open_time: int | None = Field(default=None, alias="O", description="Statistics open time (ms)")
    close_time: int | None = Field(
        default=None, alias="C", description="Statistics close time (ms)"
    )
    first_trade_id: int | None = Field(default=None, alias="F", description="First trade id")
    last_trade_id: int | None = Field(default=None, alias="L", description="Last trade id")
    trade_count: int | None = Field(default=None, alias="n", description="Total number of trades")
