"""Risk management: pre-trade and post-fill risk gate."""

from dataclasses import dataclass
from typing import Optional

import pandas as pd
from loguru import logger

from src.backtest.portfolio import PortfolioState
from src.core.config import RiskConfig
from src.exchange.base import Fill, Order


@dataclass
class RiskDecision:
    approved: bool
    reason: Optional[str] = None
    suggested_action: Optional[str] = None   # HALT | REDUCE_SIZE | CANCEL_ALL


class RiskManager:
    """
    Stateless risk gate called before every order placement and after every fill.
    Returns RiskDecision — never places or cancels orders itself.
    """

    def __init__(self, config: RiskConfig) -> None:
        self._config = config
        self._daily_pnl: float = 0.0
        self._session_start_equity: Optional[float] = None
        self._peak_equity: float = 0.0

    def set_session_start_equity(self, equity: float) -> None:
        self._session_start_equity = equity
        self._peak_equity = equity

    def check_pre_trade(self, order: Order, state: PortfolioState) -> RiskDecision:
        """Gate check before placing an order."""
        total_value = state.cash + state.holdings * (state.avg_entry_price or 1.0)

        # Check max open position percentage
        if order.side == "buy":
            order_value = order.price * order.quantity
            if total_value > 0:
                position_pct = (state.holdings * order.price + order_value) / total_value
                if position_pct > self._config.max_position_pct:
                    return RiskDecision(
                        approved=False,
                        reason=f"Position would exceed {self._config.max_position_pct*100:.0f}% of capital",
                        suggested_action="REDUCE_SIZE",
                    )

        # Check sufficient cash for buy
        if order.side == "buy":
            required = order.price * order.quantity * 1.002  # include fee buffer
            if state.cash < required:
                return RiskDecision(
                    approved=False,
                    reason=f"Insufficient cash: need {required:.2f}, have {state.cash:.2f}",
                )

        # Check sufficient holdings for sell
        if order.side == "sell" and state.holdings < order.quantity:
            return RiskDecision(
                approved=False,
                reason=f"Insufficient holdings: need {order.quantity}, have {state.holdings}",
            )

        # Check daily loss limit
        if self._daily_pnl <= -self._config.daily_loss_limit:
            return RiskDecision(
                approved=False,
                reason=f"Daily loss limit reached: {self._daily_pnl:.2f}",
                suggested_action="HALT",
            )

        return RiskDecision(approved=True)

    def check_post_fill(self, fill: Fill, state: PortfolioState) -> RiskDecision:
        """Gate check after a fill is applied to portfolio."""
        # Update daily PnL tracking
        if fill.side == "sell":
            realized = (fill.price - state.avg_entry_price) * fill.quantity if state.avg_entry_price else 0
            self._daily_pnl += realized - fill.fee

        current_equity = state.cash + state.holdings * (fill.price)

        # Update peak for drawdown tracking
        if current_equity > self._peak_equity:
            self._peak_equity = current_equity

        # Check max drawdown
        if self._peak_equity > 0:
            drawdown = (self._peak_equity - current_equity) / self._peak_equity
            if drawdown >= self._config.max_drawdown_pct:
                logger.warning(
                    f"Max drawdown triggered: {drawdown*100:.1f}% >= {self._config.max_drawdown_pct*100:.0f}%"
                )
                return RiskDecision(
                    approved=False,
                    reason=f"Max drawdown {drawdown*100:.1f}% exceeded limit",
                    suggested_action="HALT",
                )

        # Check stop-loss on average entry
        if state.avg_entry_price > 0 and fill.side == "buy":
            loss_pct = (state.avg_entry_price - fill.price) / state.avg_entry_price
            if loss_pct >= self._config.stop_loss_pct:
                logger.warning(f"Stop-loss triggered: {loss_pct*100:.1f}% below entry")
                return RiskDecision(
                    approved=False,
                    reason=f"Stop-loss triggered at {loss_pct*100:.1f}% loss",
                    suggested_action="CANCEL_ALL",
                )

        return RiskDecision(approved=True)

    def check_daily_loss(self) -> bool:
        """Returns True if still within daily loss limits."""
        return self._daily_pnl > -self._config.daily_loss_limit

    def reset_daily_pnl(self) -> None:
        self._daily_pnl = 0.0

    def check_equity_curve(self, equity_curve: pd.Series) -> RiskDecision:
        """Check max drawdown on a full equity curve (used in backtesting)."""
        if equity_curve.empty:
            return RiskDecision(approved=True)
        rolling_max = equity_curve.cummax()
        drawdown = ((equity_curve - rolling_max) / rolling_max).min()
        if abs(drawdown) >= self._config.max_drawdown_pct:
            return RiskDecision(
                approved=False,
                reason=f"Equity curve max drawdown {abs(drawdown)*100:.1f}% exceeded limit",
                suggested_action="HALT",
            )
        return RiskDecision(approved=True)

    def get_max_order_size(self, price: float, available_cash: float) -> float:
        """Return maximum quantity that can be purchased given risk limits."""
        max_spend = available_cash * self._config.max_position_pct
        return max_spend / price if price > 0 else 0.0
