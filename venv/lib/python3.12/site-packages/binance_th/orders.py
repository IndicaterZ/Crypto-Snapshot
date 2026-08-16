"""Signed order resource client (M4).

⚠ Order endpoints are SIGNED, move REAL money, and are UNVERIFIABLE / unsafe to
live-test — everything here is mock-tested and ASSUMED. Reconcile against a
credentialed, micro-order soak (under supervision) before trusting live placement.

``create_order`` performs, in order: client-order-id minting (ADR-0013, before the
send so the order is reconcilable), pre-trade validation/snapping (ADR-0009), the
signed POST, and — on a transient failure — UNKNOWN reconciliation by querying the
order by its client id (ADR-0006), never a blind resubmit.
"""

from collections.abc import Awaitable, Callable
from decimal import Decimal
from enum import Enum
from typing import Any

from binance_th.exceptions import (
    BinanceThAPIError,
    BinanceThAuthError,
    BinanceThError,
    BinanceThNetworkError,
    BinanceThOrderUnknownError,
    BinanceThServerError,
    BinanceThTimeoutError,
    BinanceThValidationError,
)
from binance_th.idempotency import mint_client_order_id
from binance_th.models.base import ExchangeInfo
from binance_th.models.enums import OrderSide, OrderType, TimeInForce
from binance_th.models.market import ExecutionRules
from binance_th.models.orders import CancelOrderRequest, Order, OrderRequest, QueryOrderRequest
from binance_th.transport import Transport
from binance_th.validation import validate_order

__all__ = ["OrdersClient"]

_ORDER_PATH = "/api/v1/order"
_OPEN_ORDERS_PATH = "/api/v1/openOrders"
_ORDER_NOT_FOUND_CODE = -2013

ExchangeInfoProvider = Callable[..., Awaitable[ExchangeInfo]]
ExecutionRulesProvider = Callable[[], Awaitable[ExecutionRules]]
_AnyOrderRequest = OrderRequest | CancelOrderRequest | QueryOrderRequest


def _to_param_str(value: Any) -> str:
    """Serialize a param value; Decimals as fixed-point (never ``3E-8``)."""
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, Enum):
        return str(value.value)
    return str(value)


def _params(request: _AnyOrderRequest) -> dict[str, str]:
    """Build the signed param dict from a request model (aliases, no None)."""
    return {
        alias: _to_param_str(value)
        for alias, value in request.model_dump(by_alias=True, exclude_none=True).items()
    }


class OrdersClient:
    """Signed order endpoints (create / cancel / query / openOrders)."""

    def __init__(
        self,
        transport: Transport,
        *,
        exchange_info: ExchangeInfoProvider,
        execution_rules: ExecutionRulesProvider | None = None,
        client_order_id_factory: Callable[[], str] = mint_client_order_id,
        use_execution_rules: bool = False,
    ) -> None:
        """Wire the client; ``exchange_info`` is the client's cached provider."""
        self._transport = transport
        self._exchange_info = exchange_info
        self._execution_rules = execution_rules
        self._mint_id = client_order_id_factory
        self._use_execution_rules = use_execution_rules

    async def create_order(
        self,
        symbol: str | None = None,
        side: OrderSide | str | None = None,
        order_type: OrderType | str | None = None,
        *,
        request: OrderRequest | None = None,
        quantity: Decimal | None = None,
        price: Decimal | None = None,
        time_in_force: TimeInForce | str | None = None,
        quote_order_qty: Decimal | None = None,
        stop_price: Decimal | None = None,
        new_client_order_id: str | None = None,
        recv_window: int | None = None,
        validate: bool = True,
    ) -> Order:
        """Place an order (kwargs build an ``OrderRequest``, or pass ``request=``)."""
        order = self._resolve_request(
            request,
            symbol,
            side,
            order_type,
            quantity,
            price,
            time_in_force,
            quote_order_qty,
            stop_price,
            new_client_order_id,
            recv_window,
        )
        if not self._transport.can_sign:
            raise BinanceThAuthError("API credentials are required for signed endpoints")

        client_order_id = order.new_client_order_id or self._mint_id()
        if order.new_client_order_id is None:  # mint BEFORE send so the order is reconcilable
            order = order.model_copy(update={"new_client_order_id": client_order_id})

        if validate:
            order = await self._validate(order)

        try:
            raw = await self._transport.request(
                "POST",
                _ORDER_PATH,
                params=_params(order),
                signed=True,
                mutating=True,
                envelope=False,
                weight=1,
            )
            return Order(**raw)
        except (BinanceThServerError, BinanceThTimeoutError, BinanceThNetworkError) as unknown:
            return await self._reconcile(order.symbol, client_order_id, unknown)

    async def cancel_order(
        self,
        symbol: str,
        *,
        order_id: int | None = None,
        orig_client_order_id: str | None = None,
        recv_window: int | None = None,
    ) -> Order:
        """Cancel an order by id or client id (``DELETE /api/v1/order``)."""
        request = CancelOrderRequest(
            symbol=symbol,
            order_id=order_id,
            orig_client_order_id=orig_client_order_id,
            recv_window=recv_window,
        )
        raw = await self._transport.request(
            "DELETE",
            _ORDER_PATH,
            params=_params(request),
            signed=True,
            mutating=True,
            envelope=False,
            weight=1,
        )
        return Order(**raw)

    async def query_order(
        self,
        symbol: str,
        *,
        order_id: int | None = None,
        orig_client_order_id: str | None = None,
        recv_window: int | None = None,
    ) -> Order:
        """Query an order by id or client id (``GET /api/v1/order``)."""
        request = QueryOrderRequest(
            symbol=symbol,
            order_id=order_id,
            orig_client_order_id=orig_client_order_id,
            recv_window=recv_window,
        )
        raw = await self._transport.request(
            "GET", _ORDER_PATH, params=_params(request), signed=True, weight=2
        )
        return Order(**raw)

    async def open_orders(self, symbol: str | None = None) -> list[Order]:
        """Open orders for a symbol, or all symbols (``GET /api/v1/openOrders``)."""
        params = {"symbol": symbol} if symbol is not None else {}
        raw = await self._transport.request(
            "GET", _OPEN_ORDERS_PATH, params=params, signed=True, weight=3 if symbol else 40
        )
        return [Order(**item) for item in raw]

    def _resolve_request(
        self,
        request: OrderRequest | None,
        symbol: str | None,
        side: OrderSide | str | None,
        order_type: OrderType | str | None,
        quantity: Decimal | None,
        price: Decimal | None,
        time_in_force: TimeInForce | str | None,
        quote_order_qty: Decimal | None,
        stop_price: Decimal | None,
        new_client_order_id: str | None,
        recv_window: int | None,
    ) -> OrderRequest:
        """Resolve request-xor-kwargs into a single validated ``OrderRequest``."""
        kwargs = (
            symbol,
            side,
            order_type,
            quantity,
            price,
            time_in_force,
            quote_order_qty,
            stop_price,
            new_client_order_id,
            recv_window,
        )
        if request is not None:
            if any(value is not None for value in kwargs):
                raise ValueError("pass either request= or keyword params, not both")
            return request
        if symbol is None or side is None or order_type is None:
            raise ValueError("symbol, side, and order_type are required when request= is omitted")
        return OrderRequest(
            symbol=symbol,
            side=OrderSide(side),
            order_type=OrderType(order_type),
            quantity=quantity,
            price=price,
            time_in_force=TimeInForce(time_in_force) if time_in_force is not None else None,
            quote_order_qty=quote_order_qty,
            stop_price=stop_price,
            new_client_order_id=new_client_order_id,
            recv_window=recv_window,
        )

    async def _validate(self, order: OrderRequest) -> OrderRequest:
        info = await self._exchange_info()
        symbol_info = info.get_symbol(order.symbol)
        if symbol_info is None:  # cache may be stale — refresh once
            info = await self._exchange_info(force=True)
            symbol_info = info.get_symbol(order.symbol)
        if symbol_info is None:
            raise BinanceThValidationError("unknown symbol", field="symbol", value=order.symbol)
        exec_rules = None
        if self._use_execution_rules and self._execution_rules is not None:
            exec_rules = (await self._execution_rules()).get_symbol(order.symbol)
        return validate_order(order, symbol_info, execution_rules=exec_rules)

    async def _reconcile(self, symbol: str, client_order_id: str, cause: BinanceThError) -> Order:
        """Query by client id after a transient create failure; never resubmit."""
        try:
            return await self.query_order(symbol, orig_client_order_id=client_order_id)
        except BinanceThAPIError as query_error:
            if query_error.code == _ORDER_NOT_FOUND_CODE:
                raise BinanceThOrderUnknownError(
                    "order was not placed; safe to resubmit",
                    client_order_id=client_order_id,
                    symbol=symbol,
                    resubmittable=True,
                ) from cause
            raise BinanceThOrderUnknownError(
                "order status unknown; reconciliation query failed",
                client_order_id=client_order_id,
                symbol=symbol,
                resubmittable=False,
            ) from query_error
