"""Account and wallet models for Binance Thailand API.

This module defines Pydantic models for account information,
balances, deposits, withdrawals, and user data.
"""

from decimal import Decimal

from pydantic import Field

from binance_th.models.base import ResponseModel
from binance_th.models.enums import SymbolType


class Balance(ResponseModel):
    """Account balance for a single asset.

    Part of AccountInfo response.
    """

    asset: str = Field(description="Asset symbol (e.g., BTC, USDT)")
    free: Decimal = Field(description="Available balance")
    locked: Decimal = Field(description="Locked in orders")

    @property
    def total(self) -> Decimal:
        """Total balance (free + locked)."""
        return self.free + self.locked


class AccountInfo(ResponseModel):
    """Account information response.

    Response from GET /api/v1/accountV2
    Contains account permissions and all asset balances.
    """

    maker_commission: int = Field(
        alias="makerCommission",
        description="Maker commission rate (basis points)",
    )
    taker_commission: int = Field(
        alias="takerCommission",
        description="Taker commission rate (basis points)",
    )
    buyer_commission: int = Field(
        alias="buyerCommission",
        description="Buyer commission rate",
    )
    seller_commission: int = Field(
        alias="sellerCommission",
        description="Seller commission rate",
    )
    can_trade: bool = Field(alias="canTrade", description="Trading allowed")
    can_withdraw: bool = Field(alias="canWithdraw", description="Withdrawals allowed")
    can_deposit: bool = Field(alias="canDeposit", description="Deposits allowed")
    update_time: int = Field(alias="updateTime", description="Last update timestamp")
    balances: list[Balance] = Field(description="All asset balances")

    def get_balance(self, asset: str) -> Balance | None:
        """Get balance for a specific asset.

        Args:
            asset: Asset symbol (e.g., "BTC")

        Returns:
            Balance or None if not found
        """
        for balance in self.balances:
            if balance.asset == asset:
                return balance
        return None

    def get_non_zero_balances(self) -> list[Balance]:
        """Get balances with non-zero total.

        Returns:
            List of balances where total > 0
        """
        return [b for b in self.balances if b.total > 0]


class UserTrade(ResponseModel):
    """User trade history record.

    Response from GET /api/v1/userTrades
    """

    symbol: str = Field(description="Trading pair symbol")
    id: int = Field(description="Trade ID")
    order_id: int = Field(alias="orderId", description="Order ID")
    price: Decimal = Field(description="Trade price")
    qty: Decimal = Field(description="Trade quantity")
    quote_qty: Decimal | None = Field(
        default=None,
        alias="quoteQty",
        description="Quote quantity (⚠ may be null on SITE; unverified)",
    )
    commission: Decimal = Field(description="Commission amount")
    commission_asset: str = Field(alias="commissionAsset", description="Commission asset")
    time: int = Field(description="Trade timestamp in milliseconds")
    is_buyer: bool = Field(alias="isBuyer", description="True if buyer")
    is_maker: bool = Field(alias="isMaker", description="True if maker")
    is_best_match: bool = Field(alias="isBestMatch", description="Best match")


class TradeFee(ResponseModel):
    """Trade fee information.

    Response from GET /api/v1/asset/tradeFee
    """

    symbol: str = Field(description="Trading pair symbol")
    maker_commission: Decimal = Field(
        alias="makerCommission",
        description="Maker fee rate",
    )
    taker_commission: Decimal = Field(
        alias="takerCommission",
        description="Taker fee rate",
    )


class DepositAddress(ResponseModel):
    """Deposit address information.

    Response from GET /api/v1/capital/deposit/address
    """

    address: str = Field(description="Deposit address")
    coin: str = Field(description="Coin symbol")
    tag: str | None = Field(
        default=None, description="Address tag (memo); absent for non-memo coins"
    )
    url: str | None = Field(default=None, description="Blockchain explorer URL (⚠ unverified)")


class DepositRecord(ResponseModel):
    """Deposit history record.

    Response from GET /api/v1/capital/deposit/history
    """

    amount: Decimal = Field(description="Deposit amount")
    coin: str = Field(description="Coin symbol")
    network: str = Field(description="Blockchain network")
    status: int = Field(description="Deposit status code (compare to DepositStatus)")
    address: str = Field(description="Deposit address")
    address_tag: str | None = Field(
        default=None, alias="addressTag", description="Address tag if any"
    )
    tx_id: str | None = Field(
        default=None, alias="txId", description="Transaction ID (absent while pending)"
    )
    insert_time: int = Field(alias="insertTime", description="Deposit request time")
    transfer_type: int = Field(alias="transferType", description="Transfer type")
    confirm_times: str = Field(alias="confirmTimes", description="Confirmation count")


class WithdrawResult(ResponseModel):
    """Withdrawal request result.

    Response from POST /api/v1/capital/withdraw
    """

    id: str = Field(description="Withdrawal ID")


class WithdrawRecord(ResponseModel):
    """Withdrawal history record.

    Response from GET /api/v1/capital/withdraw/history
    """

    address: str = Field(description="Withdrawal address")
    amount: Decimal = Field(description="Withdrawal amount")
    apply_time: str = Field(alias="applyTime", description="Application time")
    coin: str = Field(description="Coin symbol")
    id: str = Field(description="Withdrawal ID")
    withdraw_order_id: str | None = Field(
        default=None,
        alias="withdrawOrderId",
        description="Custom withdrawal order ID",
    )
    network: str = Field(description="Blockchain network")
    transfer_type: int = Field(alias="transferType", description="Transfer type")
    status: int = Field(description="Withdrawal status code (compare to WithdrawStatus)")
    transaction_fee: Decimal = Field(alias="transactionFee", description="Transaction fee")
    tx_id: str | None = Field(
        default=None, alias="txId", description="Transaction ID (absent while processing)"
    )


class SubAccountTransfer(ResponseModel):
    """Sub-account transfer result.

    Response from POST /api/v1/subaccount/transfer
    """

    tx_id: int = Field(alias="txnId", description="Transaction ID")


class ListenKey(ResponseModel):
    """Listen key for user data stream.

    Response from POST /api/v1/listenKey
    Used to connect to WebSocket user data streams.
    """

    listen_key: str = Field(alias="listenKey", description="Listen key for WebSocket")
    symbol_type: SymbolType = Field(
        alias="type",
        description="Symbol type (GLOBAL or SITE)",
    )
