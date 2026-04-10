"""Configuration loading and validation using Pydantic."""

import os
import re
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, field_validator, model_validator
from dotenv import load_dotenv

from src.core.exceptions import ConfigError


class ExchangeConfig(BaseModel):
    name: str = "binance"
    api_key: str
    api_secret: str
    testnet: bool = True
    rate_limit_ms: int = 200


class GridConfig(BaseModel):
    symbol: str
    upper_price: float
    lower_price: float
    grid_count: int
    investment_amount: float
    grid_type: str = "arithmetic"  # arithmetic | geometric
    take_profit_price: Optional[float] = None
    stop_loss_price: Optional[float] = None

    @field_validator("grid_type")
    @classmethod
    def validate_grid_type(cls, v: str) -> str:
        if v not in ("arithmetic", "geometric"):
            raise ValueError("grid_type must be 'arithmetic' or 'geometric'")
        return v

    @model_validator(mode="after")
    def validate_price_range(self) -> "GridConfig":
        if self.upper_price <= self.lower_price:
            raise ValueError("upper_price must be greater than lower_price")
        if self.grid_count < 2:
            raise ValueError("grid_count must be at least 2")
        if self.investment_amount <= 0:
            raise ValueError("investment_amount must be positive")
        return self


class RiskConfig(BaseModel):
    max_position_pct: float = 0.95
    stop_loss_pct: float = 0.08
    daily_loss_limit: float = 500.0
    max_open_orders: int = 50
    max_drawdown_pct: float = 0.20


class BacktestConfig(BaseModel):
    commission_rate: float = 0.001
    slippage_pct: float = 0.0005
    initial_capital: float = 10000.0


class DataConfig(BaseModel):
    historical_dir: str = "data/historical"
    default_timeframe: str = "1h"


class LoggingConfig(BaseModel):
    level: str = "INFO"
    log_dir: str = "logs"
    max_bytes: int = 10485760
    backup_count: int = 5


class AppConfig(BaseModel):
    exchange: ExchangeConfig
    grid: GridConfig
    risk: RiskConfig = RiskConfig()
    backtest: BacktestConfig = BacktestConfig()
    data: DataConfig = DataConfig()
    logging: LoggingConfig = LoggingConfig()


def _resolve_env_vars(value: str) -> str:
    """Replace ${VAR_NAME} placeholders with environment variable values."""
    pattern = re.compile(r"\$\{([^}]+)\}")

    def replace(match: re.Match) -> str:
        var_name = match.group(1)
        env_value = os.environ.get(var_name)
        if env_value is None:
            raise ConfigError(f"Environment variable '{var_name}' is not set")
        return env_value

    return pattern.sub(replace, value)


def _resolve_dict(data: dict) -> dict:
    """Recursively resolve environment variable placeholders in a dict."""
    resolved = {}
    for key, value in data.items():
        if isinstance(value, str):
            resolved[key] = _resolve_env_vars(value)
        elif isinstance(value, dict):
            resolved[key] = _resolve_dict(value)
        else:
            resolved[key] = value
    return resolved


def load_config(config_path: str = "config/config.yaml", env_file: str = ".env") -> AppConfig:
    """Load and validate configuration from YAML file."""
    # Load .env file if it exists
    env_path = Path(env_file)
    if env_path.exists():
        load_dotenv(env_path)

    path = Path(config_path)
    if not path.exists():
        raise ConfigError(f"Config file not found: {config_path}")

    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ConfigError(f"Failed to parse config YAML: {e}") from e

    if not isinstance(raw, dict):
        raise ConfigError("Config file must be a YAML mapping")

    resolved = _resolve_dict(raw)

    try:
        return AppConfig(**resolved)
    except Exception as e:
        raise ConfigError(f"Config validation failed: {e}") from e
