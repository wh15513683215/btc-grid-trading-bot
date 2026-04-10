"""Custom exception hierarchy for the grid trading system."""


class GridTradingError(Exception):
    """Base exception for all grid trading errors."""


class ConfigError(GridTradingError):
    """Raised when configuration is invalid or missing."""


class ExchangeError(GridTradingError):
    """Raised when exchange API calls fail."""


class InsufficientFundsError(ExchangeError):
    """Raised when account has insufficient funds to place an order."""


class OrderNotFoundError(ExchangeError):
    """Raised when an order ID cannot be found on the exchange."""


class RiskLimitError(GridTradingError):
    """Raised when a risk limit is breached and trading must halt."""


class DailyLossLimitError(RiskLimitError):
    """Raised when daily loss limit is exceeded."""


class MaxDrawdownError(RiskLimitError):
    """Raised when maximum drawdown threshold is exceeded."""


class StopLossError(RiskLimitError):
    """Raised when stop-loss is triggered."""


class DataError(GridTradingError):
    """Raised when data collection or storage fails."""


class StrategyError(GridTradingError):
    """Raised when strategy logic encounters an error."""


class GridOutOfRangeError(StrategyError):
    """Raised when price exits the grid range."""
