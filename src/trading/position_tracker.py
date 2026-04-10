"""Real-time position tracking for live trading."""

from dataclasses import dataclass

from src.exchange.base import Fill


@dataclass
class Position:
    symbol: str
    quantity: float = 0.0
    avg_entry_price: float = 0.0
    realized_pnl: float = 0.0
    total_fees: float = 0.0

    @property
    def cost_basis(self) -> float:
        return self.quantity * self.avg_entry_price

    def unrealized_pnl(self, current_price: float) -> float:
        return (current_price - self.avg_entry_price) * self.quantity


class PositionTracker:
    """Maintains real-time position state updated on each fill."""

    def __init__(self, symbol: str) -> None:
        self._position = Position(symbol=symbol)

    def apply_fill(self, fill: Fill) -> None:
        pos = self._position
        pos.total_fees += fill.fee

        if fill.side == "buy":
            total_cost = pos.avg_entry_price * pos.quantity + fill.price * fill.quantity
            pos.quantity += fill.quantity
            pos.avg_entry_price = total_cost / pos.quantity if pos.quantity > 0 else 0.0
        else:
            if pos.quantity > 0:
                realized = (fill.price - pos.avg_entry_price) * fill.quantity - fill.fee
                pos.realized_pnl += realized
            pos.quantity -= fill.quantity
            if pos.quantity <= 1e-10:
                pos.quantity = 0.0
                pos.avg_entry_price = 0.0

    def get_position(self) -> Position:
        return self._position

    def get_unrealized_pnl(self, current_price: float) -> float:
        return self._position.unrealized_pnl(current_price)

    def get_total_pnl(self, current_price: float) -> float:
        return self._position.realized_pnl + self.get_unrealized_pnl(current_price)
