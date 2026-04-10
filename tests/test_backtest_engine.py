"""Tests for BacktestEngine using synthetic OHLCV data."""

import pandas as pd
import pytest

from src.backtest.engine import BacktestEngine
from src.backtest.portfolio import Portfolio
from src.core.config import GridConfig, RiskConfig
from src.risk.manager import RiskManager
from src.strategy.grid import GridStrategy


def make_ohlcv(n_bars: int = 100, base_price: float = 65000.0) -> pd.DataFrame:
    """Generate synthetic OHLCV data with mild oscillation."""
    import numpy as np
    rng = np.random.default_rng(42)
    prices = base_price + rng.normal(0, 500, n_bars).cumsum()
    prices = np.maximum(prices, base_price * 0.8)

    timestamps = pd.date_range("2024-01-01", periods=n_bars, freq="1h")
    rows = []
    for i, (ts, p) in enumerate(zip(timestamps, prices)):
        noise = rng.uniform(0, 200)
        rows.append({
            "timestamp": ts,
            "open": p,
            "high": p + noise,
            "low": p - noise,
            "close": p + rng.uniform(-100, 100),
            "volume": rng.uniform(100, 500),
        })
    return pd.DataFrame(rows)


def make_engine(grid_count: int = 10) -> BacktestEngine:
    grid_config = GridConfig(
        symbol="BTC/USDT",
        upper_price=67000.0,
        lower_price=63000.0,
        grid_count=grid_count,
        investment_amount=10000.0,
        grid_type="arithmetic",
    )
    risk_config = RiskConfig(
        max_position_pct=0.95,
        stop_loss_pct=0.15,
        daily_loss_limit=2000.0,
        max_open_orders=100,
        max_drawdown_pct=0.50,
    )
    strategy = GridStrategy(grid_config)
    portfolio = Portfolio(initial_capital=10000.0, symbol="BTC/USDT")
    risk_manager = RiskManager(risk_config)
    return BacktestEngine(
        strategy=strategy,
        portfolio=portfolio,
        risk_manager=risk_manager,
        commission_rate=0.001,
        slippage_pct=0.0005,
    )


class TestBacktestEngine:
    def test_run_produces_result(self):
        engine = make_engine()
        ohlcv = make_ohlcv(100)
        result = engine.run(ohlcv)
        assert result is not None

    def test_equity_curve_non_empty(self):
        engine = make_engine()
        ohlcv = make_ohlcv(100)
        result = engine.run(ohlcv)
        assert not result.equity_curve.empty
        assert len(result.equity_curve) == 100

    def test_metrics_populated(self):
        engine = make_engine()
        ohlcv = make_ohlcv(100)
        result = engine.run(ohlcv)
        m = result.metrics
        assert isinstance(m.total_pnl, float)
        assert isinstance(m.sharpe_ratio, float)
        assert 0.0 <= m.max_drawdown <= 1.0
        assert 0.0 <= m.win_rate <= 1.0

    def test_final_equity_is_positive(self):
        engine = make_engine()
        ohlcv = make_ohlcv(100)
        result = engine.run(ohlcv)
        assert result.final_equity > 0

    def test_fills_are_list(self):
        engine = make_engine()
        ohlcv = make_ohlcv(50)
        result = engine.run(ohlcv)
        assert isinstance(result.fills, list)

    def test_metrics_dict_keys(self):
        engine = make_engine()
        ohlcv = make_ohlcv(50)
        result = engine.run(ohlcv)
        d = result.metrics.to_dict()
        expected_keys = {
            "total_pnl", "total_pnl_pct", "sharpe_ratio",
            "max_drawdown", "win_rate", "total_trades",
        }
        assert expected_keys.issubset(d.keys())
