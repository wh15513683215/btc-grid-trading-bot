"""Binance exchange implementation using ccxt."""

import asyncio
from typing import Callable, Dict, List, Optional

import ccxt.pro as ccxtpro
from loguru import logger

from src.core.config import ExchangeConfig
from src.core.exceptions import ExchangeError, InsufficientFundsError, OrderNotFoundError
from src.exchange.base import Balance, BaseExchange, Fill, Order, Ticker


class BinanceExchange(BaseExchange):
    """ccxt-based Binance exchange wrapper supporting both REST and WebSocket."""

    def __init__(self, config: ExchangeConfig) -> None:
        self._config = config
        options: dict = {"defaultType": "spot"}
        if config.testnet:
            options["defaultType"] = "spot"

        self._exchange = ccxtpro.binance(
            {
                "apiKey": config.api_key,
                "secret": config.api_secret,
                "enableRateLimit": True,
                "rateLimit": config.rate_limit_ms,
                "options": options,
            }
        )

        if config.testnet:
            self._exchange.set_sandbox_mode(True)

        self._ticker_task: Optional[asyncio.Task] = None
        self._order_task: Optional[asyncio.Task] = None

    # ------------------------------------------------------------------
    # REST methods
    # ------------------------------------------------------------------

    async def place_limit_order(
        self, symbol: str, side: str, price: float, quantity: float
    ) -> Order:
        try:
            result = await self._exchange.create_limit_order(symbol, side, quantity, price)
            return self._parse_order(result)
        except ccxtpro.InsufficientFunds as e:
            raise InsufficientFundsError(str(e)) from e
        except ccxtpro.BaseError as e:
            raise ExchangeError(f"Failed to place order: {e}") from e

    async def cancel_order(self, order_id: str, symbol: str) -> bool:
        try:
            await self._exchange.cancel_order(order_id, symbol)
            return True
        except ccxtpro.OrderNotFound as e:
            raise OrderNotFoundError(str(e)) from e
        except ccxtpro.BaseError as e:
            raise ExchangeError(f"Failed to cancel order {order_id}: {e}") from e

    async def get_open_orders(self, symbol: str) -> List[Order]:
        try:
            raw = await self._exchange.fetch_open_orders(symbol)
            return [self._parse_order(o) for o in raw]
        except ccxtpro.BaseError as e:
            raise ExchangeError(f"Failed to fetch open orders: {e}") from e

    async def get_order_status(self, order_id: str, symbol: str) -> Order:
        try:
            raw = await self._exchange.fetch_order(order_id, symbol)
            return self._parse_order(raw)
        except ccxtpro.OrderNotFound as e:
            raise OrderNotFoundError(str(e)) from e
        except ccxtpro.BaseError as e:
            raise ExchangeError(f"Failed to fetch order {order_id}: {e}") from e

    async def get_balance(self) -> Dict[str, Balance]:
        try:
            raw = await self._exchange.fetch_balance()
            balances: Dict[str, Balance] = {}
            for currency, info in raw.get("total", {}).items():
                if info and info > 0:
                    balances[currency] = Balance(
                        currency=currency,
                        free=raw["free"].get(currency, 0.0) or 0.0,
                        used=raw["used"].get(currency, 0.0) or 0.0,
                        total=raw["total"].get(currency, 0.0) or 0.0,
                    )
            return balances
        except ccxtpro.BaseError as e:
            raise ExchangeError(f"Failed to fetch balance: {e}") from e

    async def get_ticker(self, symbol: str) -> Ticker:
        try:
            raw = await self._exchange.fetch_ticker(symbol)
            return Ticker(
                symbol=symbol,
                last=raw["last"],
                bid=raw["bid"],
                ask=raw["ask"],
                timestamp=raw["timestamp"],
            )
        except ccxtpro.BaseError as e:
            raise ExchangeError(f"Failed to fetch ticker: {e}") from e

    async def cancel_all_orders(self, symbol: str) -> int:
        try:
            open_orders = await self.get_open_orders(symbol)
            cancelled = 0
            for order in open_orders:
                try:
                    await self.cancel_order(order.order_id, symbol)
                    cancelled += 1
                except OrderNotFoundError:
                    pass  # Already gone
            return cancelled
        except ExchangeError:
            raise

    # ------------------------------------------------------------------
    # WebSocket methods
    # ------------------------------------------------------------------

    async def subscribe_ticker(self, symbol: str, callback: Callable[[Ticker], None]) -> None:
        """Start background task streaming ticker updates."""
        async def _stream():
            while True:
                try:
                    raw = await self._exchange.watch_ticker(symbol)
                    ticker = Ticker(
                        symbol=symbol,
                        last=raw["last"],
                        bid=raw["bid"],
                        ask=raw["ask"],
                        timestamp=raw["timestamp"],
                    )
                    await asyncio.get_event_loop().run_in_executor(None, callback, ticker)
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.warning(f"Ticker stream error: {e}, reconnecting...")
                    await asyncio.sleep(1)

        self._ticker_task = asyncio.create_task(_stream())

    async def subscribe_order_updates(self, callback: Callable[[Fill], None]) -> None:
        """Start background task streaming order fill events."""
        async def _stream():
            while True:
                try:
                    orders = await self._exchange.watch_orders()
                    for raw in orders:
                        if not raw:
                            continue
                        if raw.get("status") == "closed" and raw.get("filled", 0) > 0:
                            fill = Fill(
                                order_id=str(raw["id"]),
                                symbol=raw["symbol"],
                                side=raw["side"],
                                price=raw["average"] or raw["price"],
                                quantity=raw["filled"],
                                fee=raw.get("fee", {}).get("cost", 0.0) or 0.0,
                                timestamp=raw["timestamp"],
                            )
                            await asyncio.get_event_loop().run_in_executor(None, callback, fill)
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.warning(f"Order stream error: {e}, reconnecting...")
                    await asyncio.sleep(1)

        self._order_task = asyncio.create_task(_stream())

    async def close(self) -> None:
        if self._ticker_task:
            self._ticker_task.cancel()
        if self._order_task:
            self._order_task.cancel()
        await self._exchange.close()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _parse_order(self, raw: dict) -> Order:
        status_map = {
            "open": "open",
            "closed": "filled",
            "canceled": "cancelled",
            "cancelled": "cancelled",
            "partially_filled": "partial",
        }
        status = status_map.get(raw.get("status", ""), "open")
        return Order(
            order_id=str(raw["id"]),
            symbol=raw["symbol"],
            side=raw["side"],
            price=raw["price"] or 0.0,
            quantity=raw["amount"],
            status=status,
            filled_qty=raw.get("filled", 0.0) or 0.0,
            timestamp=raw.get("timestamp"),
        )
