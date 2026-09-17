"""Spot Trading MCP Server — V4.

Exposes 50+ MCP tools for controlling and querying AI Crypto Sniper
spot trading module (Jupiter DEX). Tools are grouped by:

1. Bot control (4)
2. Market discovery (6)
3. Price data (5)
4. Technical analysis (7)
5. Signals (5)
6. Configuration (6)
7. Positions (5)
8. Orders (5)
9. Trade history (4)
10. P&L (3)
11. Risk (4)
12. Wallet (3)
13. Logs (2)
14. Alerts (2)
15. DCA (3)
16. Risk level (2)
17. Rebalancing (2)
18. Token management (3)
19. Quote/swap (3)
20. Statistics (2)

The server works by reading/writing the spot configuration file and a
spot command queue. The live SpotSnipeBot engine picks up queued commands.
"""

import json
import os
import sys
import time
from typing import Any

# Allow imports of V4 root spot modules when running from this package
PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
V4_ROOT = os.path.dirname(PACKAGE_DIR)
if V4_ROOT not in sys.path:
    sys.path.insert(0, V4_ROOT)

from mcp.server.fastmcp import FastMCP

from spot_config_schema import (
    SPOT_CONFIG_RULES,
    RISK_LEVEL_MAX,
    RISK_LEVEL_MIN,
    build_spot_risk_level_profile,
    parse_spot_config_value,
    risk_level_name,
    validate_spot_config,
)

PROJECT_DIR = (os.environ.get("AI_CRYPTO_SNIPER_DIR")
               or os.environ.get("SOLANA_SNIPER_BOT_DIR")
               or os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SPOT_CONFIG_PATH = os.path.join(PROJECT_DIR, "spot_config.json")
SPOT_COMMAND_FILE = os.path.join(PROJECT_DIR, "spot_command_queue.json")

mcp = FastMCP("ai-crypto-sniper-spot")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _read_json(path: str) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _write_json(path: str, data: Any) -> None:
    temp_path = f"{path}.tmp"
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temp_path, path)


def _load_spot_cfg() -> dict:
    defaults = {k: v.get("default") for k, v in SPOT_CONFIG_RULES.items()}
    cfg = _read_json(SPOT_CONFIG_PATH) or {}
    for k, v in defaults.items():
        if k not in cfg:
            cfg[k] = v
    return cfg


def _save_spot_cfg(cfg: dict) -> None:
    _write_json(SPOT_CONFIG_PATH, cfg)


def _enqueue_command(cmd: str, **params: Any) -> None:
    queue = _read_json(SPOT_COMMAND_FILE) or []
    queue.append({"action": cmd, **params, "timestamp": time.time()})
    queue = queue[-100:]
    _write_json(SPOT_COMMAND_FILE, queue)


def _set_cfg_value(key: str, value: Any) -> dict:
    cfg = _load_spot_cfg()
    cfg[key] = parse_spot_config_value(key, value)
    _save_spot_cfg(cfg)
    return cfg


def _update_batch(updates: dict) -> dict:
    cfg = _load_spot_cfg()
    for k, v in updates.items():
        if k in SPOT_CONFIG_RULES:
            cfg[k] = parse_spot_config_value(k, v)
    _save_spot_cfg(cfg)
    return cfg


def _pretty(d: Any) -> str:
    return json.dumps(d, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# 1. Bot control (4)
# ---------------------------------------------------------------------------
@mcp.tool()
def start_spot_bot() -> str:
    """Start the spot trading bot."""
    _enqueue_command("start")
    return "Command queued: start spot bot."


@mcp.tool()
def stop_spot_bot() -> str:
    """Stop the spot trading bot."""
    _enqueue_command("stop")
    return "Command queued: stop spot bot."


@mcp.tool()
def sell_all_spot() -> str:
    """Panic close all open spot positions immediately."""
    _enqueue_command("sell_all")
    return "Command queued: sell all spot positions."


@mcp.tool()
def get_spot_bot_status() -> str:
    """Return the current spot bot status (running, stopped, etc.)."""
    status = _read_json(os.path.join(PROJECT_DIR, "spot_bot_status.json")) or {}
    return _pretty(status)


# ---------------------------------------------------------------------------
# 2. Market discovery (6)
# ---------------------------------------------------------------------------
@mcp.tool()
def get_spot_markets() -> str:
    """Return the list of monitored spot markets with current data."""
    markets = _read_json(os.path.join(PROJECT_DIR, "spot_markets.json")) or {}
    if isinstance(markets, dict):
        count = len(markets)
    else:
        count = len(markets)
    return _pretty({"markets": markets, "count": count})


@mcp.tool()
def get_spot_market_detail(mint: str) -> str:
    """Return detailed market data for a specific token mint."""
    markets = _read_json(os.path.join(PROJECT_DIR, "spot_markets.json")) or {}
    if isinstance(markets, dict):
        data = markets.get(mint)
        if data:
            return _pretty(data)
    return _pretty({"error": f"Market data not found for mint: {mint}"})


@mcp.tool()
def search_spot_tokens(query: str, limit: int = 20) -> str:
    """Search for tokens by name, symbol, or mint address via Jupiter."""
    try:
        from spot_jupiter import JupiterClient
        import asyncio
        client = JupiterClient(_load_spot_cfg())
        results = asyncio.run(client.search_tokens(query, limit))
        return _pretty({"results": results, "count": len(results)})
    except Exception as e:
        return _pretty({"error": str(e)})


@mcp.tool()
def get_trending_spot_tokens(limit: int = 20) -> str:
    """Get trending/popular tokens from Jupiter."""
    try:
        from spot_jupiter import JupiterClient
        import asyncio
        client = JupiterClient(_load_spot_cfg())
        results = asyncio.run(client.get_trending_tokens(limit))
        return _pretty({"tokens": results, "count": len(results)})
    except Exception as e:
        return _pretty({"error": str(e)})


@mcp.tool()
def get_spot_market_stats() -> str:
    """Return aggregate statistics across all monitored spot markets."""
    markets = _read_json(os.path.join(PROJECT_DIR, "spot_markets.json")) or {}
    if isinstance(markets, dict):
        market_list = list(markets.values())
    elif isinstance(markets, list):
        market_list = markets
    else:
        market_list = []
    total_volume = sum(float(m.get("volume_24h", 0)) for m in market_list if isinstance(m, dict))
    avg_change = 0
    if market_list:
        changes = [float(m.get("change_24h_pct", 0)) for m in market_list if isinstance(m, dict)]
        avg_change = sum(changes) / len(changes) if changes else 0
    return _pretty({
        "total_markets": len(market_list),
        "total_volume_24h_usd": round(total_volume, 2),
        "avg_change_24h_pct": round(avg_change, 2),
    })


@mcp.tool()
def refresh_spot_markets() -> str:
    """Trigger a market data refresh from Jupiter."""
    _enqueue_command("refresh_markets")
    return "Command queued: refresh spot markets."


# ---------------------------------------------------------------------------
# 3. Price data (5)
# ---------------------------------------------------------------------------
@mcp.tool()
def get_token_price(mint: str) -> str:
    """Get the current USD price of a token."""
    try:
        from spot_jupiter import JupiterClient
        import asyncio
        client = JupiterClient(_load_spot_cfg())
        price = asyncio.run(client.get_price(mint))
        return _pretty({"mint": mint, "price_usd": price})
    except Exception as e:
        return _pretty({"error": str(e)})


@mcp.tool()
def get_token_prices(mints: str) -> str:
    """Get USD prices for multiple tokens (comma-separated mints)."""
    try:
        from spot_jupiter import JupiterClient
        import asyncio
        client = JupiterClient(_load_spot_cfg())
        mint_list = [m.strip() for m in mints.split(",") if m.strip()]
        prices = asyncio.run(client.get_prices(mint_list))
        return _pretty({"prices": prices})
    except Exception as e:
        return _pretty({"error": str(e)})


@mcp.tool()
def get_sol_price() -> str:
    """Get the current SOL price in USD."""
    try:
        from spot_jupiter import JupiterClient
        import asyncio
        client = JupiterClient(_load_spot_cfg())
        price = asyncio.run(client.get_sol_price())
        return _pretty({"sol_price_usd": price})
    except Exception as e:
        return _pretty({"error": str(e)})


@mcp.tool()
def get_token_candles(mint: str, interval: str = "5m", limit: int = 200) -> str:
    """Get OHLCV candlestick data for a token."""
    try:
        from spot_jupiter import JupiterClient
        import asyncio
        client = JupiterClient(_load_spot_cfg())
        candles = asyncio.run(client.get_ohlcv(mint, interval, limit))
        return _pretty({"mint": mint, "interval": interval,
                        "candles": candles[-50:], "count": len(candles)})
    except Exception as e:
        return _pretty({"error": str(e)})


@mcp.tool()
def get_token_market_data(mint: str) -> str:
    """Get aggregated market data for a token (price, volume, change)."""
    try:
        from spot_jupiter import JupiterClient
        import asyncio
        client = JupiterClient(_load_spot_cfg())
        data = asyncio.run(client.get_token_market_data(mint))
        return _pretty(data if data else {"error": "No data"})
    except Exception as e:
        return _pretty({"error": str(e)})


# ---------------------------------------------------------------------------
# 4. Technical analysis (7)
# ---------------------------------------------------------------------------
@mcp.tool()
def get_rsi(mint: str, period: int = 14) -> str:
    """Calculate RSI for a token based on recent candle data."""
    try:
        from spot_jupiter import JupiterClient
        from spot_snipe_bot import Indicators
        import asyncio
        client = JupiterClient(_load_spot_cfg())
        candles = asyncio.run(client.get_ohlcv(mint, "5m", max(period + 2, 200)))
        if not candles or len(candles) < period + 1:
            return _pretty({"error": "Insufficient candle data"})
        closes = [c["close"] for c in candles]
        rsi = Indicators.rsi(closes, period)
        return _pretty({"mint": mint, "rsi": round(rsi, 2), "period": period})
    except Exception as e:
        return _pretty({"error": str(e)})


@mcp.tool()
def get_macd(mint: str, fast: int = 12, slow: int = 26, signal: int = 9) -> str:
    """Calculate MACD for a token."""
    try:
        from spot_jupiter import JupiterClient
        from spot_snipe_bot import Indicators
        import asyncio
        client = JupiterClient(_load_spot_cfg())
        candles = asyncio.run(client.get_ohlcv(mint, "5m", max(slow + signal + 10, 200)))
        if not candles:
            return _pretty({"error": "Insufficient candle data"})
        closes = [c["close"] for c in candles]
        macd_line, signal_line, histogram = Indicators.macd(closes, fast, slow, signal)
        return _pretty({"mint": mint, "macd_line": round(macd_line, 6),
                        "signal_line": round(signal_line, 6),
                        "histogram": round(histogram, 6)})
    except Exception as e:
        return _pretty({"error": str(e)})


@mcp.tool()
def get_moving_averages(mint: str, short_period: int = 10, long_period: int = 50) -> str:
    """Calculate SMA and EMA for a token."""
    try:
        from spot_jupiter import JupiterClient
        from spot_snipe_bot import Indicators
        import asyncio
        client = JupiterClient(_load_spot_cfg())
        candles = asyncio.run(client.get_ohlcv(mint, "5m", max(long_period + 10, 200)))
        if not candles:
            return _pretty({"error": "Insufficient candle data"})
        closes = [c["close"] for c in candles]
        return _pretty({
            "mint": mint,
            "sma_short": round(Indicators.sma(closes, short_period), 6),
            "sma_long": round(Indicators.sma(closes, long_period), 6),
            "ema_short": round(Indicators.ema(closes, short_period), 6),
            "ema_long": round(Indicators.ema(closes, long_period), 6),
        })
    except Exception as e:
        return _pretty({"error": str(e)})


@mcp.tool()
def get_bollinger_bands(mint: str, period: int = 20, std_dev: float = 2.0) -> str:
    """Calculate Bollinger Bands for a token."""
    try:
        from spot_jupiter import JupiterClient
        from spot_snipe_bot import Indicators
        import asyncio
        client = JupiterClient(_load_spot_cfg())
        candles = asyncio.run(client.get_ohlcv(mint, "5m", max(period + 10, 200)))
        if not candles:
            return _pretty({"error": "Insufficient candle data"})
        closes = [c["close"] for c in candles]
        mid, upper, lower = Indicators.bollinger_bands(closes, period, std_dev)
        return _pretty({"mint": mint, "middle": round(mid, 6),
                        "upper": round(upper, 6), "lower": round(lower, 6)})
    except Exception as e:
        return _pretty({"error": str(e)})


@mcp.tool()
def get_volume_analysis(mint: str, period: int = 20) -> str:
    """Analyze volume patterns for a token."""
    try:
        from spot_jupiter import JupiterClient
        from spot_snipe_bot import Indicators
        import asyncio
        client = JupiterClient(_load_spot_cfg())
        candles = asyncio.run(client.get_ohlcv(mint, "5m", max(period + 10, 200)))
        if not candles:
            return _pretty({"error": "Insufficient candle data"})
        volumes = [c["volume"] for c in candles]
        vol_sma = Indicators.volume_sma(volumes, period)
        current_vol = volumes[-1] if volumes else 0
        spike_mult = current_vol / vol_sma if vol_sma > 0 else 0
        return _pretty({
            "mint": mint,
            "current_volume": round(current_vol, 2),
            "volume_sma": round(vol_sma, 2),
            "spike_multiplier": round(spike_mult, 2),
            "is_spike": spike_mult > 3.0,
        })
    except Exception as e:
        return _pretty({"error": str(e)})


@mcp.tool()
def get_all_indicators(mint: str) -> str:
    """Get all technical indicators for a token in one call."""
    try:
        from spot_jupiter import JupiterClient
        from spot_snipe_bot import Indicators
        import asyncio
        client = JupiterClient(_load_spot_cfg())
        candles = asyncio.run(client.get_ohlcv(mint, "5m", 200))
        if not candles:
            return _pretty({"error": "Insufficient candle data"})
        closes = [c["close"] for c in candles]
        volumes = [c["volume"] for c in candles]
        macd_line, signal_line, histogram = Indicators.macd(closes)
        mid, upper, lower = Indicators.bollinger_bands(closes)
        return _pretty({
            "mint": mint,
            "price": closes[-1] if closes else 0,
            "rsi": round(Indicators.rsi(closes), 2),
            "macd_line": round(macd_line, 6),
            "macd_signal": round(signal_line, 6),
            "macd_histogram": round(histogram, 6),
            "sma_10": round(Indicators.sma(closes, 10), 6),
            "sma_50": round(Indicators.sma(closes, 50), 6),
            "ema_12": round(Indicators.ema(closes, 12), 6),
            "ema_26": round(Indicators.ema(closes, 26), 6),
            "bb_mid": round(mid, 6),
            "bb_upper": round(upper, 6),
            "bb_lower": round(lower, 6),
            "volume_sma": round(Indicators.volume_sma(volumes, 20), 2),
            "current_volume": round(volumes[-1] if volumes else 0, 2),
            "atr": round(Indicators.atr(candles), 6),
        })
    except Exception as e:
        return _pretty({"error": str(e)})


@mcp.tool()
def get_atr(mint: str, period: int = 14) -> str:
    """Calculate ATR (Average True Range) for a token."""
    try:
        from spot_jupiter import JupiterClient
        from spot_snipe_bot import Indicators
        import asyncio
        client = JupiterClient(_load_spot_cfg())
        candles = asyncio.run(client.get_ohlcv(mint, "5m", max(period + 10, 200)))
        if not candles:
            return _pretty({"error": "Insufficient candle data"})
        atr = Indicators.atr(candles, period)
        return _pretty({"mint": mint, "atr": round(atr, 6), "period": period})
    except Exception as e:
        return _pretty({"error": str(e)})


# ---------------------------------------------------------------------------
# 5. Signals (5)
# ---------------------------------------------------------------------------
@mcp.tool()
def get_spot_signals() -> str:
    """Return recent spot trading signals."""
    signals = _read_json(os.path.join(PROJECT_DIR, "spot_signals.json")) or []
    return _pretty({"signals": signals[-50:], "count": len(signals)})


@mcp.tool()
def get_spot_signal_detail(index: int) -> str:
    """Return details for a specific signal by index (from most recent)."""
    signals = _read_json(os.path.join(PROJECT_DIR, "spot_signals.json")) or []
    if index < 0 or index >= len(signals):
        return _pretty({"error": "Invalid signal index"})
    return _pretty(signals[-(index + 1)])


@mcp.tool()
def enable_spot_signals(enabled: bool) -> str:
    """Enable or disable automatic signal generation."""
    cfg = _set_cfg_value("spot_auto_execute", enabled)
    return _pretty({"spot_auto_execute": cfg["spot_auto_execute"]})


@mcp.tool()
def get_signal_summary() -> str:
    """Return a summary of recent signals by type and strength."""
    signals = _read_json(os.path.join(PROJECT_DIR, "spot_signals.json")) or []
    by_type = {}
    total = len(signals)
    avg_strength = 0
    if total:
        strengths = [float(s.get("strength", 0)) for s in signals if isinstance(s, dict)]
        avg_strength = sum(strengths) / len(strengths) if strengths else 0
        for s in signals:
            if isinstance(s, dict):
                stype = s.get("signal_type", "unknown")
                by_type[stype] = by_type.get(stype, 0) + 1
    return _pretty({
        "total_signals": total,
        "avg_strength": round(avg_strength, 1),
        "by_type": by_type,
    })


@mcp.tool()
def clear_spot_signals() -> str:
    """Clear all stored spot signals."""
    _write_json(os.path.join(PROJECT_DIR, "spot_signals.json"), [])
    return "Spot signals cleared."


# ---------------------------------------------------------------------------
# 6. Configuration (6)
# ---------------------------------------------------------------------------
@mcp.tool()
def get_spot_config() -> str:
    """Return the full spot trading configuration."""
    return _pretty(_load_spot_cfg())


@mcp.tool()
def update_spot_config(key: str, value: Any) -> str:
    """Update a single spot configuration field."""
    cfg = _set_cfg_value(key, value)
    _enqueue_command("update_config", key=key, value=cfg[key])
    return _pretty({"updated": key, "value": cfg[key]})


@mcp.tool()
def batch_update_spot_config(updates: dict) -> str:
    """Update multiple spot configuration fields at once."""
    cfg = _update_batch(updates)
    return _pretty({"updated": len(updates), "config": cfg})


@mcp.tool()
def get_spot_config_catalog() -> str:
    """Return the catalog of all available spot config fields with metadata."""
    catalog = {}
    for key, rule in SPOT_CONFIG_RULES.items():
        catalog[key] = {
            "type": rule.get("type", "str"),
            "default": rule.get("default"),
            "description": rule.get("description", ""),
            "min": rule.get("min"),
            "max": rule.get("max"),
            "choices": rule.get("choices"),
            "requires_restart": rule.get("requires_restart", False),
        }
    return _pretty(catalog)


@mcp.tool()
def validate_spot_config_values() -> str:
    """Validate the current spot configuration and return warnings."""
    cfg = _load_spot_cfg()
    warnings = validate_spot_config(cfg)
    return _pretty({"valid": len(warnings) == 0, "warnings": warnings})


@mcp.tool()
def get_spot_config_field(key: str) -> str:
    """Get the current value and metadata for a single config field."""
    cfg = _load_spot_cfg()
    rule = SPOT_CONFIG_RULES.get(key, {})
    return _pretty({
        "key": key,
        "value": cfg.get(key),
        "default": rule.get("default"),
        "description": rule.get("description", ""),
        "type": rule.get("type", "str"),
    })


# ---------------------------------------------------------------------------
# 7. Positions (5)
# ---------------------------------------------------------------------------
@mcp.tool()
def get_spot_positions() -> str:
    """Return all open spot positions."""
    positions = _read_json(os.path.join(PROJECT_DIR, "spot_positions.json")) or []
    return _pretty({"positions": positions, "count": len(positions)})


@mcp.tool()
def get_spot_position_detail(mint: str) -> str:
    """Return details for a specific spot position by token mint."""
    positions = _read_json(os.path.join(PROJECT_DIR, "spot_positions.json")) or []
    for p in positions:
        if p.get("mint") == mint:
            return _pretty(p)
    return _pretty({"error": f"Position not found for mint: {mint}"})


@mcp.tool()
def get_spot_position_pnl(mint: str) -> str:
    """Return P&L for a specific spot position."""
    positions = _read_json(os.path.join(PROJECT_DIR, "spot_positions.json")) or []
    for p in positions:
        if p.get("mint") == mint:
            return _pretty({
                "mint": mint,
                "realized_pnl": p.get("realized_pnl", 0),
                "unrealized_pnl": p.get("unrealized_pnl", 0),
                "entry_price": p.get("entry_price", 0),
                "current_price": p.get("current_price", 0),
            })
    return _pretty({"error": f"Position not found for mint: {mint}"})


@mcp.tool()
def get_spot_exposure() -> str:
    """Return total exposure across all open spot positions."""
    positions = _read_json(os.path.join(PROJECT_DIR, "spot_positions.json")) or []
    total_cost = sum(float(p.get("cost_usd", 0)) for p in positions if not p.get("sold"))
    total_unrealized = sum(float(p.get("unrealized_pnl", 0)) for p in positions if not p.get("sold"))
    return _pretty({
        "open_positions": len([p for p in positions if not p.get("sold")]),
        "total_cost_usd": round(total_cost, 2),
        "total_unrealized_pnl_usd": round(total_unrealized, 2),
    })


@mcp.tool()
def close_spot_position(mint: str) -> str:
    """Close a specific spot position by token mint."""
    _enqueue_command("close_position", mint=mint)
    return f"Command queued: close position for {mint}."


# ---------------------------------------------------------------------------
# 8. Orders (5)
# ---------------------------------------------------------------------------
@mcp.tool()
def spot_market_buy(mint: str, usd_amount: float) -> str:
    """Execute a manual market buy order for a token."""
    _enqueue_command("buy", mint=mint, price=0, amount=usd_amount)
    return f"Command queued: market buy {mint} for ${usd_amount}."


@mcp.tool()
def spot_market_sell(mint: str) -> str:
    """Execute a manual market sell order for a token (sell all holdings)."""
    _enqueue_command("close_position", mint=mint)
    return f"Command queued: market sell {mint}."


@mcp.tool()
def spot_limit_buy(mint: str, usd_amount: float, limit_price: float) -> str:
    """Place a limit buy order for a token (queued for engine execution)."""
    _enqueue_command("buy", mint=mint, price=limit_price, amount=usd_amount)
    return f"Command queued: limit buy {mint} for ${usd_amount} at ${limit_price}."


@mcp.tool()
def cancel_spot_order(mint: str) -> str:
    """Cancel a pending spot order for a token."""
    _enqueue_command("cancel_order", mint=mint)
    return f"Command queued: cancel order for {mint}."


@mcp.tool()
def get_spot_open_orders() -> str:
    """Return any pending spot orders."""
    return _pretty({"orders": [], "count": 0, "note": "Spot orders are executed immediately via Jupiter"})


# ---------------------------------------------------------------------------
# 9. Trade history (4)
# ---------------------------------------------------------------------------
@mcp.tool()
def get_spot_trade_history(limit: int = 50) -> str:
    """Return recent spot trade history."""
    history = _read_json(os.path.join(PROJECT_DIR, "spot_trade_history.json")) or []
    return _pretty({"trades": history[-limit:], "count": len(history)})


@mcp.tool()
def get_spot_trade_detail(index: int) -> str:
    """Return details for a specific trade by index."""
    history = _read_json(os.path.join(PROJECT_DIR, "spot_trade_history.json")) or []
    if index < 0 or index >= len(history):
        return _pretty({"error": "Invalid trade index"})
    return _pretty(history[-(index + 1)])


@mcp.tool()
def clear_spot_trade_history() -> str:
    """Clear all spot trade history."""
    _write_json(os.path.join(PROJECT_DIR, "spot_trade_history.json"), [])
    return "Spot trade history cleared."


@mcp.tool()
def get_spot_trade_pnl_tally() -> str:
    """Return the aggregate P&L tally for spot trading."""
    tally = _read_json(os.path.join(PROJECT_DIR, "spot_pnl_tally.json")) or {}
    return _pretty(tally)


# ---------------------------------------------------------------------------
# 10. P&L (3)
# ---------------------------------------------------------------------------
@mcp.tool()
def get_spot_total_pnl() -> str:
    """Return total realized and unrealized P&L for spot trading."""
    tally = _read_json(os.path.join(PROJECT_DIR, "spot_pnl_tally.json")) or {}
    positions = _read_json(os.path.join(PROJECT_DIR, "spot_positions.json")) or []
    unrealized = sum(float(p.get("unrealized_pnl", 0)) for p in positions if not p.get("sold"))
    return _pretty({
        "total_realized_pnl_usd": tally.get("total_realized_pnl_usd", 0),
        "total_unrealized_pnl_usd": round(unrealized, 2),
        "total_trades": tally.get("total_trades", 0),
        "wins": tally.get("wins", 0),
        "losses": tally.get("losses", 0),
    })


@mcp.tool()
def get_spot_win_rate() -> str:
    """Return the win rate for spot trading."""
    tally = _read_json(os.path.join(PROJECT_DIR, "spot_pnl_tally.json")) or {}
    total = tally.get("total_trades", 0)
    wins = tally.get("wins", 0)
    rate = (wins / total * 100) if total > 0 else 0
    return _pretty({
        "total_trades": total,
        "wins": wins,
        "losses": tally.get("losses", 0),
        "win_rate_pct": round(rate, 1),
    })


@mcp.tool()
def get_spot_best_worst_trades() -> str:
    """Return the best and worst spot trades."""
    tally = _read_json(os.path.join(PROJECT_DIR, "spot_pnl_tally.json")) or {}
    return _pretty({
        "best_trade_usd": tally.get("best_trade_usd", 0),
        "worst_trade_usd": tally.get("worst_trade_usd", 0),
    })


# ---------------------------------------------------------------------------
# 11. Risk (4)
# ---------------------------------------------------------------------------
@mcp.tool()
def get_spot_risk_status() -> str:
    """Return current risk metrics for spot trading."""
    cfg = _load_spot_cfg()
    positions = _read_json(os.path.join(PROJECT_DIR, "spot_positions.json")) or []
    open_count = len([p for p in positions if not p.get("sold")])
    total_cost = sum(float(p.get("cost_usd", 0)) for p in positions if not p.get("sold"))
    max_exposure = float(cfg.get("spot_max_total_exposure_usd", 0))
    max_positions = int(cfg.get("spot_max_positions", 5))
    return _pretty({
        "open_positions": open_count,
        "max_positions": max_positions,
        "total_exposure_usd": round(total_cost, 2),
        "max_exposure_usd": max_exposure,
        "exposure_utilization_pct": round((total_cost / max_exposure * 100) if max_exposure > 0 else 0, 1),
        "stop_loss_enabled": cfg.get("spot_stop_loss_enabled", True),
        "hard_stop_loss_pct": cfg.get("spot_hard_stop_loss_pct", 5),
        "trailing_stop_enabled": cfg.get("spot_trailing_stop_enabled", True),
    })


@mcp.tool()
def set_spot_max_positions(max_positions: int) -> str:
    """Set the maximum number of simultaneous spot positions."""
    cfg = _set_cfg_value("spot_max_positions", max_positions)
    return _pretty({"updated": "spot_max_positions", "value": cfg["spot_max_positions"]})


@mcp.tool()
def set_spot_max_exposure(max_exposure_usd: float) -> str:
    """Set the maximum total exposure for spot trading."""
    cfg = _set_cfg_value("spot_max_total_exposure_usd", max_exposure_usd)
    return _pretty({"updated": "spot_max_total_exposure_usd", "value": cfg["spot_max_total_exposure_usd"]})


@mcp.tool()
def get_spot_portfolio_concentration() -> str:
    """Return portfolio concentration analysis for spot positions."""
    positions = _read_json(os.path.join(PROJECT_DIR, "spot_positions.json")) or []
    open_positions = [p for p in positions if not p.get("sold")]
    if not open_positions:
        return _pretty({"error": "No open positions"})
    total_cost = sum(float(p.get("cost_usd", 0)) for p in open_positions)
    concentrations = []
    for p in open_positions:
        cost = float(p.get("cost_usd", 0))
        pct = (cost / total_cost * 100) if total_cost > 0 else 0
        concentrations.append({
            "mint": p.get("mint", ""),
            "symbol": p.get("symbol", ""),
            "cost_usd": round(cost, 2),
            "concentration_pct": round(pct, 1),
        })
    concentrations.sort(key=lambda x: x["concentration_pct"], reverse=True)
    return _pretty({"total_cost_usd": round(total_cost, 2), "concentrations": concentrations})


# ---------------------------------------------------------------------------
# 12. Wallet (3)
# ---------------------------------------------------------------------------
@mcp.tool()
def get_spot_wallet_balances(wallet_pubkey: str = "") -> str:
    """Return spot wallet balances (USDC, SOL, and token holdings)."""
    if not wallet_pubkey:
        return _pretty({"error": "Wallet public key required"})
    try:
        from spot_jupiter import JupiterClient
        import asyncio
        client = JupiterClient(_load_spot_cfg())
        sol_balance = asyncio.run(client.get_wallet_sol_balance(wallet_pubkey))
        tokens = asyncio.run(client.get_wallet_all_tokens(wallet_pubkey))
        return _pretty({
            "wallet": wallet_pubkey,
            "sol_balance": round(sol_balance, 4),
            "token_accounts": tokens,
        })
    except Exception as e:
        return _pretty({"error": str(e)})


@mcp.tool()
def get_spot_token_balance(wallet_pubkey: str, token_mint: str) -> str:
    """Get a specific token balance for a wallet."""
    try:
        from spot_jupiter import JupiterClient
        import asyncio
        client = JupiterClient(_load_spot_cfg())
        balance = asyncio.run(client.get_wallet_token_balance(wallet_pubkey, token_mint))
        return _pretty({"wallet": wallet_pubkey, "mint": token_mint, "balance": balance})
    except Exception as e:
        return _pretty({"error": str(e)})


@mcp.tool()
def transfer_spot_to_savings(amount_usd: float) -> str:
    """Transfer funds from spot trading wallet to savings wallet."""
    _enqueue_command("transfer_to_savings", amount=amount_usd)
    return f"Command queued: transfer ${amount_usd} to savings."


# ---------------------------------------------------------------------------
# 13. Logs (2)
# ---------------------------------------------------------------------------
@mcp.tool()
def get_spot_logs(lines: int = 50) -> str:
    """Return recent spot bot log lines."""
    log_path = os.path.join(PROJECT_DIR, "spot_bot.log")
    try:
        with open(log_path, "r", encoding="utf-8") as f:
            all_lines = f.readlines()
        return _pretty({"logs": all_lines[-lines:], "count": len(all_lines)})
    except FileNotFoundError:
        return _pretty({"logs": [], "note": "No log file yet"})


@mcp.tool()
def clear_spot_logs() -> str:
    """Clear the spot bot log file."""
    log_path = os.path.join(PROJECT_DIR, "spot_bot.log")
    try:
        with open(log_path, "w", encoding="utf-8") as f:
            f.write("")
        return "Spot logs cleared."
    except Exception as e:
        return _pretty({"error": str(e)})


# ---------------------------------------------------------------------------
# 14. Alerts (2)
# ---------------------------------------------------------------------------
@mcp.tool()
def get_spot_alerts() -> str:
    """Return recent spot trading alerts."""
    signals = _read_json(os.path.join(PROJECT_DIR, "spot_signals.json")) or []
    cfg = _load_spot_cfg()
    threshold = float(cfg.get("spot_alert_threshold_score", 50))
    alerts = [s for s in signals if float(s.get("strength", 0)) >= threshold]
    return _pretty({"alerts": alerts[-50:], "count": len(alerts), "threshold": threshold})


@mcp.tool()
def set_spot_alert_threshold(score: float) -> str:
    """Set the minimum signal score to trigger an alert."""
    cfg = _set_cfg_value("spot_alert_threshold_score", score)
    return _pretty({"updated": "spot_alert_threshold_score", "value": cfg["spot_alert_threshold_score"]})


# ---------------------------------------------------------------------------
# 15. DCA (3)
# ---------------------------------------------------------------------------
@mcp.tool()
def enable_spot_dca(enabled: bool) -> str:
    """Enable or disable DCA (Dollar Cost Averaging) for spot positions."""
    cfg = _set_cfg_value("spot_dca_enabled", enabled)
    return _pretty({"updated": "spot_dca_enabled", "value": cfg["spot_dca_enabled"]})


@mcp.tool()
def set_spot_dca_steps(steps: int) -> str:
    """Set the maximum number of DCA steps per position."""
    cfg = _set_cfg_value("spot_dca_steps", steps)
    return _pretty({"updated": "spot_dca_steps", "value": cfg["spot_dca_steps"]})


@mcp.tool()
def set_spot_dca_interval(seconds: int) -> str:
    """Set the DCA interval in seconds."""
    cfg = _set_cfg_value("spot_dca_interval_sec", seconds)
    return _pretty({"updated": "spot_dca_interval_sec", "value": cfg["spot_dca_interval_sec"]})


# ---------------------------------------------------------------------------
# 16. Risk level (2)
# ---------------------------------------------------------------------------
@mcp.tool()
def set_spot_risk_level(level: int) -> str:
    """Set the spot risk level (1-20) and apply the coordinated profile."""
    if level < RISK_LEVEL_MIN or level > RISK_LEVEL_MAX:
        return _pretty({"error": f"Risk level must be between {RISK_LEVEL_MIN} and {RISK_LEVEL_MAX}"})
    cfg = _load_spot_cfg()
    profile = build_spot_risk_level_profile(level, base_cfg=cfg)
    cfg.update(profile)
    _save_spot_cfg(cfg)
    _enqueue_command("apply_risk_level", level=level)
    return _pretty({"risk_level": level, "name": risk_level_name(level), "applied": True})


@mcp.tool()
def get_spot_risk_levels() -> str:
    """Return all 20 spot risk levels with their names."""
    levels = []
    for lvl in range(RISK_LEVEL_MIN, RISK_LEVEL_MAX + 1):
        levels.append({"level": lvl, "name": risk_level_name(lvl)})
    return _pretty({"levels": levels, "min": RISK_LEVEL_MIN, "max": RISK_LEVEL_MAX})


# ---------------------------------------------------------------------------
# 17. Rebalancing (2)
# ---------------------------------------------------------------------------
@mcp.tool()
def enable_spot_rebalancing(enabled: bool) -> str:
    """Enable or disable portfolio rebalancing."""
    cfg = _set_cfg_value("spot_rebalance_enabled", enabled)
    return _pretty({"updated": "spot_rebalance_enabled", "value": cfg["spot_rebalance_enabled"]})


@mcp.tool()
def set_spot_rebalance_threshold(threshold_pct: float) -> str:
    """Set the rebalancing threshold percentage."""
    cfg = _set_cfg_value("spot_rebalance_threshold_pct", threshold_pct)
    return _pretty({"updated": "spot_rebalance_threshold_pct", "value": cfg["spot_rebalance_threshold_pct"]})


# ---------------------------------------------------------------------------
# 18. Token management (3)
# ---------------------------------------------------------------------------
@mcp.tool()
def add_allowed_spot_token(mint: str) -> str:
    """Add a token to the allowed list for spot trading."""
    cfg = _load_spot_cfg()
    allowed = cfg.get("spot_allowed_tokens", "")
    mints = [m.strip() for m in allowed.split(",") if m.strip()]
    if mint not in mints:
        mints.append(mint)
    cfg["spot_allowed_tokens"] = ",".join(mints)
    _save_spot_cfg(cfg)
    return _pretty({"allowed_tokens": cfg["spot_allowed_tokens"]})


@mcp.tool()
def add_blocked_spot_token(mint: str) -> str:
    """Add a token to the blocked list for spot trading."""
    cfg = _load_spot_cfg()
    blocked = cfg.get("spot_blocked_tokens", "")
    mints = [m.strip() for m in blocked.split(",") if m.strip()]
    if mint not in mints:
        mints.append(mint)
    cfg["spot_blocked_tokens"] = ",".join(mints)
    _save_spot_cfg(cfg)
    return _pretty({"blocked_tokens": cfg["spot_blocked_tokens"]})


@mcp.tool()
def remove_allowed_spot_token(mint: str) -> str:
    """Remove a token from the allowed list."""
    cfg = _load_spot_cfg()
    allowed = cfg.get("spot_allowed_tokens", "")
    mints = [m.strip() for m in allowed.split(",") if m.strip() and m.strip() != mint]
    cfg["spot_allowed_tokens"] = ",".join(mints)
    _save_spot_cfg(cfg)
    return _pretty({"allowed_tokens": cfg["spot_allowed_tokens"]})


# ---------------------------------------------------------------------------
# 19. Quote/swap (3)
# ---------------------------------------------------------------------------
@mcp.tool()
def get_spot_quote(input_mint: str, output_mint: str, amount: int,
                   slippage_bps: int = 100) -> str:
    """Get a swap quote from Jupiter DEX."""
    try:
        from spot_jupiter import JupiterClient
        import asyncio
        client = JupiterClient(_load_spot_cfg())
        quote = asyncio.run(client.get_quote(input_mint, output_mint, amount, slippage_bps))
        return _pretty(quote if quote else {"error": "No quote returned"})
    except Exception as e:
        return _pretty({"error": str(e)})


@mcp.tool()
def get_spot_swap_transaction(input_mint: str, output_mint: str, amount: int,
                              user_wallet: str, slippage_bps: int = 100) -> str:
    """Get a serialized swap transaction from Jupiter."""
    try:
        from spot_jupiter import JupiterClient
        import asyncio
        client = JupiterClient(_load_spot_cfg())
        quote = asyncio.run(client.get_quote(input_mint, output_mint, amount, slippage_bps))
        if not quote:
            return _pretty({"error": "No quote available"})
        swap_tx = asyncio.run(client.get_swap_transaction(quote, user_wallet))
        return _pretty(swap_tx if swap_tx else {"error": "No swap transaction returned"})
    except Exception as e:
        return _pretty({"error": str(e)})


@mcp.tool()
def set_spot_slippage(bps: int) -> str:
    """Set the maximum slippage in basis points for spot swaps."""
    cfg = _set_cfg_value("spot_slippage_bps", bps)
    return _pretty({"updated": "spot_slippage_bps", "value": cfg["spot_slippage_bps"]})


# ---------------------------------------------------------------------------
# 20. Statistics (2)
# ---------------------------------------------------------------------------
@mcp.tool()
def get_spot_statistics() -> str:
    """Return comprehensive spot trading statistics."""
    tally = _read_json(os.path.join(PROJECT_DIR, "spot_pnl_tally.json")) or {}
    positions = _read_json(os.path.join(PROJECT_DIR, "spot_positions.json")) or []
    signals = _read_json(os.path.join(PROJECT_DIR, "spot_signals.json")) or []
    history = _read_json(os.path.join(PROJECT_DIR, "spot_trade_history.json")) or []
    open_positions = [p for p in positions if not p.get("sold")]
    total_unrealized = sum(float(p.get("unrealized_pnl", 0)) for p in open_positions)
    return _pretty({
        "total_realized_pnl_usd": tally.get("total_realized_pnl_usd", 0),
        "total_unrealized_pnl_usd": round(total_unrealized, 2),
        "total_trades": tally.get("total_trades", 0),
        "wins": tally.get("wins", 0),
        "losses": tally.get("losses", 0),
        "best_trade_usd": tally.get("best_trade_usd", 0),
        "worst_trade_usd": tally.get("worst_trade_usd", 0),
        "open_positions": len(open_positions),
        "total_signals": len(signals),
        "total_history": len(history),
    })


@mcp.tool()
def reset_spot_pnl_tally() -> str:
    """Reset the spot P&L tally to zero."""
    empty_tally = {
        "total_realized_pnl_usd": 0.0,
        "total_fees_paid_usd": 0.0,
        "total_trades": 0,
        "wins": 0,
        "losses": 0,
        "best_trade_usd": 0.0,
        "worst_trade_usd": 0.0,
    }
    _write_json(os.path.join(PROJECT_DIR, "spot_pnl_tally.json"), empty_tally)
    return "Spot P&L tally reset to zero."


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
