"""Abstract base class for trading strategies."""

from abc import ABC, abstractmethod
from typing import List, Optional

from src.exchange.base import Fill, Order


class BaseStrategy(ABC):

    @abstractmethod
    def build_grid(self) -> list:
        """Initialize the strategy's grid/structure."""

    @abstractmethod
    def on_price_update(self, current_price: float) -> List[Order]:
        """Called on each price tick. Returns orders to place."""

    @abstractmethod
    def on_order_filled(self, fill: Fill) -> Optional[Order]:
        """Called when an order is filled. Returns the counter-order to place, if any."""

    @abstractmethod
    def should_stop(self, current_price: float) -> bool:
        """Returns True when the strategy determines trading should halt."""

    @abstractmethod
    def get_initial_orders(self) -> List[Order]:
        """Returns the initial set of orders to place when the grid is first started."""
