"""User-data WebSocket event models for Binance Thailand (M6).

⚠ **ASSUMED shapes.** The M6 probe (2026-07-10) verified the listenKey lifecycle and the
connect URL, but the account was idle, so **no user-data event was observed live**. These
models follow the standard Binance spot shapes and must be confirmed by a later credentialed
order-activity soak. All subclass :class:`ResponseModel` (``extra="allow"``), so any field a
real frame adds is preserved rather than rejected.

Enum-valued wire fields (side/type/status/…) are modelled as **raw ``str``**, not the library
enums: Binance TH may emit values outside the current enums (e.g. ``PENDING_CANCEL``), and a
strict enum field would crash live decode. Coercion to enums (with a safe fallback) happens
only in :func:`order_from_execution_report`.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import TypeVar

from pydantic import Field

from binance_th.models.base import ResponseModel
from binance_th.models.enums import OrderSide, OrderStatus, OrderType, TimeInForce
from binance_th.models.orders import Order

_E = TypeVar("_E", bound=StrEnum)


def _coerce(enum_cls: type[_E], raw: str, default: _E) -> _E:
    """Coerce a wire string to an enum, falling back to ``default`` on an unmodeled value."""
    try:
        return enum_cls(raw)
    except ValueError:
        return default


class AccountBalanceDelta(ResponseModel):
    """One changed balance inside an ``outboundAccountPosition`` event (the ``B`` array)."""

    asset: str = Field(alias="a", description="Asset")
    free: Decimal = Field(alias="f", description="Free balance")
    locked: Decimal = Field(alias="l", description="Locked balance")


class OutboundAccountPositionEvent(ResponseModel):
    """Account balance snapshot after any change (``e=outboundAccountPosition``). ⚠ASSUMED."""

    event_type: str = Field(alias="e", description="'outboundAccountPosition'")
    event_time: int = Field(alias="E", description="Event time (ms)")
    last_update_time: int = Field(alias="u", description="Time of the last account update (ms)")
    balances: list[AccountBalanceDelta] = Field(alias="B", description="Changed balances")


class BalanceUpdateEvent(ResponseModel):
    """A deposit/withdrawal/transfer balance delta (``e=balanceUpdate``). ⚠ASSUMED."""

    event_type: str = Field(alias="e", description="'balanceUpdate'")
    event_time: int = Field(alias="E", description="Event time (ms)")
    asset: str = Field(alias="a", description="Asset")
    balance_delta: Decimal = Field(alias="d", description="Balance delta (signed)")
    clear_time: int | None = Field(default=None, alias="T", description="Clear time (ms)")


class ExecutionReportEvent(ResponseModel):
    """Order-update event (``e=executionReport``) — the FR-UDS-02 target. ⚠ASSUMED.

    Enum-like fields are raw strings; :func:`order_from_execution_report` coerces them.
    """

    event_type: str = Field(alias="e", description="'executionReport'")
    event_time: int = Field(alias="E", description="Event time (ms)")
    symbol: str = Field(alias="s", description="Symbol")
    client_order_id: str = Field(alias="c", description="Client order id")
    side: str = Field(alias="S", description="Side (BUY/SELL)")
    order_type: str = Field(alias="o", description="Order type")
    time_in_force: str = Field(alias="f", description="Time in force")
    orig_qty: Decimal = Field(alias="q", description="Original quantity")
    price: Decimal = Field(alias="p", description="Order price")
    stop_price: Decimal | None = Field(default=None, alias="P", description="Stop price")
    current_execution_type: str = Field(alias="x", description="Current execution type")
    current_order_status: str = Field(alias="X", description="Current order status")
    reject_reason: str | None = Field(default=None, alias="r", description="Order reject reason")
    order_id: int = Field(alias="i", description="Order id")
    order_list_id: int | None = Field(
        default=None, alias="g", description="Order list id (-1 if none)"
    )
    last_executed_qty: Decimal = Field(alias="l", description="Last executed quantity")
    cumulative_filled_qty: Decimal = Field(alias="z", description="Cumulative filled quantity")
    last_executed_price: Decimal = Field(alias="L", description="Last executed price")
    commission_amount: Decimal | None = Field(default=None, alias="n", description="Commission")
    commission_asset: str | None = Field(default=None, alias="N", description="Commission asset")
    transaction_time: int | None = Field(
        default=None, alias="T", description="Transaction time (ms)"
    )
    trade_id: int | None = Field(default=None, alias="t", description="Trade id (-1 if none)")
    is_on_book: bool | None = Field(
        default=None, alias="w", description="Is the order on the book?"
    )
    is_maker: bool | None = Field(
        default=None, alias="m", description="Is this fill the maker side?"
    )
    order_creation_time: int | None = Field(
        default=None, alias="O", description="Order creation (ms)"
    )
    cumulative_quote_qty: Decimal | None = Field(
        default=None, alias="Z", description="Cumulative quote qty"
    )
    last_quote_qty: Decimal | None = Field(default=None, alias="Y", description="Last quote qty")
    quote_order_qty: Decimal | None = Field(default=None, alias="Q", description="Quote order qty")


class ListenKeyExpiredEvent(ResponseModel):
    """Emitted when the listenKey expires (``e=listenKeyExpired``). ⚠ASSUMED shape."""

    event_type: str = Field(alias="e", description="'listenKeyExpired'")
    event_time: int = Field(alias="E", description="Event time (ms)")
    listen_key: str | None = Field(default=None, alias="listenKey", description="The expired key")


def order_from_execution_report(evt: ExecutionReportEvent) -> Order:
    """Build a full :class:`Order` from an execution report (feeds the order tracker).

    Enum fields are coerced with safe fallbacks; possibly-absent fields fall back to
    ``event_time`` / ``0`` so a brand-new order seen live (before any REST read) is
    representable.
    """
    status = _coerce(OrderStatus, evt.current_order_status, OrderStatus.NEW)
    is_active = status in (OrderStatus.NEW, OrderStatus.PARTIALLY_FILLED)
    return Order(
        symbol=evt.symbol,
        order_id=evt.order_id,
        order_list_id=evt.order_list_id if evt.order_list_id is not None else -1,
        client_order_id=evt.client_order_id,
        price=evt.price,
        orig_qty=evt.orig_qty,
        executed_qty=evt.cumulative_filled_qty,
        cummulative_quote_qty=(
            evt.cumulative_quote_qty if evt.cumulative_quote_qty is not None else Decimal("0")
        ),
        status=status,
        time_in_force=_coerce(TimeInForce, evt.time_in_force, TimeInForce.GTC),
        order_type=_coerce(OrderType, evt.order_type, OrderType.LIMIT),
        side=_coerce(OrderSide, evt.side, OrderSide.BUY),
        stop_price=evt.stop_price,
        time=evt.order_creation_time if evt.order_creation_time is not None else evt.event_time,
        update_time=evt.transaction_time if evt.transaction_time is not None else evt.event_time,
        is_working=evt.is_on_book if evt.is_on_book is not None else is_active,
        orig_quote_order_qty=evt.quote_order_qty
        if evt.quote_order_qty is not None
        else Decimal("0"),
    )
