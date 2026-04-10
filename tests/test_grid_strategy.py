"""Tests for GridStrategy."""

import pytest
from src.core.config import GridConfig
from src.exchange.base import Fill
from src.strategy.grid import GridStrategy


def make_config(**kwargs) -> GridConfig:
    defaults = dict(
        symbol="BTC/USDT",
        upper_price=70000.0,
        lower_price=60000.0,
        grid_count=10,
        investment_amount=10000.0,
        grid_type="arithmetic",
    )
    defaults.update(kwargs)
    return GridConfig(**defaults)


class TestGridPrices:
    def test_arithmetic_count(self):
        strategy = GridStrategy(make_config(grid_count=10))
        levels = strategy.build_grid()
        assert len(levels) == 10

    def test_arithmetic_first_last(self):
        strategy = GridStrategy(make_config(lower_price=60000, upper_price=70000, grid_count=10))
        levels = strategy.build_grid()
        assert abs(levels[0].price - 60000) < 1e-4
        assert abs(levels[-1].price - 70000) < 1e-4

    def test_arithmetic_equal_spacing(self):
        strategy = GridStrategy(make_config(lower_price=60000, upper_price=70000, grid_count=6))
        levels = strategy.build_grid()
        step = 2000.0
        for i in range(1, len(levels)):
            assert abs((levels[i].price - levels[i - 1].price) - step) < 1e-4

    def test_geometric_count(self):
        strategy = GridStrategy(make_config(grid_count=5, grid_type="geometric"))
        levels = strategy.build_grid()
        assert len(levels) == 5

    def test_geometric_ratio_constant(self):
        strategy = GridStrategy(
            make_config(lower_price=60000, upper_price=70000, grid_count=5, grid_type="geometric")
        )
        levels = strategy.build_grid()
        ratios = [levels[i + 1].price / levels[i].price for i in range(len(levels) - 1)]
        for r in ratios:
            assert abs(r - ratios[0]) < 1e-6

    def test_quantity_sum_equals_investment(self):
        config = make_config(grid_count=10, investment_amount=10000)
        strategy = GridStrategy(config)
        levels = strategy.build_grid()
        total = sum(l.price * l.quantity for l in levels)
        assert abs(total - config.investment_amount) < 1.0  # within $1


class TestOnOrderFilled:
    def _make_filled_strategy(self):
        strategy = GridStrategy(make_config(grid_count=5, lower_price=60000, upper_price=70000))
        strategy.build_grid()
        orders = strategy.get_initial_orders()
        for order in orders:
            strategy.register_order(order, order.price)
        return strategy, orders

    def test_buy_fill_produces_sell_above(self):
        strategy, orders = self._make_filled_strategy()
        # Simulate fill of the 2nd buy order (index 1)
        buy_order = orders[1]
        fill = Fill(
            order_id=buy_order.order_id,
            symbol="BTC/USDT",
            side="buy",
            price=buy_order.price,
            quantity=buy_order.quantity,
            fee=0.001,
            timestamp=0,
        )
        counter = strategy.on_order_filled(fill)
        assert counter is not None
        assert counter.side == "sell"
        assert counter.price > buy_order.price

    def test_no_counter_at_top_level(self):
        strategy, orders = self._make_filled_strategy()
        top_order = orders[-1]
        fill = Fill(
            order_id=top_order.order_id,
            symbol="BTC/USDT",
            side="buy",
            price=top_order.price,
            quantity=top_order.quantity,
            fee=0.001,
            timestamp=0,
        )
        counter = strategy.on_order_filled(fill)
        assert counter is None


class TestShouldStop:
    def test_stop_loss_price(self):
        config = make_config(stop_loss_price=55000.0)
        strategy = GridStrategy(config)
        strategy.build_grid()
        assert strategy.should_stop(54000) is True
        assert strategy.should_stop(56000) is False

    def test_take_profit_price(self):
        config = make_config(take_profit_price=75000.0)
        strategy = GridStrategy(config)
        strategy.build_grid()
        assert strategy.should_stop(76000) is True
        assert strategy.should_stop(74000) is False

    def test_no_stop_by_default(self):
        strategy = GridStrategy(make_config())
        strategy.build_grid()
        assert strategy.should_stop(65000) is False
