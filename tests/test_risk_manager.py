"""Tests for RiskManager."""

import pytest
from src.backtest.portfolio import PortfolioState
from src.core.config import RiskConfig
from src.exchange.base import Fill, Order
from src.risk.manager import RiskManager


def make_risk_config(**kwargs) -> RiskConfig:
    defaults = dict(
        max_position_pct=0.95,
        stop_loss_pct=0.08,
        daily_loss_limit=500.0,
        max_open_orders=50,
        max_drawdown_pct=0.20,
    )
    defaults.update(kwargs)
    return RiskConfig(**defaults)


def make_order(side="buy", price=65000, quantity=0.01) -> Order:
    return Order(
        order_id="test_1",
        symbol="BTC/USDT",
        side=side,
        price=price,
        quantity=quantity,
        status="pending",
    )


def make_fill(side="buy", price=65000, quantity=0.01, fee=0.001) -> Fill:
    return Fill(
        order_id="test_1",
        symbol="BTC/USDT",
        side=side,
        price=price,
        quantity=quantity,
        fee=fee,
        timestamp=0,
    )


class TestPreTradeChecks:
    def test_approved_normal_buy(self):
        rm = RiskManager(make_risk_config())
        state = PortfolioState(cash=10000, holdings=0, avg_entry_price=0)
        order = make_order(side="buy", price=65000, quantity=0.1)
        decision = rm.check_pre_trade(order, state)
        assert decision.approved

    def test_rejected_insufficient_cash(self):
        rm = RiskManager(make_risk_config())
        state = PortfolioState(cash=100, holdings=0, avg_entry_price=0)
        order = make_order(side="buy", price=65000, quantity=1.0)
        decision = rm.check_pre_trade(order, state)
        assert not decision.approved  # Rejected for position limit or cash — either is valid

    def test_rejected_insufficient_holdings_for_sell(self):
        rm = RiskManager(make_risk_config())
        state = PortfolioState(cash=10000, holdings=0.001, avg_entry_price=65000)
        order = make_order(side="sell", price=65000, quantity=1.0)
        decision = rm.check_pre_trade(order, state)
        assert not decision.approved

    def test_approved_sell_with_enough_holdings(self):
        rm = RiskManager(make_risk_config())
        state = PortfolioState(cash=0, holdings=1.0, avg_entry_price=65000)
        order = make_order(side="sell", price=65000, quantity=0.5)
        decision = rm.check_pre_trade(order, state)
        assert decision.approved

    def test_rejected_daily_loss_limit(self):
        rm = RiskManager(make_risk_config(daily_loss_limit=100))
        rm._daily_pnl = -200  # Force over limit
        state = PortfolioState(cash=10000, holdings=0, avg_entry_price=0)
        order = make_order()
        decision = rm.check_pre_trade(order, state)
        assert not decision.approved
        assert "daily loss" in decision.reason.lower()


class TestPostFillChecks:
    def test_approved_normal_fill(self):
        rm = RiskManager(make_risk_config())
        rm.set_session_start_equity(10000)
        fill = make_fill(side="buy", price=65000, quantity=0.01)
        state = PortfolioState(cash=9000, holdings=0.01, avg_entry_price=65000)
        decision = rm.check_post_fill(fill, state)
        assert decision.approved

    def test_max_drawdown_triggers_halt(self):
        rm = RiskManager(make_risk_config(max_drawdown_pct=0.10))
        rm.set_session_start_equity(10000)
        rm._peak_equity = 10000
        fill = make_fill(side="buy", price=65000, quantity=0.1)
        # Simulate equity drop of 15% — cash + holdings below peak
        state = PortfolioState(cash=8500, holdings=0.0, avg_entry_price=0)
        decision = rm.check_post_fill(fill, state)
        assert not decision.approved
        assert decision.suggested_action == "HALT"


class TestGetMaxOrderSize:
    def test_basic_size_calc(self):
        rm = RiskManager(make_risk_config(max_position_pct=0.5))
        size = rm.get_max_order_size(price=50000, available_cash=10000)
        assert abs(size - 0.1) < 1e-8  # 10000 * 0.5 / 50000
