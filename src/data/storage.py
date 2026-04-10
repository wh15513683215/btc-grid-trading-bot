"""Data persistence: read/write OHLCV data as CSV or Parquet."""

from pathlib import Path
from typing import Optional

import pandas as pd
from loguru import logger

from src.core.exceptions import DataError

OHLCV_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]


class DataStorage:
    """Handles reading and writing of OHLCV market data to disk."""

    def __init__(self, base_dir: str = "data/historical") -> None:
        self._base_dir = Path(base_dir)
        self._base_dir.mkdir(parents=True, exist_ok=True)

    def _filepath(self, symbol: str, timeframe: str, fmt: str = "csv") -> Path:
        safe_symbol = symbol.replace("/", "_")
        return self._base_dir / f"{safe_symbol}_{timeframe}.{fmt}"

    def save(self, df: pd.DataFrame, symbol: str, timeframe: str) -> Path:
        """Save OHLCV DataFrame to CSV."""
        if df.empty:
            raise DataError("Cannot save empty DataFrame")
        path = self._filepath(symbol, timeframe, "csv")
        df.to_csv(path, index=False)
        logger.debug(f"Saved {len(df)} rows to {path}")
        return path

    def load(
        self,
        symbol: str,
        timeframe: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> pd.DataFrame:
        """Load OHLCV DataFrame from CSV, optionally filtered by date range."""
        path = self._filepath(symbol, timeframe, "csv")
        if not path.exists():
            raise DataError(f"No cached data for {symbol} {timeframe}: {path}")

        df = pd.read_csv(path)
        df["timestamp"] = pd.to_datetime(df["timestamp"])

        if start_date:
            df = df[df["timestamp"] >= pd.Timestamp(start_date)]
        if end_date:
            df = df[df["timestamp"] <= pd.Timestamp(end_date)]

        df = df.reset_index(drop=True)
        logger.debug(f"Loaded {len(df)} rows for {symbol} {timeframe}")
        return df

    def exists(self, symbol: str, timeframe: str) -> bool:
        return self._filepath(symbol, timeframe, "csv").exists()

    def append(self, df: pd.DataFrame, symbol: str, timeframe: str) -> None:
        """Append new rows to existing CSV (deduplicates by timestamp)."""
        if self.exists(symbol, timeframe):
            existing = self.load(symbol, timeframe)
            combined = pd.concat([existing, df], ignore_index=True)
            combined = combined.drop_duplicates(subset=["timestamp"]).sort_values("timestamp")
            self.save(combined, symbol, timeframe)
        else:
            self.save(df, symbol, timeframe)
