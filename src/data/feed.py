"""Real-time WebSocket data feed."""

import asyncio
from typing import Callable, Optional

from loguru import logger

from src.exchange.base import BaseExchange, Ticker


class DataFeed:
    """Manages real-time price and order update subscriptions."""

    def __init__(self, exchange: BaseExchange) -> None:
        self._exchange = exchange
        self._running = False

    async def start(
        self,
        symbol: str,
        on_ticker: Callable[[Ticker], None],
        on_fill: Optional[Callable] = None,
    ) -> None:
        """Subscribe to ticker and optionally order fill events."""
        self._running = True
        logger.info(f"Starting data feed for {symbol}")

        await self._exchange.subscribe_ticker(symbol, on_ticker)
        if on_fill:
            await self._exchange.subscribe_order_updates(on_fill)

    async def stop(self) -> None:
        self._running = False
        await self._exchange.close()
        logger.info("Data feed stopped")
