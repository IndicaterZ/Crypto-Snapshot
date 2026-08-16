"""Market data models for Binance Thailand API.

This module defines Pydantic models for all market data responses
including order book, trades, klines, and tickers.
"""

from decimal import Decimal
from typing import Any, Self

from pydantic import Field

from binance_th.models.base import ResponseModel


class OrderBookEntry(ResponseModel):
    """Single entry in order book (bid or ask).

    Order book entries are returned as [price, quantity] arrays.
    """

    price: Decimal = Field(description="Price level")
    quantity: Decimal = Field(description="Quantity at this price level")

    @classmethod
    def from_list(cls, data: list[str]) -> Self:
        """Create from API array format [price, quantity].

        Args:
            data: Array with [price, quantity] as strings

        Returns:
            OrderBookEntry instance
        """
        return cls(price=Decimal(data[0]), quantity=Decimal(data[1]))


class OrderBook(ResponseModel):
    """Order book depth response.

    Response from GET /api/v1/depth
    """

    last_update_id: int = Field(alias="lastUpdateId", description="Last update ID")
    bids: list[OrderBookEntry] = Field(description="Bid orders (buy side)")
    asks: list[OrderBookEntry] = Field(description="Ask orders (sell side)")

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Self:
        """Create from raw API response.

        Args:
            data: Raw API response dictionary

        Returns:
            OrderBook instance
        """
        return cls(
            last_update_id=int(data["lastUpdateId"]),
            bids=[OrderBookEntry.from_list(b) for b in data["bids"]],
            asks=[OrderBookEntry.from_list(a) for a in data["asks"]],
        )


class Trade(ResponseModel):
    """Recent trade information.

    Response from GET /api/v1/trades
    """

    id: int = Field(description="Trade ID")
    price: Decimal = Field(description="Trade price")
    qty: Decimal = Field(description="Trade quantity")
    quote_qty: Decimal | None = Field(
        default=None, alias="quoteQty", description="Quote asset quantity (null on SITE symbols)"
    )
    time: int = Field(description="Trade timestamp in milliseconds")
    is_buyer_maker: bool = Field(
        alias="isBuyerMaker",
        description="True if buyer was the maker",
    )
    is_best_match: bool = Field(alias="isBestMatch", description="Best price match")


class AggregateTrade(ResponseModel):
    """Compressed aggregate trade information.

    Response from GET /api/v1/aggTrades
    Aggregates multiple trades at the same price.
    """

    agg_trade_id: int = Field(alias="a", description="Aggregate trade ID")
    price: Decimal = Field(alias="p", description="Trade price")
    quantity: Decimal = Field(alias="q", description="Trade quantity")
    first_trade_id: int = Field(alias="f", description="First trade ID in aggregate")
    last_trade_id: int = Field(alias="l", description="Last trade ID in aggregate")
    timestamp: int = Field(alias="T", description="Timestamp in milliseconds")
    is_buyer_maker: bool = Field(alias="m", description="True if buyer was the maker")


class Kline(ResponseModel):
    """Kline/candlestick data.

    Response from GET /api/v1/klines
    Each kline is returned as an array that needs parsing.
    """

    open_time: int = Field(description="Kline open timestamp in milliseconds")
    open_price: Decimal = Field(description="Open price")
    high_price: Decimal = Field(description="High price")
    low_price: Decimal = Field(description="Low price")
    close_price: Decimal = Field(description="Close price")
    volume: Decimal = Field(description="Base asset volume")
    close_time: int = Field(description="Kline close timestamp in milliseconds")
    quote_volume: Decimal = Field(description="Quote asset volume")
    trade_count: int = Field(description="Number of trades")
    taker_buy_base_volume: Decimal = Field(description="Taker buy base asset volume")
    taker_buy_quote_volume: Decimal = Field(description="Taker buy quote asset volume")

    @classmethod
    def from_list(cls, data: list[str | int]) -> Self:
        """Create from API array format.

        Args:
            data: Array with kline data [open_time, open, high, low, close, volume,
                  close_time, quote_volume, trade_count, taker_buy_base_vol,
                  taker_buy_quote_vol, unused]

        Returns:
            Kline instance
        """
        return cls(
            open_time=int(data[0]),
            open_price=Decimal(str(data[1])),
            high_price=Decimal(str(data[2])),
            low_price=Decimal(str(data[3])),
            close_price=Decimal(str(data[4])),
            volume=Decimal(str(data[5])),
            close_time=int(data[6]),
            quote_volume=Decimal(str(data[7])),
            trade_count=int(data[8]),
            taker_buy_base_volume=Decimal(str(data[9])),
            taker_buy_quote_volume=Decimal(str(data[10])),
        )


class Ticker24hr(ResponseModel):
    """24-hour ticker statistics.

    Response from GET /api/v1/ticker/24hr
    """

    symbol: str = Field(description="Trading pair symbol")
    price_change: Decimal = Field(alias="priceChange", description="Price change in period")
    price_change_percent: Decimal = Field(
        alias="priceChangePercent",
        description="Price change percentage",
    )
    weighted_avg_price: Decimal = Field(
        alias="weightedAvgPrice",
        description="Weighted average price",
    )
    prev_close_price: Decimal | None = Field(
        default=None,
        alias="prevClosePrice",
        description="Previous close price (null on some SITE symbols)",
    )
    last_price: Decimal = Field(alias="lastPrice", description="Last traded price")
    last_qty: Decimal | None = Field(
        default=None,
        alias="lastQty",
        description="Last traded quantity (null on some SITE symbols)",
    )
    bid_price: Decimal | None = Field(
        default=None, alias="bidPrice", description="Best bid price (null on some SITE symbols)"
    )
    bid_qty: Decimal | None = Field(
        default=None, alias="bidQty", description="Best bid quantity (null on some SITE symbols)"
    )
    ask_price: Decimal | None = Field(
        default=None, alias="askPrice", description="Best ask price (null on some SITE symbols)"
    )
    ask_qty: Decimal | None = Field(
        default=None, alias="askQty", description="Best ask quantity (null on some SITE symbols)"
    )
    open_price: Decimal = Field(alias="openPrice", description="Open price")
    high_price: Decimal = Field(alias="highPrice", description="High price")
    low_price: Decimal = Field(alias="lowPrice", description="Low price")
    volume: Decimal = Field(description="Base asset volume")
    quote_volume: Decimal = Field(alias="quoteVolume", description="Quote asset volume")
    open_time: int = Field(alias="openTime", description="Statistics open time")
    close_time: int = Field(alias="closeTime", description="Statistics close time")
    first_id: int = Field(alias="firstId", description="First trade ID")
    last_id: int = Field(alias="lastId", description="Last trade ID")
    count: int = Field(description="Number of trades")


class PriceTicker(ResponseModel):
    """Symbol price ticker.

    Response from GET /api/v1/ticker/price
    Simple price ticker showing latest price.
    """

    symbol: str = Field(description="Trading pair symbol")
    price: Decimal = Field(description="Latest price")


class BookTicker(ResponseModel):
    """Symbol order book ticker.

    Response from GET /api/v1/ticker/bookTicker
    Best bid and ask prices.
    """

    symbol: str = Field(description="Trading pair symbol")
    bid_price: Decimal = Field(alias="bidPrice", description="Best bid price")
    bid_qty: Decimal = Field(alias="bidQty", description="Best bid quantity")
    ask_price: Decimal = Field(alias="askPrice", description="Best ask price")
    ask_qty: Decimal = Field(alias="askQty", description="Best ask quantity")


class ReferencePrice(ResponseModel):
    """Reference price for a GLOBAL symbol.

    Response from GET /api/v1/referencePrice (TH-only). ``symbol`` is required and
    only GLOBAL symbols are served — SITE/THB symbols return HTTP 400.
    """

    symbol: str = Field(description="Trading pair symbol")
    reference_price: Decimal = Field(alias="referencePrice", description="Reference price")
    timestamp: int = Field(description="Server timestamp in milliseconds")


class ExecutionRule(ResponseModel):
    """A single execution rule (e.g. PRICE_RANGE) for a symbol.

    Part of GET /api/v1/executionRules. The PRICE_RANGE multipliers may be null.
    """

    rule_type: str = Field(alias="ruleType", description="Rule type, e.g. PRICE_RANGE")
    bid_multiplier_up: Decimal | None = Field(
        default=None, alias="bidMultiplierUp", description="Max bid price multiplier"
    )
    bid_multiplier_down: Decimal | None = Field(
        default=None, alias="bidMultiplierDown", description="Min bid price multiplier"
    )
    ask_multiplier_up: Decimal | None = Field(
        default=None, alias="askMultiplierUp", description="Max ask price multiplier"
    )
    ask_multiplier_down: Decimal | None = Field(
        default=None, alias="askMultiplierDown", description="Min ask price multiplier"
    )


class SymbolExecutionRules(ResponseModel):
    """Execution rules for one symbol."""

    symbol: str = Field(description="Trading pair symbol")
    rules: list[ExecutionRule] = Field(description="Execution rules for the symbol")


class ExecutionRules(ResponseModel):
    """Execution rules response.

    Response from GET /api/v1/executionRules (TH-only). Contains GLOBAL symbols only.
    """

    symbol_rules: list[SymbolExecutionRules] = Field(
        alias="symbolRules", description="Per-symbol execution rules"
    )

    def get_symbol(self, symbol: str) -> SymbolExecutionRules | None:
        """Get execution rules for a symbol, or None if absent."""
        for entry in self.symbol_rules:
            if entry.symbol == symbol:
                return entry
        return None
