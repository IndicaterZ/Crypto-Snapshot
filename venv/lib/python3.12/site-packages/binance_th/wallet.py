"""Signed wallet/fiat resource client (M3b) — reads only.

Money-moving writes (``withdraw``, ``sub_account_transfer``) are deferred to a
later, carefully-gated milestone. All responses are bare; signed calls pass
``signed=True``. ⚠ Signed response shapes are UNVERIFIED — the models are
defensively reconciled and must be confirmed against a credentialed soak.

Note: ``WithdrawRecord`` exposes only a string ``applyTime`` (no integer
timestamp), so withdraw history is a single call — a time-window iterator is
deferred until the field's format is verified. Deposit history paginates on the
integer ``insertTime``.
"""

from collections.abc import AsyncIterator
from typing import Any

from binance_th.models.account import DepositAddress, DepositRecord, WithdrawRecord
from binance_th.pagination import iter_time_windows
from binance_th.transport import Transport

__all__ = ["WalletClient"]

_DEPOSIT_ADDRESS_PATH = "/api/v1/capital/deposit/address"
_DEPOSIT_HISTORY_PATH = "/api/v1/capital/deposit/history"
_WITHDRAW_HISTORY_PATH = "/api/v1/capital/withdraw/history"


def _history_params(
    coin: str | None, start_time: int | None, end_time: int | None, limit: int | None
) -> dict[str, Any]:
    """Build the common history query, omitting unset values."""
    params: dict[str, Any] = {}
    if coin is not None:
        params["coin"] = coin
    if start_time is not None:
        params["startTime"] = start_time
    if end_time is not None:
        params["endTime"] = end_time
    if limit is not None:
        params["limit"] = limit
    return params


class WalletClient:
    """Signed wallet/fiat read endpoints."""

    def __init__(self, transport: Transport) -> None:
        """Hold the shared transport owned by :class:`BinanceThClient`."""
        self._transport = transport

    async def deposit_address(self, coin: str, *, network: str | None = None) -> DepositAddress:
        """``GET /api/v1/capital/deposit/address`` — a deposit address (signed)."""
        params: dict[str, Any] = {"coin": coin}
        if network is not None:
            params["network"] = network
        raw = await self._transport.request(
            "GET", _DEPOSIT_ADDRESS_PATH, params=params, signed=True, weight=1
        )
        return DepositAddress(**raw)

    async def deposit_history(
        self,
        *,
        coin: str | None = None,
        start_time: int | None = None,
        end_time: int | None = None,
        limit: int | None = None,
    ) -> list[DepositRecord]:
        """``GET /api/v1/capital/deposit/history`` — deposit records (signed)."""
        raw = await self._transport.request(
            "GET",
            _DEPOSIT_HISTORY_PATH,
            params=_history_params(coin, start_time, end_time, limit),
            signed=True,
            weight=1,
        )
        return [DepositRecord(**item) for item in raw]

    async def withdraw_history(
        self,
        *,
        coin: str | None = None,
        start_time: int | None = None,
        end_time: int | None = None,
        limit: int | None = None,
    ) -> list[WithdrawRecord]:
        """``GET /api/v1/capital/withdraw/history`` — withdrawal records (signed)."""
        raw = await self._transport.request(
            "GET",
            _WITHDRAW_HISTORY_PATH,
            params=_history_params(coin, start_time, end_time, limit),
            signed=True,
            weight=1,
        )
        return [WithdrawRecord(**item) for item in raw]

    async def iter_deposit_history(
        self,
        *,
        coin: str | None = None,
        start_time: int,
        end_time: int,
        limit: int = 1000,
    ) -> AsyncIterator[DepositRecord]:
        """Iterate deposit history across ``[start_time, end_time)`` (best-effort txId dedup)."""

        async def fetch(window_start: int, window_end: int) -> list[DepositRecord]:
            return await self.deposit_history(
                coin=coin, start_time=window_start, end_time=window_end, limit=limit
            )

        async for record in iter_time_windows(
            fetch,
            start_time=start_time,
            end_time=end_time,
            page_limit=limit,
            window_key=lambda record: record.insert_time,
            dedup_key=lambda record: record.tx_id or record.insert_time,
        ):
            yield record
