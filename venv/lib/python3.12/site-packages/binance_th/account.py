"""Signed account resource client (M3b).

Reads under ``client.account.*``. All Binance TH responses are bare; signed calls
pass ``signed=True``. ⚠ Signed response shapes are UNVERIFIED (no probe possible
without credentials) — the models are defensively reconciled and must be
confirmed against a credentialed soak.
"""

from collections.abc import AsyncIterator
from typing import Any

from binance_th.models.account import AccountInfo, TradeFee, UserTrade
from binance_th.pagination import iter_time_windows
from binance_th.transport import Transport

__all__ = ["AccountClient"]

_ACCOUNT_PATH = "/api/v1/accountV2"
_USER_TRADES_PATH = "/api/v1/userTrades"
_TRADE_FEE_PATH = "/api/v1/asset/tradeFee"


class AccountClient:
    """Signed account-data endpoints."""

    def __init__(self, transport: Transport) -> None:
        """Hold the shared transport owned by :class:`BinanceThClient`."""
        self._transport = transport

    async def account(self) -> AccountInfo:
        """``GET /api/v1/accountV2`` — account permissions and balances (signed)."""
        raw = await self._transport.request("GET", _ACCOUNT_PATH, signed=True, weight=10)
        return AccountInfo(**raw)

    async def trade_fees(self, *, symbol: str | None = None) -> list[TradeFee]:
        """``GET /api/v1/asset/tradeFee`` — maker/taker fees (⚠ list-vs-single unverified)."""
        params: dict[str, Any] = {}
        if symbol is not None:
            params["symbol"] = symbol
        raw = await self._transport.request(
            "GET", _TRADE_FEE_PATH, params=params, signed=True, weight=1
        )
        rows = raw if isinstance(raw, list) else [raw]
        return [TradeFee(**item) for item in rows]

    async def user_trades(
        self,
        symbol: str,
        *,
        limit: int | None = None,
        start_time: int | None = None,
        end_time: int | None = None,
    ) -> list[UserTrade]:
        """``GET /api/v1/userTrades`` — account trade history (signed)."""
        params: dict[str, Any] = {"symbol": symbol}
        if limit is not None:
            params["limit"] = limit
        if start_time is not None:
            params["startTime"] = start_time
        if end_time is not None:
            params["endTime"] = end_time
        raw = await self._transport.request(
            "GET", _USER_TRADES_PATH, params=params, signed=True, weight=10
        )
        return [UserTrade(**item) for item in raw]

    async def iter_user_trades(
        self,
        symbol: str,
        *,
        start_time: int,
        end_time: int,
        limit: int = 1000,
    ) -> AsyncIterator[UserTrade]:
        """Iterate user trades across ``[start_time, end_time)``, de-duping by id."""

        async def fetch(window_start: int, window_end: int) -> list[UserTrade]:
            return await self.user_trades(
                symbol, start_time=window_start, end_time=window_end, limit=limit
            )

        async for trade in iter_time_windows(
            fetch,
            start_time=start_time,
            end_time=end_time,
            page_limit=limit,
            window_key=lambda trade: trade.time,
            dedup_key=lambda trade: trade.id,
        ):
            yield trade
