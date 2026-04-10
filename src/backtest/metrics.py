"""Performance metrics calculation for backtesting results."""

import math
from dataclasses import dataclass
from typing import List

import numpy as np
import pandas as pd

from src.exchange.base import Fill


@dataclass
class PerformanceMetrics:
    total_pnl: float
    total_pnl_pct: float
    sharpe_ratio: float
    max_drawdown: float
    max_drawdown_duration: int     # In bars
    win_rate: float
    total_trades: int
    avg_profit_per_trade: float
    profit_factor: float
    calmar_ratio: float
    annualized_return: float

    def to_dict(self) -> dict:
        return {
            "total_pnl": round(self.total_pnl, 2),
            "total_pnl_pct": round(self.total_pnl_pct * 100, 2),
            "sharpe_ratio": round(self.sharpe_ratio, 3),
            "max_drawdown": round(self.max_drawdown * 100, 2),
            "max_drawdown_duration_bars": self.max_drawdown_duration,
            "win_rate": round(self.win_rate * 100, 2),
            "total_trades": self.total_trades,
            "avg_profit_per_trade": round(self.avg_profit_per_trade, 4),
            "profit_factor": round(self.profit_factor, 3),
            "calmar_ratio": round(self.calmar_ratio, 3),
            "annualized_return_pct": round(self.annualized_return * 100, 2),
        }


class MetricsCalculator:

    def compute(
        self,
        equity_curve: pd.Series,
        fills: List[Fill],
        initial_capital: float,
        bars_per_year: int = 8760,  # Hourly bars default
    ) -> PerformanceMetrics:

        if equity_curve.empty:
            return self._zero_metrics()

        final_equity = equity_curve.iloc[-1]
        total_pnl = final_equity - initial_capital
        total_pnl_pct = total_pnl / initial_capital

        # Annualized return
        n_bars = len(equity_curve)
        years = n_bars / bars_per_year
        annualized_return = (final_equity / initial_capital) ** (1 / years) - 1 if years > 0 else 0.0

        # Sharpe ratio (annualized, zero risk-free rate)
        returns = equity_curve.pct_change().dropna()
        if returns.std() > 0:
            sharpe = (returns.mean() / returns.std()) * math.sqrt(bars_per_year)
        else:
            sharpe = 0.0

        # Max drawdown
        rolling_max = equity_curve.cummax()
        drawdown_series = (equity_curve - rolling_max) / rolling_max
        max_drawdown = abs(drawdown_series.min())

        # Max drawdown duration
        in_drawdown = drawdown_series < 0
        max_dd_duration = 0
        current_duration = 0
        for flag in in_drawdown:
            if flag:
                current_duration += 1
                max_dd_duration = max(max_dd_duration, current_duration)
            else:
                current_duration = 0

        # Calmar ratio
        calmar = annualized_return / max_drawdown if max_drawdown > 0 else 0.0

        # Trade metrics from fills (pair buys with sells as round trips)
        buy_fills = [f for f in fills if f.side == "buy"]
        sell_fills = [f for f in fills if f.side == "sell"]
        total_trades = len(fills)

        profits = [f.price * f.quantity - f.fee for f in sell_fills]
        costs = [f.price * f.quantity + f.fee for f in buy_fills]

        gross_profit = sum(p for p in profits if p > 0)
        gross_loss = abs(sum(p for p in profits if p < 0))

        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")
        win_rate = len([p for p in profits if p > 0]) / len(profits) if profits else 0.0
        avg_profit = (gross_profit - gross_loss) / len(profits) if profits else 0.0

        return PerformanceMetrics(
            total_pnl=total_pnl,
            total_pnl_pct=total_pnl_pct,
            sharpe_ratio=sharpe,
            max_drawdown=max_drawdown,
            max_drawdown_duration=max_dd_duration,
            win_rate=win_rate,
            total_trades=total_trades,
            avg_profit_per_trade=avg_profit,
            profit_factor=profit_factor,
            calmar_ratio=calmar,
            annualized_return=annualized_return,
        )

    def _zero_metrics(self) -> PerformanceMetrics:
        return PerformanceMetrics(
            total_pnl=0, total_pnl_pct=0, sharpe_ratio=0,
            max_drawdown=0, max_drawdown_duration=0, win_rate=0,
            total_trades=0, avg_profit_per_trade=0, profit_factor=0,
            calmar_ratio=0, annualized_return=0,
        )
