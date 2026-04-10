"""Live trading engine: async event loop coordinating all components."""

import asyncio
import signal
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from loguru import logger

from src.backtest.portfolio import PortfolioState
from src.core.config import AppConfig
from src.exchange.base import BaseExchange, Fill, Ticker
from src.risk.manager import RiskManager
from src.strategy.grid import GridStrategy
from src.trading.order_manager import OrderManager
from src.trading.position_tracker import PositionTracker


@dataclass
class TradingStatus:
    symbol: str
    running: bool
    uptime_seconds: float
    open_orders: int
    position_qty: float
    avg_entry_price: float
    realized_pnl: float
    unrealized_pnl: float
    total_fills: int
    last_price: float


class TradingEngine:
    """
    Async live trading engine.
    Coordinates: strategy ↔ exchange ↔ order manager ↔ position tracker ↔ risk manager.
    """

    def __init__(
        self,
        strategy: GridStrategy,
        exchange: BaseExchange,
        order_manager: OrderManager,
        position_tracker: PositionTracker,
        risk_manager: RiskManager,
        config: AppConfig,
        dry_run: bool = False,
    ) -> None:
        self._strategy = strategy
        self._exchange = exchange
        self._order_manager = order_manager
        self._position_tracker = position_tracker
        self._risk_manager = risk_manager
        self._config = config
        self._dry_run = dry_run

        self._running = False
        self._start_time: Optional[datetime] = None
        self._last_price: float = 0.0
        self._total_fills = 0

    async def start(self) -> None:
        """Initialize grid and start trading event loop."""
        logger.info(
            f"TradingEngine starting | symbol={self._config.grid.symbol} | "
            f"dry_run={self._dry_run} | testnet={self._config.exchange.testnet}"
        )

        # Fetch current price
        ticker = await self._exchange.get_ticker(self._config.grid.symbol)
        self._last_price = ticker.last
        logger.info(f"Current price: {ticker.last}")

        # Check account balance
        balances = await self._exchange.get_balance()
        quote = self._config.grid.symbol.split("/")[1]
        quote_balance = balances.get(quote)
        available = quote_balance.free if quote_balance else 0.0
        logger.info(f"Available {quote}: {available:.2f}")

        min_required = self._config.grid.investment_amount * 0.9
        if available < min_required and not self._dry_run:
            logger.error(
                f"Insufficient balance: need at least {min_required:.2f} {quote}, "
                f"have {available:.2f}"
            )
            return

        # Build grid
        self._strategy.build_grid()

        # Fetch and cancel any existing orders
        existing = await self._exchange.get_open_orders(self._config.grid.symbol)
        if existing:
            logger.info(f"Cancelling {len(existing)} existing orders")
            if not self._dry_run:
                await self._exchange.cancel_all_orders(self._config.grid.symbol)

        # Place initial grid orders
        initial_orders = self._strategy.get_initial_orders()
        portfolio_state = PortfolioState(
            cash=available,
            holdings=0.0,
            avg_entry_price=0.0,
        )

        for order in initial_orders:
            if order.price >= ticker.last:
                continue  # Skip sell orders above current price at start (buy-only init)

            decision = self._risk_manager.check_pre_trade(order, portfolio_state)
            if not decision.approved:
                logger.warning(f"Risk rejected initial order @ {order.price}: {decision.reason}")
                continue

            if self._dry_run:
                logger.info(f"[DRY RUN] Would place {order.side} @ {order.price:.4f} qty={order.quantity:.6f}")
                self._order_manager.register(order)
                self._strategy.register_order(order, order.price)
            else:
                placed = await self._exchange.place_limit_order(
                    order.symbol, order.side, order.price, order.quantity
                )
                self._order_manager.register(placed)
                self._strategy.register_order(placed, order.price)

        logger.info(f"Placed {self._order_manager.open_count()} initial orders")

        # Subscribe to real-time feeds
        await self._exchange.subscribe_ticker(
            self._config.grid.symbol, self._on_ticker_sync
        )
        await self._exchange.subscribe_order_updates(self._on_fill_sync)

        self._running = True
        self._start_time = datetime.utcnow()

        # Setup graceful shutdown
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, lambda: asyncio.create_task(self.stop()))

        logger.info("Trading engine running. Press Ctrl+C to stop.")

        # Keep alive
        while self._running:
            await asyncio.sleep(1)

    async def stop(self, cancel_orders: bool = True) -> None:
        self._running = False
        logger.info("Stopping trading engine...")

        if cancel_orders and not self._dry_run:
            cancelled = await self._exchange.cancel_all_orders(self._config.grid.symbol)
            logger.info(f"Cancelled {cancelled} open orders")

        await self._exchange.close()
        logger.info("Trading engine stopped")

    def _on_ticker_sync(self, ticker: Ticker) -> None:
        """Synchronous wrapper called from exchange WebSocket callback."""
        self._last_price = ticker.last
        if self._strategy.should_stop(ticker.last):
            logger.warning(f"Price {ticker.last} triggered strategy stop")
            asyncio.create_task(self.stop())

    def _on_fill_sync(self, fill: Fill) -> None:
        """Synchronous wrapper called from exchange WebSocket callback."""
        asyncio.create_task(self._handle_fill(fill))

    async def _handle_fill(self, fill: Fill) -> None:
        """Process a fill: update tracking, risk check, place counter-order."""
        self._order_manager.mark_filled(fill)
        self._position_tracker.apply_fill(fill)
        self._total_fills += 1

        position = self._position_tracker.get_position()
        state = PortfolioState(
            cash=0.0,  # Updated from exchange in production; simplified here
            holdings=position.quantity,
            avg_entry_price=position.avg_entry_price,
        )

        post_decision = self._risk_manager.check_post_fill(fill, state)
        if not post_decision.approved:
            logger.warning(f"Post-fill risk halt: {post_decision.reason}")
            await self.stop(cancel_orders=(post_decision.suggested_action in ("HALT", "CANCEL_ALL")))
            return

        counter = self._strategy.on_order_filled(fill)
        if counter:
            pre_decision = self._risk_manager.check_pre_trade(counter, state)
            if pre_decision.approved:
                if self._dry_run:
                    logger.info(f"[DRY RUN] Counter order: {counter.side} @ {counter.price:.4f}")
                    self._order_manager.register(counter)
                    self._strategy.register_order(counter, counter.price)
                else:
                    placed = await self._exchange.place_limit_order(
                        counter.symbol, counter.side, counter.price, counter.quantity
                    )
                    self._order_manager.register(placed)
                    self._strategy.register_order(placed, counter.price)

    def get_status(self) -> TradingStatus:
        pos = self._position_tracker.get_position()
        uptime = (datetime.utcnow() - self._start_time).total_seconds() if self._start_time else 0.0
        return TradingStatus(
            symbol=self._config.grid.symbol,
            running=self._running,
            uptime_seconds=uptime,
            open_orders=self._order_manager.open_count(),
            position_qty=pos.quantity,
            avg_entry_price=pos.avg_entry_price,
            realized_pnl=pos.realized_pnl,
            unrealized_pnl=self._position_tracker.get_unrealized_pnl(self._last_price),
            total_fills=self._total_fills,
            last_price=self._last_price,
        )
