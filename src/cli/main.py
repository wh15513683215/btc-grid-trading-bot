"""CLI entry point for the grid trading system."""

import asyncio
import json
import sys
from pathlib import Path

import click
from loguru import logger
from tabulate import tabulate

from src.core.config import load_config
from src.core.logger import setup_logger


@click.group()
@click.option("--config", "-c", default="config/config.yaml", help="Path to config YAML")
@click.pass_context
def cli(ctx: click.Context, config: str) -> None:
    """Crypto Grid Trading System — Binance"""
    ctx.ensure_object(dict)
    ctx.obj["config_path"] = config


@cli.command("trade")
@click.option("--dry-run", is_flag=True, default=False, help="Simulate without placing real orders")
@click.pass_context
def start_trading(ctx: click.Context, dry_run: bool) -> None:
    """Start live grid trading."""
    config_path = ctx.obj["config_path"]

    try:
        config = load_config(config_path)
    except Exception as e:
        click.echo(f"[ERROR] Failed to load config: {e}", err=True)
        sys.exit(1)

    setup_logger(config.logging.log_dir, config.logging.level)

    from src.exchange.binance import BinanceExchange
    from src.risk.manager import RiskManager
    from src.strategy.grid import GridStrategy
    from src.trading.engine import TradingEngine
    from src.trading.order_manager import OrderManager
    from src.trading.position_tracker import PositionTracker

    exchange = BinanceExchange(config.exchange)
    strategy = GridStrategy(config.grid)
    order_manager = OrderManager()
    position_tracker = PositionTracker(config.grid.symbol)
    risk_manager = RiskManager(config.risk)

    engine = TradingEngine(
        strategy=strategy,
        exchange=exchange,
        order_manager=order_manager,
        position_tracker=position_tracker,
        risk_manager=risk_manager,
        config=config,
        dry_run=dry_run,
    )

    mode = "[DRY RUN] " if dry_run else ""
    click.echo(f"{mode}Starting grid trading for {config.grid.symbol}...")
    asyncio.run(engine.start())


@cli.command("backtest")
@click.option("--symbol", "-s", required=True, help="Trading pair, e.g. BTC/USDT")
@click.option("--start", required=True, help="Start date YYYY-MM-DD")
@click.option("--end", required=True, help="End date YYYY-MM-DD")
@click.option("--timeframe", "-t", default="1h", help="Candle timeframe (default: 1h)")
@click.option("--output", "-o", default=None, help="Save results to JSON file")
@click.option("--no-cache", is_flag=True, default=False, help="Re-download data even if cached")
@click.pass_context
def run_backtest(
    ctx: click.Context,
    symbol: str,
    start: str,
    end: str,
    timeframe: str,
    output: str,
    no_cache: bool,
) -> None:
    """Run grid strategy backtest on historical data."""
    config_path = ctx.obj["config_path"]

    try:
        config = load_config(config_path)
    except Exception as e:
        click.echo(f"[ERROR] Failed to load config: {e}", err=True)
        sys.exit(1)

    setup_logger(config.logging.log_dir, config.logging.level)

    async def _run():
        from src.backtest.engine import BacktestEngine
        from src.backtest.portfolio import Portfolio
        from src.data.collector import DataCollector
        from src.data.storage import DataStorage
        from src.exchange.binance import BinanceExchange
        from src.risk.manager import RiskManager
        from src.strategy.grid import GridStrategy

        exchange = BinanceExchange(config.exchange)
        storage = DataStorage(config.data.historical_dir)
        collector = DataCollector(exchange, storage)

        click.echo(f"Fetching {symbol} {timeframe} data from {start} to {end}...")

        if no_cache or not storage.exists(symbol, timeframe):
            ohlcv = await collector.fetch_full_history(symbol, timeframe, start, end)
            storage.save(ohlcv, symbol, timeframe)
        else:
            ohlcv = storage.load(symbol, timeframe, start, end)

        await exchange.close()

        click.echo(f"Loaded {len(ohlcv)} bars. Running backtest...")

        # Override grid config symbol with CLI arg
        grid_config = config.grid.model_copy(update={"symbol": symbol})
        strategy = GridStrategy(grid_config)
        portfolio = Portfolio(config.backtest.initial_capital, symbol)
        risk_manager = RiskManager(config.risk)

        engine = BacktestEngine(
            strategy=strategy,
            portfolio=portfolio,
            risk_manager=risk_manager,
            commission_rate=config.backtest.commission_rate,
            slippage_pct=config.backtest.slippage_pct,
        )

        result = engine.run(ohlcv, start, end)
        metrics = result.metrics.to_dict()

        # Pretty-print results
        click.echo("\n" + "=" * 50)
        click.echo("BACKTEST RESULTS")
        click.echo("=" * 50)
        rows = [[k, v] for k, v in metrics.items()]
        click.echo(tabulate(rows, headers=["Metric", "Value"], tablefmt="simple"))
        click.echo(f"\nInitial capital : {result.initial_capital:,.2f}")
        click.echo(f"Final equity    : {result.final_equity:,.2f}")
        click.echo(f"Total fills     : {len(result.fills)}")

        if output:
            out_path = Path(output)
            with open(out_path, "w") as f:
                json.dump(metrics, f, indent=2)
            click.echo(f"\nResults saved to {out_path}")

    asyncio.run(_run())


@cli.command("collect")
@click.option("--symbol", "-s", required=True, help="Trading pair, e.g. BTC/USDT")
@click.option("--timeframe", "-t", default="1h", help="Candle timeframe")
@click.option("--start", required=True, help="Start date YYYY-MM-DD")
@click.option("--end", required=True, help="End date YYYY-MM-DD")
@click.pass_context
def collect_data(ctx: click.Context, symbol: str, timeframe: str, start: str, end: str) -> None:
    """Download and cache historical OHLCV data."""
    config_path = ctx.obj["config_path"]

    try:
        config = load_config(config_path)
    except Exception as e:
        click.echo(f"[ERROR] Failed to load config: {e}", err=True)
        sys.exit(1)

    setup_logger(config.logging.log_dir, config.logging.level)

    async def _run():
        from src.data.collector import DataCollector
        from src.data.storage import DataStorage
        from src.exchange.binance import BinanceExchange

        exchange = BinanceExchange(config.exchange)
        storage = DataStorage(config.data.historical_dir)
        collector = DataCollector(exchange, storage)

        click.echo(f"Downloading {symbol} {timeframe} from {start} to {end}...")
        df = await collector.fetch_full_history(symbol, timeframe, start, end)
        storage.save(df, symbol, timeframe)
        await exchange.close()

        click.echo(f"Saved {len(df)} bars to {config.data.historical_dir}/{symbol.replace('/', '_')}_{timeframe}.csv")

    asyncio.run(_run())


@cli.command("status")
@click.pass_context
def show_status(ctx: click.Context) -> None:
    """Show grid configuration summary."""
    config_path = ctx.obj["config_path"]

    try:
        config = load_config(config_path)
    except Exception as e:
        click.echo(f"[ERROR] Failed to load config: {e}", err=True)
        sys.exit(1)

    from src.strategy.grid import GridStrategy
    strategy = GridStrategy(config.grid)
    levels = strategy.build_grid()
    prices = [f"{l.price:.4f}" for l in levels]

    click.echo("\nGrid Configuration")
    click.echo("=" * 40)
    rows = [
        ["Symbol", config.grid.symbol],
        ["Lower price", f"{config.grid.lower_price:.2f}"],
        ["Upper price", f"{config.grid.upper_price:.2f}"],
        ["Grid count", config.grid.grid_count],
        ["Grid type", config.grid.grid_type],
        ["Investment", f"{config.grid.investment_amount:.2f} USDT"],
        ["Per-level invest", f"{config.grid.investment_amount / config.grid.grid_count:.2f} USDT"],
        ["Exchange testnet", config.exchange.testnet],
    ]
    click.echo(tabulate(rows, tablefmt="simple"))
    click.echo(f"\nGrid prices: {', '.join(prices[:5])} ... {', '.join(prices[-5:])}")


if __name__ == "__main__":
    cli()
