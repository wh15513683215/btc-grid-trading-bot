"""Grid trading strategy implementation."""

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from loguru import logger

from src.core.config import GridConfig
from src.core.exceptions import GridOutOfRangeError, StrategyError
from src.exchange.base import Fill, Order
from src.strategy.base import BaseStrategy

_ORDER_ID_COUNTER = 0


def _next_local_id() -> str:
    """Generate local temporary order IDs for backtest use."""
    global _ORDER_ID_COUNTER
    _ORDER_ID_COUNTER += 1
    return f"local_{_ORDER_ID_COUNTER}"


@dataclass
class GridLevel:
    price: float
    side: str          # "buy" | "sell"
    quantity: float
    order_id: Optional[str] = None
    status: str = "pending"   # pending | open | filled | cancelled


class GridStrategy(BaseStrategy):
    """
    Grid trading strategy that places buy and sell orders at regular price intervals.

    When a buy order fills, a sell order is placed one grid level above.
    When a sell order fills, a buy order is placed one grid level below.
    """

    def __init__(self, config: GridConfig) -> None:
        self._config = config
        self._levels: List[GridLevel] = []
        # Map order_id → GridLevel for O(1) fill lookup
        self._order_map: Dict[str, GridLevel] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build_grid(self) -> List[GridLevel]:
        """Compute all grid price levels and create GridLevel objects."""
        prices = self._compute_grid_prices()
        self._levels = []

        for price in prices:
            qty = self._compute_order_quantity(price)
            level = GridLevel(price=price, side="buy", quantity=qty)
            self._levels.append(level)

        logger.info(
            f"Grid built: {len(self._levels)} levels "
            f"[{self._config.lower_price:.2f} – {self._config.upper_price:.2f}] "
            f"type={self._config.grid_type}"
        )
        return self._levels

    def get_initial_orders(self) -> List[Order]:
        """
        Return buy orders for all grid levels below the current midpoint.
        The caller must fetch the current price first and pass it; for initial
        order generation we place buys at all levels.
        """
        if not self._levels:
            raise StrategyError("Call build_grid() before get_initial_orders()")

        orders = []
        for level in self._levels:
            order = Order(
                order_id=_next_local_id(),
                symbol=self._config.symbol,
                side=level.side,
                price=level.price,
                quantity=level.quantity,
                status="pending",
            )
            orders.append(order)
        return orders

    def on_price_update(self, current_price: float) -> List[Order]:
        """Check whether any pending levels need orders placed."""
        if not self._levels:
            return []

        if self.should_stop(current_price):
            logger.warning(f"Price {current_price} is outside grid range — strategy stopping")
            return []

        # No new orders to place on every tick in simple grid logic;
        # new orders arise from on_order_filled(). Return empty list.
        return []

    def on_order_filled(self, fill: Fill) -> Optional[Order]:
        """
        When a buy fills → place a sell one level up.
        When a sell fills → place a buy one level down.
        """
        level = self._order_map.get(fill.order_id)
        if level is None:
            logger.warning(f"Filled order {fill.order_id} not found in order map")
            return None

        level.status = "filled"
        logger.bind(trade=True).info(
            f"FILL | {fill.side.upper()} {fill.quantity} {fill.symbol} @ {fill.price:.4f}"
        )

        idx = self._find_level_index(level)
        if idx is None:
            return None

        if fill.side == "buy":
            # Place sell one level above
            counter_idx = idx + 1
            if counter_idx >= len(self._levels):
                logger.info("Buy filled at top of grid — no sell level above")
                return None
            counter_level = self._levels[counter_idx]
            counter_side = "sell"
        else:
            # Place buy one level below
            counter_idx = idx - 1
            if counter_idx < 0:
                logger.info("Sell filled at bottom of grid — no buy level below")
                return None
            counter_level = self._levels[counter_idx]
            counter_side = "buy"

        order = Order(
            order_id=_next_local_id(),
            symbol=self._config.symbol,
            side=counter_side,
            price=counter_level.price,
            quantity=counter_level.quantity,
            status="pending",
        )
        logger.bind(trade=True).info(
            f"COUNTER ORDER | {counter_side.upper()} {order.quantity} @ {order.price:.4f}"
        )
        return order

    def should_stop(self, current_price: float) -> bool:
        if not self._levels:
            return False
        stop_loss = self._config.stop_loss_price
        take_profit = self._config.take_profit_price

        if stop_loss and current_price <= stop_loss:
            return True
        if take_profit and current_price >= take_profit:
            return True
        return False

    def register_order(self, order: Order, level_price: float) -> None:
        """Associate a live order_id with its grid level (called after exchange confirms order)."""
        for level in self._levels:
            if abs(level.price - level_price) < 1e-8:
                level.order_id = order.order_id
                level.status = "open"
                self._order_map[order.order_id] = level
                return
        logger.warning(f"No grid level found for price {level_price}")

    def get_levels(self) -> List[GridLevel]:
        return list(self._levels)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _compute_grid_prices(self) -> List[float]:
        n = self._config.grid_count
        lo = self._config.lower_price
        hi = self._config.upper_price

        if self._config.grid_type == "arithmetic":
            step = (hi - lo) / (n - 1)
            prices = [lo + i * step for i in range(n)]
        else:  # geometric
            ratio = (hi / lo) ** (1 / (n - 1))
            prices = [lo * (ratio ** i) for i in range(n)]

        return [round(p, 8) for p in prices]

    def _compute_order_quantity(self, price: float) -> float:
        """Each grid level receives an equal share of the investment amount."""
        per_level = self._config.investment_amount / self._config.grid_count
        qty = per_level / price
        return round(qty, 8)

    def _find_level_index(self, target: GridLevel) -> Optional[int]:
        for i, level in enumerate(self._levels):
            if level is target:
                return i
        return None
