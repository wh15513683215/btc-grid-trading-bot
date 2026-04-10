"""Abstract base class for exchange integrations."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Callable, List, Optional


@dataclass
class Order:
    order_id: str
    symbol: str
    side: str        # "buy" | "sell"
    price: float
    quantity: float
    status: str      # "open" | "filled" | "cancelled" | "partial"
    filled_qty: float = 0.0
    timestamp: Optional[int] = None  # Unix ms


@dataclass
class Fill:
    order_id: str
    symbol: str
    side: str
    price: float
    quantity: float
    fee: float
    timestamp: int   # Unix ms


@dataclass
class Ticker:
    symbol: str
    last: float
    bid: float
    ask: float
    timestamp: int   # Unix ms


@dataclass
class Balance:
    currency: str
    free: float
    used: float
    total: float


class BaseExchange(ABC):

    @abstractmethod
    async def place_limit_order(
        self, symbol: str, side: str, price: float, quantity: float
    ) -> Order:
        """Place a limit order and return the resulting Order object."""

    @abstractmethod
    async def cancel_order(self, order_id: str, symbol: str) -> bool:
        """Cancel an order. Returns True if successfully cancelled."""

    @abstractmethod
    async def get_open_orders(self, symbol: str) -> List[Order]:
        """Return all currently open orders for the symbol."""

    @abstractmethod
    async def get_order_status(self, order_id: str, symbol: str) -> Order:
        """Fetch the current status of a specific order."""

    @abstractmethod
    async def get_balance(self) -> dict:
        """Return balances as {currency: Balance}."""

    @abstractmethod
    async def get_ticker(self, symbol: str) -> Ticker:
        """Return the current ticker (price, bid, ask)."""

    @abstractmethod
    async def cancel_all_orders(self, symbol: str) -> int:
        """Cancel all open orders for the symbol. Returns count cancelled."""

    @abstractmethod
    async def subscribe_ticker(self, symbol: str, callback: Callable[[Ticker], None]) -> None:
        """Subscribe to real-time ticker updates via WebSocket."""

    @abstractmethod
    async def subscribe_order_updates(self, callback: Callable[[Fill], None]) -> None:
        """Subscribe to order fill events via WebSocket."""

    @abstractmethod
    async def close(self) -> None:
        """Clean up connections."""
