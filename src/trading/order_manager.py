"""Order state machine for live trading."""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from loguru import logger

from src.exchange.base import Fill, Order


class OrderManager:
    """
    Tracks all open, filled, and cancelled orders during a live trading session.
    Acts as an in-memory order book mirror.
    """

    def __init__(self) -> None:
        self._open: Dict[str, Order] = {}
        self._filled: Dict[str, Fill] = {}
        self._cancelled: List[str] = []

    def register(self, order: Order) -> None:
        """Register a newly placed order as open."""
        self._open[order.order_id] = order
        logger.debug(f"Order registered: {order.order_id} {order.side} {order.quantity} @ {order.price}")

    def mark_filled(self, fill: Fill) -> Optional[Order]:
        """Mark an order as filled. Returns the original Order if found."""
        order = self._open.pop(fill.order_id, None)
        if order:
            order.status = "filled"
            order.filled_qty = fill.quantity
            self._filled[fill.order_id] = fill
            logger.bind(trade=True).info(
                f"ORDER FILLED | {fill.order_id} | {fill.side} {fill.quantity} @ {fill.price:.4f} | fee={fill.fee:.4f}"
            )
        else:
            logger.warning(f"Fill received for unknown order: {fill.order_id}")
        return order

    def mark_cancelled(self, order_id: str) -> bool:
        order = self._open.pop(order_id, None)
        if order:
            order.status = "cancelled"
            self._cancelled.append(order_id)
            return True
        return False

    def get_open_orders(self) -> List[Order]:
        return list(self._open.values())

    def get_filled_orders(self) -> List[Fill]:
        return list(self._filled.values())

    def is_open(self, order_id: str) -> bool:
        return order_id in self._open

    def open_count(self) -> int:
        return len(self._open)

    def clear(self) -> None:
        self._open.clear()
