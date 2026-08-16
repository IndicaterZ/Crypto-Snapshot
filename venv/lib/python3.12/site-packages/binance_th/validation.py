"""Pre-trade order validation against exchangeInfo filters (ADR-0009).

Pure and transport-free. Snaps ``price`` to ``tickSize`` and ``quantity`` to
``stepSize`` with **ROUND_DOWN** (never into a more aggressive order), then rejects
orders that still violate the price/lot bounds or ``MIN_NOTIONAL`` — all before any
network call, as a typed :class:`~binance_th.exceptions.BinanceThValidationError`.

Snapping uses **floor division**, not ``Decimal.quantize`` (which only fixes decimal
places, not multiples — Binance ticks aren't always powers of ten). ⚠ The TH filter
semantics are ASSUMED (mock-tested only; no signed live probe).
"""

from decimal import ROUND_DOWN, Decimal

from binance_th.exceptions import BinanceThValidationError
from binance_th.models.base import SymbolInfo
from binance_th.models.enums import FilterType, OrderType
from binance_th.models.market import SymbolExecutionRules
from binance_th.models.orders import OrderRequest

__all__ = ["snap_price", "snap_qty", "validate_order"]


def snap_price(price: Decimal, tick: Decimal | None) -> Decimal:
    """Floor ``price`` to a multiple of ``tick`` (ROUND_DOWN); unchanged if tick is 0/None."""
    if not tick:
        return price
    return (price / tick).to_integral_value(rounding=ROUND_DOWN) * tick


def snap_qty(qty: Decimal, step: Decimal | None) -> Decimal:
    """Floor ``qty`` to a multiple of ``step`` (ROUND_DOWN); unchanged if step is 0/None."""
    if not step:
        return qty
    return (qty / step).to_integral_value(rounding=ROUND_DOWN) * step


def validate_order(
    request: OrderRequest,
    symbol_info: SymbolInfo,
    execution_rules: SymbolExecutionRules | None = None,
) -> OrderRequest:
    """Return a filter-snapped copy of ``request`` or raise ``BinanceThValidationError``.

    Snaps price/stopPrice to ``tickSize`` and quantity to ``stepSize`` (ROUND_DOWN),
    then enforces the price/lot bounds and ``MIN_NOTIONAL``. A ``0`` bound means "no
    limit". The PRICE_RANGE hook is dormant (TH multipliers are null / GLOBAL-only).
    """
    price_filter = symbol_info.get_filter(FilterType.PRICE_FILTER)
    lot_filter = None
    if request.order_type == OrderType.MARKET:
        lot_filter = symbol_info.get_filter(FilterType.MARKET_LOT_SIZE)
    if lot_filter is None:
        lot_filter = symbol_info.get_filter(FilterType.LOT_SIZE)
    notional_filter = symbol_info.get_filter(FilterType.MIN_NOTIONAL)

    updates: dict[str, Decimal] = {}

    price = request.price
    if price is not None and price_filter is not None:
        price = snap_price(price, price_filter.tick_size)
        updates["price"] = price
    if price is not None:
        if price <= 0:
            raise BinanceThValidationError("price must be positive", field="price", value=price)
        if price_filter is not None:
            if price_filter.min_price and price < price_filter.min_price:
                raise BinanceThValidationError("price below minPrice", field="price", value=price)
            if price_filter.max_price and price > price_filter.max_price:
                raise BinanceThValidationError("price above maxPrice", field="price", value=price)

    if request.stop_price is not None and price_filter is not None:
        updates["stop_price"] = snap_price(request.stop_price, price_filter.tick_size)

    quantity = request.quantity
    if quantity is not None and lot_filter is not None:
        quantity = snap_qty(quantity, lot_filter.step_size)
        updates["quantity"] = quantity
    if quantity is not None:
        if quantity <= 0:
            raise BinanceThValidationError(
                "quantity snapped to zero (below stepSize)", field="quantity", value=quantity
            )
        if lot_filter is not None:
            if lot_filter.min_qty and quantity < lot_filter.min_qty:
                raise BinanceThValidationError(
                    "quantity below minQty", field="quantity", value=quantity
                )
            if lot_filter.max_qty and quantity > lot_filter.max_qty:
                raise BinanceThValidationError(
                    "quantity above maxQty", field="quantity", value=quantity
                )

    if notional_filter is not None and notional_filter.min_notional:
        notional: Decimal | None = None
        if request.quote_order_qty is not None:
            notional = request.quote_order_qty
        elif price is not None and quantity is not None:
            notional = price * quantity
        if notional is not None and notional < notional_filter.min_notional:
            raise BinanceThValidationError(
                "notional below minNotional", field="notional", value=notional
            )

    _check_price_range(execution_rules)

    if not updates:
        return request
    return request.model_copy(update=updates)


def _check_price_range(execution_rules: SymbolExecutionRules | None) -> None:
    """PRICE_RANGE band check — dormant: TH multipliers are null / GLOBAL-only.

    When a ``referencePrice`` provider is wired, enforce BUY within
    ``[ref*bidDown, ref*bidUp]`` / SELL within ``[ref*askDown, ref*askUp]`` here.
    """
    if execution_rules is None:
        return
    # Rules present but all multipliers are currently null — nothing to enforce yet.
