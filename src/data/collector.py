"""Data collection: fetch OHLCV, orderbook, and trade data from exchange."""

import asyncio
import time
from datetime import datetime
from typing import Optional

import ccxt.async_support as ccxt_async
import pandas as pd
from loguru import logger

from src.core.exceptions import DataError
from src.data.storage import DataStorage
from src.exchange.base import BaseExchange

OHLCV_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]


class DataCollector:
    """Fetches market data from exchange via REST API."""

    def __init__(self, exchange: BaseExchange, storage: DataStorage) -> None:
        self._exchange = exchange
        self._storage = storage
        # Separate public client without sandbox — testnet has no historical OHLCV
        self._public = ccxt_async.binance({"enableRateLimit": True})

    async def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        since: Optional[int] = None,
        limit: int = 500,
    ) -> pd.DataFrame:
        """Fetch a single batch of OHLCV bars."""
        try:
            raw = await self._public.fetch_ohlcv(
                symbol, timeframe, since=since, limit=limit
            )
        except Exception as e:
            raise DataError(f"Failed to fetch OHLCV for {symbol}: {e}") from e

        if not raw:
            return pd.DataFrame(columns=OHLCV_COLUMNS)

        df = pd.DataFrame(raw, columns=OHLCV_COLUMNS)
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        return df

    async def fetch_full_history(
        self,
        symbol: str,
        timeframe: str,
        start_date: str,
        end_date: str,
    ) -> pd.DataFrame:
        """Download complete historical OHLCV data with pagination."""
        start_ms = int(datetime.strptime(start_date, "%Y-%m-%d").timestamp() * 1000)
        end_ms = int(datetime.strptime(end_date, "%Y-%m-%d").timestamp() * 1000)

        all_bars = []
        since = start_ms
        batch_size = 500

        logger.info(f"Fetching {symbol} {timeframe} from {start_date} to {end_date}")

        while since < end_ms:
            df = await self.fetch_ohlcv(symbol, timeframe, since=since, limit=batch_size)
            if df.empty:
                break

            # Filter to requested range
            df = df[df["timestamp"] <= pd.Timestamp(end_date)]
            if df.empty:
                break
            all_bars.append(df)

            last_ts = int(df["timestamp"].iloc[-1].timestamp() * 1000)
            if last_ts <= since:
                break
            since = last_ts + 1

            fetched = sum(len(b) for b in all_bars)
            logger.debug(f"Fetched {fetched} bars so far...")
            await asyncio.sleep(0.2)  # Respect rate limit

        if not all_bars:
            raise DataError(f"No data returned for {symbol} {timeframe}")

        result = pd.concat(all_bars, ignore_index=True)
        result = result.drop_duplicates(subset=["timestamp"]).sort_values("timestamp")
        result = result.reset_index(drop=True)

        logger.info(f"Downloaded {len(result)} bars for {symbol} {timeframe}")
        await self._public.close()
        return result

    async def fetch_and_cache(
        self,
        symbol: str,
        timeframe: str,
        start_date: str,
        end_date: str,
    ) -> pd.DataFrame:
        """Fetch full history and save to disk, or load from cache if present."""
        if self._storage.exists(symbol, timeframe):
            logger.info(f"Loading cached data for {symbol} {timeframe}")
            return self._storage.load(symbol, timeframe, start_date, end_date)

        df = await self.fetch_full_history(symbol, timeframe, start_date, end_date)
        self._storage.save(df, symbol, timeframe)
        return self._storage.load(symbol, timeframe, start_date, end_date)

    async def fetch_orderbook(self, symbol: str, depth: int = 20) -> dict:
        """Fetch current order book snapshot."""
        try:
            raw = await self._exchange._exchange.fetch_order_book(symbol, limit=depth)
            return {
                "bids": raw["bids"],
                "asks": raw["asks"],
                "timestamp": raw.get("timestamp", int(time.time() * 1000)),
            }
        except Exception as e:
            raise DataError(f"Failed to fetch orderbook for {symbol}: {e}") from e

    async def fetch_recent_trades(self, symbol: str, limit: int = 100) -> pd.DataFrame:
        """Fetch recent public trades."""
        try:
            raw = await self._exchange._exchange.fetch_trades(symbol, limit=limit)
            rows = [
                {
                    "timestamp": pd.Timestamp(t["timestamp"], unit="ms"),
                    "side": t["side"],
                    "price": t["price"],
                    "amount": t["amount"],
                }
                for t in raw
            ]
            return pd.DataFrame(rows)
        except Exception as e:
            raise DataError(f"Failed to fetch trades for {symbol}: {e}") from e
