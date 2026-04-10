"""Virtual portfolio for backtesting: tracks cash, holdings, and equity."""

from dataclasses import dataclass, field
from typing import List

import pandas as pd

from src.exchange.base import Fill


@dataclass
class PortfolioState:
    cash: float
    holdings: float      # Base asset quantity (e.g., BTC)
    avg_entry_price: float = 0.0
    total_fees: float = 0.0


class Portfolio:
    """
    Simulates account state during backtesting.
    Tracks cash (quote currency) and holdings (base currency).
    """

    def __init__(self, initial_capital: float, symbol: str) -> None:
        self._initial_capital = initial_capital
        self._symbol = symbol
        self._cash = initial_capital
        self._holdings = 0.0
        self._avg_entry_price = 0.0
        self._total_fees = 0.0
        self._equity_history: List[dict] = []

    def apply_fill(self, fill: Fill, current_price: float) -> None:
        """Update portfolio state based on a fill event."""
        cost = fill.price * fill.quantity

        if fill.side == "buy":
            total_cost = self._avg_entry_price * self._holdings + fill.price * fill.quantity
            self._holdings += fill.quantity
            self._avg_entry_price = total_cost / self._holdings if self._holdings > 0 else 0
            self._cash -= cost + fill.fee
        else:  # sell
            self._cash += cost - fill.fee
            self._holdings -= fill.quantity
            if self._holdings <= 0:
                self._holdings = 0.0
                self._avg_entry_price = 0.0

        self._total_fees += fill.fee

    def record_equity(self, timestamp, current_price: float) -> float:
        """Record equity snapshot and return current equity value."""
        equity = self._cash + self._holdings * current_price
        self._equity_history.append({"timestamp": timestamp, "equity": equity})
        return equity

    def get_equity_curve(self) -> pd.Series:
        if not self._equity_history:
            return pd.Series(dtype=float)
        df = pd.DataFrame(self._equity_history)
        df = df.set_index("timestamp")
        return df["equity"]

    def get_state(self) -> PortfolioState:
        return PortfolioState(
            cash=self._cash,
            holdings=self._holdings,
            avg_entry_price=self._avg_entry_price,
            total_fees=self._total_fees,
        )

    def can_afford_buy(self, price: float, quantity: float, fee_rate: float = 0.001) -> bool:
        cost = price * quantity * (1 + fee_rate)
        return self._cash >= cost

    def has_enough_to_sell(self, quantity: float) -> bool:
        return self._holdings >= quantity

    @property
    def initial_capital(self) -> float:
        return self._initial_capital
