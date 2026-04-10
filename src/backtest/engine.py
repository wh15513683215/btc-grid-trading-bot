"""Event-driven backtesting engine."""

import time
from dataclasses import dataclass, field
from typing import List, Optional

import pandas as pd
from loguru import logger

from src.backtest.metrics import MetricsCalculator, PerformanceMetrics
from src.backtest.portfolio import Portfolio
from src.exchange.base import Fill, Order
from src.risk.manager import RiskManager
from src.strategy.grid import GridStrategy


@dataclass
class BacktestResult:
    fills: List[Fill]
    equity_curve: pd.Series
    metrics: PerformanceMetrics
    initial_capital: float
    final_equity: float


class BacktestEngine:
    """
    Replays historical OHLCV bars and simulates grid strategy execution.

    Each bar: strategy is checked for new orders → risk gate → simulated fill.
    Fill → counter-order logic → repeat.
    """

    def __init__(
        self,
        strategy: GridStrategy,
        portfolio: Portfolio,
        risk_manager: RiskManager,
        commission_rate: float = 0.001,
        slippage_pct: float = 0.0005,
    ) -> None:
        self._strategy = strategy
        self._portfolio = portfolio
        self._risk_manager = risk_manager
        self._commission_rate = commission_rate
        self._slippage_pct = slippage_pct
        self._fills: List[Fill] = []
        self._pending_orders: List[Order] = []

    def run(
        self,
        ohlcv: pd.DataFrame,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> BacktestResult:
        """Run backtest over the provided OHLCV DataFrame."""
        df = ohlcv.copy()

        if start_date:
            df = df[df["timestamp"] >= pd.Timestamp(start_date)]
        if end_date:
            df = df[df["timestamp"] <= pd.Timestamp(end_date)]

        df = df.reset_index(drop=True)

        if df.empty:
            raise ValueError("No data in the requested date range")

        logger.info(f"Backtest start | {len(df)} bars | capital={self._portfolio.initial_capital}")

        # Initialize grid
        self._strategy.build_grid()
        initial_orders = self._strategy.get_initial_orders()

        # Queue only buy orders below the first bar's open price
        first_price = df.iloc[0]["open"]
        for order in initial_orders:
            if order.side == "buy" and order.price < first_price:
                state = self._portfolio.get_state()
                decision = self._risk_manager.check_pre_trade(order, state)
                if decision.approved:
                    self._pending_orders.append(order)
                    self._strategy.register_order(order, order.price)

        # Main bar loop
        for _, bar in df.iterrows():
            self._process_bar(bar)

        equity_curve = self._portfolio.get_equity_curve()
        calculator = MetricsCalculator()
        metrics = calculator.compute(
            equity_curve=equity_curve,
            fills=self._fills,
            initial_capital=self._portfolio.initial_capital,
        )

        final_equity = equity_curve.iloc[-1] if not equity_curve.empty else self._portfolio.initial_capital

        logger.info(
            f"Backtest complete | trades={len(self._fills)} | "
            f"PnL={metrics.total_pnl:.2f} ({metrics.total_pnl_pct*100:.1f}%) | "
            f"Sharpe={metrics.sharpe_ratio:.2f} | MaxDD={metrics.max_drawdown*100:.1f}%"
        )

        return BacktestResult(
            fills=self._fills,
            equity_curve=equity_curve,
            metrics=metrics,
            initial_capital=self._portfolio.initial_capital,
            final_equity=final_equity,
        )

    def _process_bar(self, bar: pd.Series) -> None:
        """Simulate one OHLCV bar: check for fills, record equity."""
        timestamp = bar["timestamp"]
        open_p = bar["open"]
        high_p = bar["high"]
        low_p = bar["low"]
        close_p = bar["close"]

        # Check pending orders for simulated fills
        filled = []
        remaining = []
        for order in self._pending_orders:
            fill = self._simulate_fill(order, low_p, high_p)
            if fill:
                filled.append((order, fill))
            else:
                remaining.append(order)

        self._pending_orders = remaining

        for order, fill in filled:
            self._portfolio.apply_fill(fill, close_p)
            self._fills.append(fill)

            # Risk check after fill
            state = self._portfolio.get_state()
            post_decision = self._risk_manager.check_post_fill(fill, state)
            if not post_decision.approved:
                logger.warning(f"Risk halt after fill: {post_decision.reason}")
                self._pending_orders.clear()
                return

            # Strategy counter-order
            counter = self._strategy.on_order_filled(fill)
            if counter:
                pre_decision = self._risk_manager.check_pre_trade(counter, state)
                if pre_decision.approved:
                    self._pending_orders.append(counter)
                    self._strategy.register_order(counter, counter.price)

        self._portfolio.record_equity(timestamp, close_p)

    def _simulate_fill(self, order: Order, low_p: float, high_p: float) -> Optional[Fill]:
        """
        Simulate limit order fill: fill if bar range crosses order price.
        Apply slippage and commission.
        """
        if order.side == "buy" and low_p <= order.price:
            fill_price = self._apply_slippage(order.price, "buy")
            if not self._portfolio.can_afford_buy(fill_price, order.quantity, self._commission_rate):
                return None
            fee = fill_price * order.quantity * self._commission_rate
            return Fill(
                order_id=order.order_id,
                symbol=order.symbol,
                side="buy",
                price=fill_price,
                quantity=order.quantity,
                fee=fee,
                timestamp=int(time.time() * 1000),
            )
        elif order.side == "sell" and high_p >= order.price:
            if not self._portfolio.has_enough_to_sell(order.quantity):
                return None
            fill_price = self._apply_slippage(order.price, "sell")
            fee = fill_price * order.quantity * self._commission_rate
            return Fill(
                order_id=order.order_id,
                symbol=order.symbol,
                side="sell",
                price=fill_price,
                quantity=order.quantity,
                fee=fee,
                timestamp=int(time.time() * 1000),
            )
        return None

    def _apply_slippage(self, price: float, side: str) -> float:
        if side == "buy":
            return price * (1 + self._slippage_pct)
        else:
            return price * (1 - self._slippage_pct)
