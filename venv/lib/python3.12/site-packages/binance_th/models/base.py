"""Base model classes for Binance Thailand API.

This module provides base Pydantic model configurations and
common response models used across the library.

Model Policies:
- Response models: Use extra="allow" for forward compatibility with new API fields
- Request models: Use extra="forbid" for strict validation
- Financial data: Use Decimal for prices, quantities, and balances
"""

from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from binance_th.models.enums import (
    FilterType,
    RateLimitInterval,
    RateLimitType,
    SymbolStatus,
    SymbolType,
)


class ResponseModel(BaseModel):
    """Base model for API responses.

    Allows extra fields for forward compatibility when Binance
    adds new fields to their API responses.
    """

    model_config = ConfigDict(
        extra="allow",
        populate_by_name=True,
        str_strip_whitespace=True,
    )


class RequestModel(BaseModel):
    """Base model for API requests.

    Uses strict validation to catch errors before sending.
    Extra fields are forbidden to prevent typos.
    """

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        str_strip_whitespace=True,
    )


class ServerTime(ResponseModel):
    """Server time response.

    Response from GET /api/v1/time
    """

    server_time: int = Field(alias="serverTime", description="Server timestamp in milliseconds")


class SymbolTypeInfo(ResponseModel):
    """Symbol type information.

    Response from GET /api/v1/symbolType showing whether
    a symbol is GLOBAL or SITE type.
    """

    symbol: str = Field(description="Trading pair symbol")
    symbol_type: str = Field(alias="type", description="Symbol type: GLOBAL or SITE")


class RateLimit(ResponseModel):
    """Rate limit configuration from exchange info.

    Defines rate limiting rules for API requests.
    """

    rate_limit_type: RateLimitType = Field(
        alias="rateLimitType",
        description="Type of rate limit (REQUEST_WEIGHT, ORDERS, RAW_REQUESTS)",
    )
    interval: RateLimitInterval = Field(description="Time interval unit")
    interval_num: int = Field(alias="intervalNum", description="Number of intervals")
    limit: int = Field(description="Maximum allowed within interval")


class SymbolFilter(ResponseModel):
    """Symbol filter from exchange info.

    Filters define trading rules for symbols (price, lot size, etc.).
    Different filter types have different fields.
    """

    filter_type: FilterType = Field(alias="filterType", description="Type of filter")

    # PRICE_FILTER fields
    min_price: Decimal | None = Field(
        default=None,
        alias="minPrice",
        description="Minimum price allowed",
    )
    max_price: Decimal | None = Field(
        default=None,
        alias="maxPrice",
        description="Maximum price allowed",
    )
    tick_size: Decimal | None = Field(
        default=None,
        alias="tickSize",
        description="Price increment step",
    )

    # PERCENT_PRICE fields
    multiplier_up: Decimal | None = Field(
        default=None,
        alias="multiplierUp",
        description="Max price multiplier from weighted avg",
    )
    multiplier_down: Decimal | None = Field(
        default=None,
        alias="multiplierDown",
        description="Min price multiplier from weighted avg",
    )
    avg_price_mins: int | None = Field(
        default=None,
        alias="avgPriceMins",
        description="Minutes for weighted average price",
    )

    # LOT_SIZE and MARKET_LOT_SIZE fields
    min_qty: Decimal | None = Field(
        default=None,
        alias="minQty",
        description="Minimum quantity allowed",
    )
    max_qty: Decimal | None = Field(
        default=None,
        alias="maxQty",
        description="Maximum quantity allowed",
    )
    step_size: Decimal | None = Field(
        default=None,
        alias="stepSize",
        description="Quantity increment step",
    )

    # MIN_NOTIONAL fields
    min_notional: Decimal | None = Field(
        default=None,
        alias="minNotional",
        description="Minimum notional value (price * quantity)",
    )
    apply_to_market: bool | None = Field(
        default=None,
        alias="applyToMarket",
        description="Whether applies to market orders",
    )

    # MAX_NUM_ORDERS fields
    max_num_orders: int | None = Field(
        default=None,
        alias="maxNumOrders",
        description="Maximum number of open orders",
    )
    max_num_algo_orders: int | None = Field(
        default=None,
        alias="maxNumAlgoOrders",
        description="Maximum algorithmic orders",
    )
    max_num_iceberg_orders: int | None = Field(
        default=None,
        alias="maxNumIcebergOrders",
        description="Maximum iceberg orders",
    )

    # ICEBERG_PARTS fields
    iceberg_limit: int | None = Field(
        default=None,
        alias="limit",
        description="Maximum iceberg order parts",
    )


class SymbolInfo(ResponseModel):
    """Symbol information from exchange info.

    Contains trading rules and constraints for a symbol.
    """

    symbol: str = Field(description="Trading pair symbol (e.g., BTCUSDT)")
    status: SymbolStatus = Field(description="Trading status")
    symbol_type: SymbolType | None = Field(
        default=None,
        alias="type",
        description="TH symbol type: GLOBAL or SITE (ADR-0011)",
    )
    test: int | None = Field(default=None, description="1 if a test symbol")
    base_asset: str = Field(alias="baseAsset", description="Base asset (e.g., BTC)")
    base_asset_precision: int = Field(
        alias="baseAssetPrecision",
        description="Base asset decimal precision",
    )
    quote_asset: str = Field(alias="quoteAsset", description="Quote asset (e.g., USDT)")
    quote_precision: int = Field(alias="quotePrecision", description="Quote decimal precision")
    quote_asset_precision: int = Field(
        alias="quoteAssetPrecision",
        description="Quote asset decimal precision",
    )
    base_commission_precision: int | None = Field(
        default=None,
        alias="baseCommissionPrecision",
        description="Base asset commission precision",
    )
    quote_commission_precision: int | None = Field(
        default=None,
        alias="quoteCommissionPrecision",
        description="Quote asset commission precision",
    )
    order_types: list[str] = Field(
        alias="orderTypes",
        description="Allowed order types for this symbol",
    )
    filters: list[SymbolFilter] = Field(description="Trading filters/constraints")
    # Absent on live Binance TH exchangeInfo (verified 2026-07-09); kept optional for
    # forward-compatibility and parity with the global API.
    iceberg_allowed: bool | None = Field(
        default=None, alias="icebergAllowed", description="Iceberg orders allowed"
    )
    oco_allowed: bool | None = Field(
        default=None, alias="ocoAllowed", description="OCO orders allowed"
    )
    is_spot_trading_allowed: bool | None = Field(
        default=None,
        alias="isSpotTradingAllowed",
        description="Spot trading allowed",
    )
    is_margin_trading_allowed: bool | None = Field(
        default=None,
        alias="isMarginTradingAllowed",
        description="Margin trading allowed",
    )
    permissions: list[str] | None = Field(default=None, description="Trading permissions")

    def get_filter(self, filter_type: FilterType) -> SymbolFilter | None:
        """Get a specific filter by type.

        Args:
            filter_type: The filter type to retrieve

        Returns:
            The filter or None if not found
        """
        for f in self.filters:
            if f.filter_type == filter_type:
                return f
        return None


class ExchangeInfo(ResponseModel):
    """Exchange information response.

    Response from GET /api/v1/exchangeInfo containing
    rate limits and symbol trading rules.
    """

    timezone: str = Field(description="Server timezone")
    server_time: int = Field(alias="serverTime", description="Server timestamp in milliseconds")
    rate_limits: list[RateLimit] = Field(alias="rateLimits", description="Rate limit rules")
    exchange_filters: list[dict[str, Any]] = Field(
        alias="exchangeFilters",
        description="Exchange-level filters",
    )
    symbols: list[SymbolInfo] = Field(description="Symbol information")

    def get_symbol(self, symbol: str) -> SymbolInfo | None:
        """Get symbol info by name.

        Args:
            symbol: Symbol name (e.g., "BTCUSDT")

        Returns:
            Symbol info or None if not found
        """
        for s in self.symbols:
            if s.symbol == symbol:
                return s
        return None
