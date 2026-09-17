"""Perpetuals MCP Server — V4.

Exposes 50 MCP tools for controlling and querying AI Crypto Sniper
perpetuals module (Raydium Perps / Orderly Network). Tools are grouped by:

1. Bot control
2. Market data
3. Configuration
4. Positions
5. Orders
6. Trade history & P&L
7. Wallet & risk
8. Signals
9. Risk
10. Logs

The server works by reading/writing the perp configuration file and a
perp command queue. The live PerpSnipeBot engine picks up queued commands.
"""

import json
import os
import sys
import time
from typing import Any

# Allow imports of V4 root perp modules when running from this package
PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
V4_ROOT = os.path.dirname(PACKAGE_DIR)
if V4_ROOT not in sys.path:
    sys.path.insert(0, V4_ROOT)

from mcp.server.fastmcp import FastMCP

from perp_config_schema import (
    PERP_CONFIG_RULES,
    RISK_LEVEL_MAX,
    RISK_LEVEL_MIN,
    build_perp_risk_level_profile,
    parse_perp_config_value,
    risk_level_name,
    validate_perp_config,
)
from perp_credentials import (
    ORDERLY_SECRET_KEYS,
    load_orderly_credentials,
    public_perp_config,
    save_orderly_credentials,
)

PROJECT_DIR = (os.environ.get("AI_CRYPTO_SNIPER_DIR")
               or os.environ.get("SOLANA_SNIPER_BOT_DIR")
               or os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PERP_CONFIG_PATH = os.path.join(PROJECT_DIR, "perp_config.json")
PERP_COMMAND_FILE = os.path.join(PROJECT_DIR, "perp_command_queue.json")

mcp = FastMCP("ai-crypto-sniper-perp")


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


def _load_perp_cfg() -> dict:
    defaults = {k: v.get("default") for k, v in PERP_CONFIG_RULES.items()}
    cfg = _read_json(PERP_CONFIG_PATH) or {}
    for k, v in defaults.items():
        if k not in cfg:
            cfg[k] = v
    return cfg


def _save_perp_cfg(cfg: dict) -> None:
    _write_json(PERP_CONFIG_PATH, public_perp_config(cfg))


def _enqueue_command(cmd: str, **params: Any) -> None:
    queue = _read_json(PERP_COMMAND_FILE) or []
    queue.append({"cmd": cmd, "params": params, "timestamp": time.time()})
    queue = queue[-100:]
    _write_json(PERP_COMMAND_FILE, queue)


def _set_cfg_value(key: str, value: Any) -> dict:
    cfg = _load_perp_cfg()
    parsed = parse_perp_config_value(key, value)
    if key in ORDERLY_SECRET_KEYS:
        credentials = load_orderly_credentials()
        credentials[key] = parsed
        save_orderly_credentials(credentials)
        cfg[key] = "<stored securely>" if parsed else ""
    else:
        cfg[key] = parsed
    _save_perp_cfg(cfg)
    return cfg


def _update_batch(updates: dict) -> dict:
    cfg = _load_perp_cfg()
    credentials = load_orderly_credentials()
    secrets_changed = False
    for k, v in updates.items():
        if k in PERP_CONFIG_RULES:
            parsed = parse_perp_config_value(k, v)
            if k in ORDERLY_SECRET_KEYS:
                credentials[k] = parsed
                cfg[k] = "<stored securely>" if parsed else ""
                secrets_changed = True
            else:
                cfg[k] = parsed
    if secrets_changed:
        save_orderly_credentials(credentials)
    _save_perp_cfg(cfg)
    return cfg


def _pretty(d: Any) -> str:
    return json.dumps(d, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# 1. Bot control (4)
# ---------------------------------------------------------------------------
@mcp.tool()
def start_perp_bot() -> str:
    """Start the perpetuals trading bot."""
    _enqueue_command("start_perp_bot")
    return "Command queued: start_perp_bot."


@mcp.tool()
def stop_perp_bot() -> str:
    """Stop the perpetuals trading bot."""
    _enqueue_command("stop_perp_bot")
    return "Command queued: stop_perp_bot."


@mcp.tool()
def sell_all_perps() -> str:
    """Panic close all open perpetual positions immediately."""
    _enqueue_command("sell_all_perps")
    return "Command queued: sell_all_perps."


@mcp.tool()
def get_perp_bot_status() -> str:
    """Return the current perpetuals bot status (running, stopped, etc.)."""
    status = _read_json(os.path.join(PROJECT_DIR, "perp_bot_status.json")) or {}
    return _pretty(status)


# ---------------------------------------------------------------------------
# 2. Market data (8)
# ---------------------------------------------------------------------------
@mcp.tool()
def get_perp_markets() -> str:
    """Return the list of available perpetual markets."""
    markets = _read_json(os.path.join(PROJECT_DIR, "perp_markets.json")) or []
    return _pretty({"markets": markets, "count": len(markets)})


@mcp.tool()
def get_perp_market_detail(symbol: str) -> str:
    """Return detailed data for a specific perp market."""
    markets = _read_json(os.path.join(PROJECT_DIR, "perp_markets.json")) or []
    for m in markets:
        if (m.get("symbol") or "").upper() == symbol.upper():
            return _pretty(m)
    return _pretty({"error": f"Market {symbol} not found"})


@mcp.tool()
def get_perp_orderbook(symbol: str) -> str:
    """Return the latest orderbook snapshot for a perp market."""
    data = _read_json(os.path.join(PROJECT_DIR,
                                   f"perp_orderbook_{symbol.upper()}.json")) or {}
    return _pretty(data)


@mcp.tool()
def get_perp_candles(symbol: str, interval: str = "1m", limit: int = 100) -> str:
    """Return recent candle (kline) data for a perp market."""
    data = _read_json(os.path.join(PROJECT_DIR,
                                   f"perp_candles_{symbol.upper()}_{interval}.json")) or {}
    return _pretty({"symbol": symbol, "interval": interval,
                    "limit": limit, "data": data})


@mcp.tool()
def get_funding_rates() -> str:
    """Return current funding rates for all perp markets."""
    data = _read_json(os.path.join(PROJECT_DIR, "perp_funding_rates.json")) or []
    return _pretty({"count": len(data), "rates": data})


@mcp.tool()
def get_funding_history(symbol: str, limit: int = 30) -> str:
    """Return recent funding payment history for a perp market."""
    data = _read_json(os.path.join(PROJECT_DIR,
                                   f"perp_funding_history_{symbol.upper()}.json")) or []
    return _pretty({"symbol": symbol, "limit": limit, "history": data})


@mcp.tool()
def get_liquidations(limit: int = 50) -> str:
    """Return recent large liquidation events."""
    data = _read_json(os.path.join(PROJECT_DIR, "perp_liquidations.json")) or []
    return _pretty({"count": len(data), "liquidations": data[:limit]})


@mcp.tool()
def get_perp_price_changes() -> str:
    """Return multi-timeframe price changes for all perp markets."""
    data = _read_json(os.path.join(PROJECT_DIR, "perp_price_changes.json")) or []
    return _pretty({"count": len(data), "changes": data})


# ---------------------------------------------------------------------------
# 3. Configuration (6)
# ---------------------------------------------------------------------------
@mcp.tool()
def get_perp_config() -> str:
    """Return the current perp configuration."""
    return _pretty(_load_perp_cfg())


@mcp.tool()
def update_perp_config(key: str, value: Any) -> str:
    """Update a single perp configuration value."""
    if key not in PERP_CONFIG_RULES:
        return _pretty({"error": f"Unknown perp config key: {key}"})
    cfg = _set_cfg_value(key, value)
    warnings = validate_perp_config(cfg)
    return _pretty({"updated": key, "value": cfg[key],
                    "warnings": warnings})


@mcp.tool()
def get_perp_config_catalog() -> str:
    """Return the catalog of all available perp config keys."""
    return _pretty({k: {"type": v["type"], "default": v.get("default"),
                        "min": v.get("min"), "max": v.get("max"),
                        "choices": v.get("choices"),
                        "description": v.get("description", "")}
                    for k, v in PERP_CONFIG_RULES.items()})


@mcp.tool()
def validate_perp_config_tool() -> str:
    """Validate the current perp configuration and return any warnings."""
    cfg = _load_perp_cfg()
    warnings = validate_perp_config(cfg)
    return _pretty({"valid": len(warnings) == 0, "warnings": warnings})


@mcp.tool()
def preview_perp_risk_level(level: int) -> str:
    """Preview the perp configuration for a specific risk level (1-20)."""
    try:
        level = int(level)
    except (ValueError, TypeError):
        return _pretty({"error": "level must be an integer"})
    if level < RISK_LEVEL_MIN or level > RISK_LEVEL_MAX:
        return _pretty({"error": f"level must be between {RISK_LEVEL_MIN} and {RISK_LEVEL_MAX}"})
    profile = build_perp_risk_level_profile(level, base_cfg=_load_perp_cfg())
    return _pretty({
        "level": level,
        "name": risk_level_name(level),
        "leverage": profile.get("perp_default_leverage"),
        "max_leverage": profile.get("perp_max_leverage"),
        "margin_mode": profile.get("perp_margin_mode"),
        "pct_of_wallet": profile.get("perp_pct_of_wallet"),
        "stop_loss_pct": profile.get("perp_hard_stop_loss_pct"),
        "tp_ladder_steps": profile.get("perp_tp_ladder_steps"),
    })


@mcp.tool()
def apply_perp_risk_level(level: int) -> str:
    """Apply a risk level (1-20) to the perp configuration."""
    try:
        level = int(level)
    except (ValueError, TypeError):
        return _pretty({"error": "level must be an integer"})
    if level < RISK_LEVEL_MIN or level > RISK_LEVEL_MAX:
        return _pretty({"error": f"level must be between {RISK_LEVEL_MIN} and {RISK_LEVEL_MAX}"})
    base = _load_perp_cfg()
    profile = build_perp_risk_level_profile(level, base_cfg=base)
    profile["perp_risk_level"] = level
    _save_perp_cfg(profile)
    _enqueue_command("apply_perp_risk_level", level=level)
    return _pretty({"updated": True, "level": level,
                    "name": risk_level_name(level)})


# ---------------------------------------------------------------------------
# 4. Positions (9)
# ---------------------------------------------------------------------------
@mcp.tool()
def get_perp_positions() -> str:
    """Return all open perpetual positions."""
    positions = _read_json(os.path.join(PROJECT_DIR, "perp_positions.json")) or []
    return _pretty({"count": len(positions), "positions": positions})


@mcp.tool()
def open_perp_long(symbol: str, notional_usd: float) -> str:
    """Open a long perpetual position by symbol and notional size."""
    _enqueue_command("open_perp_long", symbol=symbol,
                     notional_usd=float(notional_usd))
    return f"Command queued: open long {symbol} for {notional_usd} USDC."


@mcp.tool()
def open_perp_short(symbol: str, notional_usd: float) -> str:
    """Open a short perpetual position by symbol and notional size."""
    _enqueue_command("open_perp_short", symbol=symbol,
                     notional_usd=float(notional_usd))
    return f"Command queued: open short {symbol} for {notional_usd} USDC."


@mcp.tool()
def close_perp_position(symbol: str, pct: float = 100.0) -> str:
    """Close (reduce) a perp position by symbol and percentage."""
    _enqueue_command("close_perp_position", symbol=symbol, pct=float(pct))
    return f"Command queued: close {pct}% of {symbol}."


@mcp.tool()
def get_perp_position_detail(symbol: str) -> str:
    """Return detailed data for a specific perp position."""
    positions = _read_json(os.path.join(PROJECT_DIR, "perp_positions.json")) or []
    for p in positions:
        if (p.get("symbol") or "").upper() == symbol.upper():
            return _pretty(p)
    return _pretty({"error": f"Position {symbol} not found"})


@mcp.tool()
def get_perp_position_pnl(symbol: str) -> str:
    """Return the P&L for a specific perp position."""
    positions = _read_json(os.path.join(PROJECT_DIR, "perp_positions.json")) or []
    for p in positions:
        if (p.get("symbol") or "").upper() == symbol.upper():
            return _pretty({"symbol": symbol,
                            "unrealized_pnl": p.get("unrealized_pnl", 0),
                            "realized_pnl": p.get("realized_pnl", 0),
                            "pnl_pct": p.get("pnl_pct", 0)})
    return _pretty({"error": f"Position {symbol} not found"})


@mcp.tool()
def set_perp_leverage(symbol: str, leverage: float) -> str:
    """Set leverage for an existing perp position or as default."""
    _enqueue_command("set_perp_leverage", symbol=symbol, leverage=float(leverage))
    return f"Command queued: set leverage for {symbol} to {leverage}x."


@mcp.tool()
def set_perp_margin_mode(mode: str) -> str:
    """Set perp margin mode to isolated or cross."""
    if mode not in ("isolated", "cross"):
        return _pretty({"error": "mode must be 'isolated' or 'cross'"})
    _update_batch({"perp_margin_mode": mode})
    _enqueue_command("set_perp_margin_mode", mode=mode)
    return _pretty({"updated": "perp_margin_mode", "mode": mode})


@mcp.tool()
def get_perp_exposure() -> str:
    """Return total perp exposure and margin usage summary."""
    status = _read_json(os.path.join(PROJECT_DIR, "perp_positions.json")) or []
    total = sum(float(p.get("notional", 0)) for p in status)
    margin = sum(float(p.get("margin", 0) or 0) for p in status)
    return _pretty({"total_notional": total, "total_margin": margin,
                    "position_count": len(status)})


# ---------------------------------------------------------------------------
# 5. Orders (4)
# ---------------------------------------------------------------------------
@mcp.tool()
def get_perp_open_orders() -> str:
    """Return all open perp orders."""
    orders = _read_json(os.path.join(PROJECT_DIR, "perp_open_orders.json")) or []
    return _pretty({"count": len(orders), "orders": orders})


@mcp.tool()
def cancel_perp_order(order_id: str) -> str:
    """Cancel a specific perp order by order ID."""
    _enqueue_command("cancel_perp_order", order_id=order_id)
    return f"Command queued: cancel order {order_id}."


@mcp.tool()
def cancel_all_perp_orders(symbol: str = "") -> str:
    """Cancel all open perp orders, optionally filtered by symbol."""
    _enqueue_command("cancel_all_perp_orders", symbol=symbol)
    return "Command queued: cancel all perp orders."


@mcp.tool()
def get_perp_order_history(limit: int = 50) -> str:
    """Return recent perp order history."""
    history = _read_json(os.path.join(PROJECT_DIR, "perp_order_history.json")) or []
    return _pretty({"count": len(history), "history": history[:limit]})


# ---------------------------------------------------------------------------
# 6. Trade history & P&L (5)
# ---------------------------------------------------------------------------
@mcp.tool()
def get_perp_trade_history(limit: int = 100) -> str:
    """Return perp trade history."""
    trades = _read_json(os.path.join(PROJECT_DIR, "perp_trade_history.json")) or []
    return _pretty({"count": len(trades), "trades": trades[:limit]})


@mcp.tool()
def clear_perp_trade_history() -> str:
    """Clear the perp trade history file."""
    _write_json(os.path.join(PROJECT_DIR, "perp_trade_history.json"), [])
    return "Perp trade history cleared."


@mcp.tool()
def get_perp_pnl_tally() -> str:
    """Return the all-time perp P&L tally."""
    tally = _read_json(os.path.join(PROJECT_DIR, "perp_pnl_tally.json")) or {}
    return _pretty(tally)


@mcp.tool()
def reset_perp_pnl_tally() -> str:
    """Reset the all-time perp P&L tally to zero."""
    _write_json(os.path.join(PROJECT_DIR, "perp_pnl_tally.json"),
                {"realized_pnl": 0, "unrealized_pnl": 0, "fees_paid": 0,
                 "win_count": 0, "loss_count": 0})
    return "Perp P&L tally reset."


@mcp.tool()
def analyze_perp_performance() -> str:
    """Analyze perp trade performance and return summary stats."""
    trades = _read_json(os.path.join(PROJECT_DIR, "perp_trade_history.json")) or []
    if not trades:
        return _pretty({"error": "No perp trades found"})
    wins = [t for t in trades if float(t.get("pnl", 0)) > 0]
    losses = [t for t in trades if float(t.get("pnl", 0)) <= 0]
    total_pnl = sum(float(t.get("pnl", 0)) for t in trades)
    return _pretty({
        "total_trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(100 * len(wins) / len(trades), 2) if trades else 0,
        "total_pnl": round(total_pnl, 4),
        "avg_pnl": round(total_pnl / len(trades), 4) if trades else 0,
    })


# ---------------------------------------------------------------------------
# 7. Wallet & risk (4)
# ---------------------------------------------------------------------------
@mcp.tool()
def get_perp_wallet_balances() -> str:
    """Return the perp trading and savings wallet balances."""
    balances = _read_json(os.path.join(PROJECT_DIR, "perp_wallet_balances.json")) or {}
    return _pretty(balances)


@mcp.tool()
def transfer_perp_sol(direction: str, amount_sol: float) -> str:
    """Transfer SOL between trading and savings wallets."""
    if direction not in ("to_savings", "to_trading"):
        return _pretty({"error": "direction must be 'to_savings' or 'to_trading'"})
    _enqueue_command("transfer_perp_sol", direction=direction,
                     amount_sol=float(amount_sol))
    return f"Command queued: transfer {amount_sol} SOL {direction}."


@mcp.tool()
def get_perp_margin_ratio() -> str:
    """Return the current perp margin ratio / health."""
    data = _read_json(os.path.join(PROJECT_DIR, "perp_margin_health.json")) or {}
    return _pretty(data)


@mcp.tool()
def get_perp_liquidation_price(symbol: str) -> str:
    """Return the estimated liquidation price for a perp position."""
    positions = _read_json(os.path.join(PROJECT_DIR, "perp_positions.json")) or []
    for p in positions:
        if (p.get("symbol") or "").upper() == symbol.upper():
            return _pretty({"symbol": symbol,
                            "liquidation_price": p.get("liquidation_price", 0),
                            "entry_price": p.get("entry_price", 0),
                            "leverage": p.get("leverage", 0)})
    return _pretty({"error": f"Position {symbol} not found"})


# ---------------------------------------------------------------------------
# 8. Signals (4)
# ---------------------------------------------------------------------------
@mcp.tool()
def get_perp_signals() -> str:
    """Return the latest perp trading signals."""
    signals = _read_json(os.path.join(PROJECT_DIR, "perp_signals.json")) or []
    return _pretty({"count": len(signals), "signals": signals})


@mcp.tool()
def get_perp_signal_detail(signal_id: str) -> str:
    """Return details for a specific perp signal."""
    signals = _read_json(os.path.join(PROJECT_DIR, "perp_signals.json")) or []
    for s in signals:
        if str(s.get("id", "")) == str(signal_id):
            return _pretty(s)
    return _pretty({"error": f"Signal {signal_id} not found"})


@mcp.tool()
def enable_perp_signal(symbol: str) -> str:
    """Re-enable signal generation for a blocked perp market."""
    _enqueue_command("enable_perp_signal", symbol=symbol)
    return f"Command queued: enable signals for {symbol}."


@mcp.tool()
def disable_perp_signal(symbol: str) -> str:
    """Disable signal generation for a perp market."""
    _enqueue_command("disable_perp_signal", symbol=symbol)
    return f"Command queued: disable signals for {symbol}."


# ---------------------------------------------------------------------------
# 9. Risk (4)
# ---------------------------------------------------------------------------
@mcp.tool()
def get_perp_risk_status() -> str:
    """Return the current perp risk status (leverage, exposure, etc.)."""
    cfg = _load_perp_cfg()
    positions = _read_json(os.path.join(PROJECT_DIR, "perp_positions.json")) or []
    exposure = sum(float(p.get("notional", 0)) for p in positions)
    return _pretty({
        "risk_level": cfg.get("perp_risk_level"),
        "default_leverage": cfg.get("perp_default_leverage"),
        "max_leverage": cfg.get("perp_max_leverage"),
        "margin_mode": cfg.get("perp_margin_mode"),
        "max_total_exposure": cfg.get("perp_max_total_exposure_usd"),
        "current_exposure": exposure,
        "position_count": len(positions),
    })


@mcp.tool()
def set_perp_max_leverage(leverage: float) -> str:
    """Set the perp max leverage cap."""
    cfg = _set_cfg_value("perp_max_leverage", leverage)
    _enqueue_command("set_perp_max_leverage", leverage=float(leverage))
    return _pretty({"updated": "perp_max_leverage",
                    "value": cfg["perp_max_leverage"]})


@mcp.tool()
def set_perp_max_exposure(usd: float) -> str:
    """Set the perp max total exposure in USD."""
    cfg = _set_cfg_value("perp_max_total_exposure_usd", usd)
    _enqueue_command("set_perp_max_exposure", usd=float(usd))
    return _pretty({"updated": "perp_max_total_exposure_usd",
                    "value": cfg["perp_max_total_exposure_usd"]})


@mcp.tool()
def get_perp_var_estimate(confidence: float = 0.95) -> str:
    """Return a simple parametric VaR estimate for open positions."""
    positions = _read_json(os.path.join(PROJECT_DIR, "perp_positions.json")) or []
    notional = sum(float(p.get("notional", 0)) for p in positions)
    vol = 0.05  # assumed 5% per-period volatility placeholder
    import math
    z = 1.65 if confidence <= 0.95 else 2.33
    var = notional * vol * z
    return _pretty({"notional": notional, "confidence": confidence,
                    "var": round(var, 2)})


# ---------------------------------------------------------------------------
# 10. Logs (2)
# ---------------------------------------------------------------------------
@mcp.tool()
def get_perp_log(limit: int = 100) -> str:
    """Return the tail of the perp bot log."""
    log_path = os.path.join(PROJECT_DIR, "perp_bot.log")
    try:
        with open(log_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        tail = "".join(lines[-int(limit):])
        return json.dumps({"tail": tail}, ensure_ascii=False, indent=2)
    except FileNotFoundError:
        return _pretty({"tail": ""})


@mcp.tool()
def clear_perp_log() -> str:
    """Clear the perp bot log file."""
    log_path = os.path.join(PROJECT_DIR, "perp_bot.log")
    try:
        with open(log_path, "w", encoding="utf-8") as f:
            f.write("")
    except FileNotFoundError:
        pass
    return "Perp bot log cleared."


# ---------------------------------------------------------------------------
# 11. Batch & convenience config (7)
# ---------------------------------------------------------------------------
@mcp.tool()
def update_perp_config_batch(updates: str) -> str:
    """Update multiple perp config values at once.

    Pass a JSON object string of key-value pairs, e.g.:
    '{"perp_default_leverage": 5, "perp_dry_run": true}'
    """
    try:
        parsed = json.loads(updates)
    except json.JSONDecodeError as e:
        return _pretty({"error": f"Invalid JSON: {e}"})
    if not isinstance(parsed, dict):
        return _pretty({"error": "Expected a JSON object"})
    cfg = _update_batch(parsed)
    warnings = validate_perp_config(cfg)
    _enqueue_command("update_config", **parsed)
    return _pretty({"updated_keys": list(parsed.keys()),
                    "warnings": warnings})


@mcp.tool()
def save_perp_settings() -> str:
    """Persist the current perp configuration to disk."""
    cfg = _load_perp_cfg()
    _save_perp_cfg(cfg)
    _enqueue_command("save_settings")
    return _pretty({"saved": True, "keys": len(cfg)})


@mcp.tool()
def set_perp_stop_loss(pct: float) -> str:
    """Set the hard stop loss percentage for perp positions."""
    cfg = _set_cfg_value("perp_hard_stop_loss_pct", pct)
    _enqueue_command("update_config", perp_hard_stop_loss_pct=float(pct))
    return _pretty({"updated": "perp_hard_stop_loss_pct",
                    "value": cfg["perp_hard_stop_loss_pct"]})


@mcp.tool()
def set_perp_take_profit_ladder(steps: str) -> str:
    """Set the take-profit ladder steps string (e.g. '2%:30,5%:30,10%:20')."""
    cfg = _set_cfg_value("perp_tp_ladder_steps", steps)
    _enqueue_command("update_config", perp_tp_ladder_steps=steps)
    return _pretty({"updated": "perp_tp_ladder_steps",
                    "value": cfg["perp_tp_ladder_steps"]})


@mcp.tool()
def set_perp_trailing_stop(activation_pct: float, drawdown_pct: float) -> str:
    """Configure the trailing stop activation and drawdown percentages."""
    cfg = _update_batch({
        "perp_trailing_stop_activation_pct": activation_pct,
        "perp_trailing_stop_drawdown_pct": drawdown_pct,
    })
    _enqueue_command("update_config",
                     perp_trailing_stop_activation_pct=float(activation_pct),
                     perp_trailing_stop_drawdown_pct=float(drawdown_pct))
    return _pretty({"updated": ["perp_trailing_stop_activation_pct",
                                "perp_trailing_stop_drawdown_pct"],
                    "activation_pct": cfg["perp_trailing_stop_activation_pct"],
                    "drawdown_pct": cfg["perp_trailing_stop_drawdown_pct"]})


@mcp.tool()
def set_perp_position_size(pct_of_wallet: float, max_notional: float) -> str:
    """Set position sizing: % of wallet as margin and max notional cap."""
    cfg = _update_batch({
        "perp_pct_of_wallet": pct_of_wallet,
        "perp_max_notional": max_notional,
    })
    _enqueue_command("update_config",
                     perp_pct_of_wallet=float(pct_of_wallet),
                     perp_max_notional=float(max_notional))
    return _pretty({"updated": ["perp_pct_of_wallet", "perp_max_notional"],
                    "pct_of_wallet": cfg["perp_pct_of_wallet"],
                    "max_notional": cfg["perp_max_notional"]})


@mcp.tool()
def set_perp_direction(mode: str) -> str:
    """Set allowed trade directions: 'long', 'short', or 'both'."""
    if mode not in ("long", "short", "both"):
        return _pretty({"error": "mode must be 'long', 'short', or 'both'"})
    cfg = _set_cfg_value("perp_allowed_directions", mode)
    _enqueue_command("update_config", perp_allowed_directions=mode)
    return _pretty({"updated": "perp_allowed_directions", "mode": mode})


# ---------------------------------------------------------------------------
# 12. Order management extensions (3)
# ---------------------------------------------------------------------------
@mcp.tool()
def modify_perp_order(order_id: str, new_price: float = 0,
                      new_size: float = 0) -> str:
    """Modify an existing perp order's price and/or size."""
    _enqueue_command("modify_perp_order", order_id=order_id,
                     new_price=float(new_price), new_size=float(new_size))
    return f"Command queued: modify order {order_id}."


@mcp.tool()
def set_perp_order_type(order_type: str) -> str:
    """Set the default perp order type: MARKET, LIMIT, POST_ONLY, IOC, or FOK."""
    valid = {"MARKET", "LIMIT", "POST_ONLY", "IOC", "FOK"}
    if order_type.upper() not in valid:
        return _pretty({"error": f"order_type must be one of {sorted(valid)}"})
    cfg = _set_cfg_value("perp_default_order_type", order_type.upper())
    _enqueue_command("update_config",
                     perp_default_order_type=order_type.upper())
    return _pretty({"updated": "perp_default_order_type",
                    "value": cfg["perp_default_order_type"]})


@mcp.tool()
def set_perp_slippage(bps: int) -> str:
    """Set the max acceptable slippage in basis points for perp orders."""
    cfg = _set_cfg_value("perp_slippage_bps", bps)
    _enqueue_command("update_config", perp_slippage_bps=int(bps))
    return _pretty({"updated": "perp_slippage_bps",
                    "value": cfg["perp_slippage_bps"]})


# ---------------------------------------------------------------------------
# 13. Market search & filtering (3)
# ---------------------------------------------------------------------------
@mcp.tool()
def search_perp_markets(query: str, min_volume: float = 0,
                        min_leverage: float = 0) -> str:
    """Search perp markets by symbol substring with optional volume/leverage filters."""
    markets = _read_json(os.path.join(PROJECT_DIR, "perp_markets.json")) or []
    q = query.upper()
    results = []
    for m in markets:
        sym = (m.get("symbol") or "").upper()
        if q and q not in sym:
            continue
        vol = float(m.get("24h_volume", 0) or 0)
        if min_volume > 0 and vol < min_volume:
            continue
        maxlev = float(m.get("max_leverage", 0) or 0)
        if min_leverage > 0 and maxlev < min_leverage:
            continue
        results.append(m)
    return _pretty({"query": query, "count": len(results), "markets": results})


@mcp.tool()
def get_top_perp_markets(sort_by: str = "24h_volume", limit: int = 20) -> str:
    """Return top perp markets sorted by volume, open interest, or 24h change."""
    markets = _read_json(os.path.join(PROJECT_DIR, "perp_markets.json")) or []
    valid_sorts = {"24h_volume", "open_interest", "change_24h_pct",
                   "mark_price", "max_leverage"}
    if sort_by not in valid_sorts:
        return _pretty({"error": f"sort_by must be one of {sorted(valid_sorts)}"})
    sorted_markets = sorted(
        markets,
        key=lambda m: float(m.get(sort_by, 0) or 0),
        reverse=True
    )
    return _pretty({"sort_by": sort_by, "count": len(sorted_markets[:limit]),
                    "markets": sorted_markets[:limit]})


@mcp.tool()
def get_perp_market_stats() -> str:
    """Return aggregate statistics across all perp markets."""
    markets = _read_json(os.path.join(PROJECT_DIR, "perp_markets.json")) or []
    if not markets:
        return _pretty({"error": "No market data loaded. Use Refresh Markets first."})
    total_vol = sum(float(m.get("24h_volume", 0) or 0) for m in markets)
    total_oi = sum(float(m.get("open_interest", 0) or 0) for m in markets)
    avg_funding = (sum(float(m.get("est_funding_rate", 0) or 0) for m in markets)
                   / len(markets)) if markets else 0
    gains = [m for m in markets if float(m.get("change_24h_pct", 0) or 0) > 0]
    losses = [m for m in markets if float(m.get("change_24h_pct", 0) or 0) < 0]
    return _pretty({
        "total_markets": len(markets),
        "total_24h_volume": round(total_vol, 2),
        "total_open_interest": round(total_oi, 2),
        "avg_funding_rate": round(avg_funding, 8),
        "gainers": len(gains),
        "losers": len(losses),
        "max_leverage_available": max(
            (float(m.get("max_leverage", 0) or 0) for m in markets), default=0),
    })


# ---------------------------------------------------------------------------
# 14. Signal history & management (3)
# ---------------------------------------------------------------------------
@mcp.tool()
def get_perp_signal_history(limit: int = 50) -> str:
    """Return the history of past perp signals (executed and rejected)."""
    history = _read_json(os.path.join(PROJECT_DIR,
                                      "perp_signal_history.json")) or []
    return _pretty({"count": len(history), "history": history[:limit]})


@mcp.tool()
def clear_perp_signal_history() -> str:
    """Clear the perp signal history file."""
    _write_json(os.path.join(PROJECT_DIR, "perp_signal_history.json"), [])
    return "Perp signal history cleared."


@mcp.tool()
def get_perp_signal_summary() -> str:
    """Return a summary of signal generation stats (counts by type, direction)."""
    history = _read_json(os.path.join(PROJECT_DIR,
                                      "perp_signal_history.json")) or []
    if not history:
        return _pretty({"error": "No signal history found"})
    by_type: dict = {}
    by_direction: dict = {}
    executed = 0
    rejected = 0
    for s in history:
        stype = s.get("signal_type", "unknown")
        by_type[stype] = by_type.get(stype, 0) + 1
        direction = s.get("direction", "unknown")
        by_direction[direction] = by_direction.get(direction, 0) + 1
        if s.get("executed"):
            executed += 1
        else:
            rejected += 1
    return _pretty({
        "total_signals": len(history),
        "executed": executed,
        "rejected": rejected,
        "by_type": by_type,
        "by_direction": by_direction,
    })


# ---------------------------------------------------------------------------
# 15. Fee & cost analysis (2)
# ---------------------------------------------------------------------------
@mcp.tool()
def get_perp_fee_summary() -> str:
    """Return a summary of fees paid across all perp trades."""
    trades = _read_json(os.path.join(PROJECT_DIR,
                                     "perp_trade_history.json")) or []
    total_fees = sum(float(t.get("fees", 0) or 0) for t in trades)
    total_notional = sum(float(t.get("notional", 0) or 0) for t in trades)
    fee_pct = (total_fees / total_notional * 100) if total_notional else 0
    return _pretty({
        "total_trades": len(trades),
        "total_fees_usd": round(total_fees, 4),
        "total_notional_usd": round(total_notional, 2),
        "effective_fee_pct": round(fee_pct, 4),
    })


@mcp.tool()
def get_perp_funding_cost(symbol: str = "") -> str:
    """Return total funding payments paid/received for a position or all."""
    positions = _read_json(os.path.join(PROJECT_DIR,
                                        "perp_positions.json")) or []
    results = []
    for p in positions:
        if symbol and (p.get("symbol") or "").upper() != symbol.upper():
            continue
        funding_paid = float(p.get("funding_paid", 0) or 0)
        funding_received = float(p.get("funding_received", 0) or 0)
        net = funding_received - funding_paid
        results.append({
            "symbol": p.get("symbol"),
            "funding_paid": round(funding_paid, 4),
            "funding_received": round(funding_received, 4),
            "net_funding": round(net, 4),
        })
    return _pretty({"positions": results, "count": len(results)})


# ---------------------------------------------------------------------------
# 16. Risk extensions (3)
# ---------------------------------------------------------------------------
@mcp.tool()
def get_perp_correlation_matrix() -> str:
    """Return a simple correlation matrix between open perp positions."""
    positions = _read_json(os.path.join(PROJECT_DIR,
                                        "perp_positions.json")) or []
    symbols = [p.get("symbol", "") for p in positions]
    if len(symbols) < 2:
        return _pretty({"error": "Need at least 2 positions for correlation"})
    # Placeholder: identity matrix (real correlation requires price history)
    n = len(symbols)
    matrix = [[1.0 if i == j else 0.0 for j in range(n)]
              for i in range(n)]
    return _pretty({"symbols": symbols, "matrix": matrix,
                    "note": "Placeholder - requires price history for real correlation"})


@mcp.tool()
def set_perp_liquidation_floor(pct: float) -> str:
    """Set the minimum liquidation distance floor percentage."""
    cfg = _set_cfg_value("perp_liquidation_distance_floor_pct", pct)
    _enqueue_command("update_config",
                     perp_liquidation_distance_floor_pct=float(pct))
    return _pretty({"updated": "perp_liquidation_distance_floor_pct",
                    "value": cfg["perp_liquidation_distance_floor_pct"]})


@mcp.tool()
def set_perp_funding_exit(max_rate: float) -> str:
    """Set the max adverse funding rate before the bot exits a position."""
    cfg = _set_cfg_value("perp_max_adverse_funding_rate", max_rate)
    _enqueue_command("update_config",
                     perp_max_adverse_funding_rate=float(max_rate))
    return _pretty({"updated": "perp_max_adverse_funding_rate",
                    "value": cfg["perp_max_adverse_funding_rate"]})


# ---------------------------------------------------------------------------
# 17. P&L extensions (2)
# ---------------------------------------------------------------------------
@mcp.tool()
def refresh_perp_pnl() -> str:
    """Force a refresh of the perp P&L tally from trade history."""
    _enqueue_command("refresh_pnl")
    trades = _read_json(os.path.join(PROJECT_DIR,
                                     "perp_trade_history.json")) or []
    realized = sum(float(t.get("pnl", 0) or 0) for t in trades)
    fees = sum(float(t.get("fees", 0) or 0) for t in trades)
    tally = {
        "realized_pnl": round(realized, 4),
        "fees_paid": round(fees, 4),
        "net_pnl": round(realized - fees, 4),
        "trade_count": len(trades),
    }
    _write_json(os.path.join(PROJECT_DIR, "perp_pnl_tally.json"), tally)
    return _pretty(tally)


@mcp.tool()
def get_perp_trade_detail(trade_index: int) -> str:
    """Return details for a specific perp trade by its index in history."""
    trades = _read_json(os.path.join(PROJECT_DIR,
                                     "perp_trade_history.json")) or []
    try:
        idx = int(trade_index)
    except (ValueError, TypeError):
        return _pretty({"error": "trade_index must be an integer"})
    if idx < 0 or idx >= len(trades):
        return _pretty({"error": f"Index {idx} out of range (0-{len(trades)-1})"})
    return _pretty(trades[idx])


# ---------------------------------------------------------------------------
# 18. Wallet extensions (2)
# ---------------------------------------------------------------------------
@mcp.tool()
def get_perp_margin_info() -> str:
    """Return detailed margin information for all open perp positions."""
    positions = _read_json(os.path.join(PROJECT_DIR,
                                        "perp_positions.json")) or []
    info = []
    for p in positions:
        info.append({
            "symbol": p.get("symbol"),
            "margin_mode": p.get("margin_mode", "isolated"),
            "initial_margin": float(p.get("initial_margin", 0) or 0),
            "maintenance_margin": float(p.get("maintenance_margin", 0) or 0),
            "available_margin": float(p.get("available_margin", 0) or 0),
            "margin_ratio": float(p.get("margin_ratio", 0) or 0),
        })
    return _pretty({"positions": info, "count": len(info)})


@mcp.tool()
def set_perp_auto_savings(enabled: bool, threshold_usd: float = 0,
                           transfer_usd: float = 0) -> str:
    """Configure auto savings sweep for perp profits."""
    updates = {"perp_enable_auto_savings": enabled}
    if threshold_usd > 0:
        updates["perp_savings_threshold_usd"] = threshold_usd
    if transfer_usd > 0:
        updates["perp_savings_transfer_usd"] = transfer_usd
    cfg = _update_batch(updates)
    _enqueue_command("update_config", **updates)
    return _pretty({"updated": list(updates.keys()), "values": updates})


# ---------------------------------------------------------------------------
# 19. Monitoring & intervals (2)
# ---------------------------------------------------------------------------
@mcp.tool()
def set_perp_poll_intervals(market_sec: float = 0, position_sec: float = 0,
                             signal_sec: float = 0) -> str:
    """Set polling intervals for market data, position monitoring, and signals."""
    updates = {}
    if market_sec > 0:
        updates["perp_market_poll_sec"] = market_sec
    if position_sec > 0:
        updates["perp_position_poll_sec"] = position_sec
    if signal_sec > 0:
        updates["perp_signal_poll_sec"] = signal_sec
    if not updates:
        return _pretty({"error": "Provide at least one non-zero interval"})
    cfg = _update_batch(updates)
    _enqueue_command("update_config", **updates)
    return _pretty({"updated": list(updates.keys()), "values": updates})


@mcp.tool()
def set_perp_market_filters(min_volume: float = -1, min_oi: float = -1,
                             max_spread: float = -1) -> str:
    """Set market entry filters: min 24h volume, min open interest, max spread."""
    updates = {}
    if min_volume >= 0:
        updates["perp_min_24h_volume_usd"] = min_volume
    if min_oi >= 0:
        updates["perp_min_open_interest_usd"] = min_oi
    if max_spread >= 0:
        updates["perp_max_spread_pct"] = max_spread
    if not updates:
        return _pretty({"error": "Provide at least one filter value (>=0)"})
    cfg = _update_batch(updates)
    _enqueue_command("update_config", **updates)
    return _pretty({"updated": list(updates.keys()), "values": updates})


# ---------------------------------------------------------------------------
# 20. Token allow/block lists (2)
# ---------------------------------------------------------------------------
@mcp.tool()
def set_perp_allowed_tokens(tokens: str) -> str:
    """Set the comma-separated list of allowed base tokens (empty = all allowed)."""
    cfg = _set_cfg_value("perp_allowed_base_tokens", tokens)
    _enqueue_command("update_config", perp_allowed_base_tokens=tokens)
    return _pretty({"updated": "perp_allowed_base_tokens",
                    "value": cfg["perp_allowed_base_tokens"]})


@mcp.tool()
def set_perp_blocked_tokens(tokens: str) -> str:
    """Set the comma-separated list of blocked base tokens (never trade these)."""
    cfg = _set_cfg_value("perp_blocked_base_tokens", tokens)
    _enqueue_command("update_config", perp_blocked_base_tokens=tokens)
    return _pretty({"updated": "perp_blocked_base_tokens",
                    "value": cfg["perp_blocked_base_tokens"]})


# ---------------------------------------------------------------------------
# 21. Dry-run / live mode (2)
# ---------------------------------------------------------------------------
@mcp.tool()
def set_perp_dry_run(enabled: bool) -> str:
    """Enable or disable perp dry-run (practice) mode."""
    cfg = _set_cfg_value("perp_dry_run", enabled)
    _enqueue_command("update_config", perp_dry_run=bool(enabled))
    return _pretty({"updated": "perp_dry_run", "value": cfg["perp_dry_run"]})


@mcp.tool()
def set_perp_auto_execute(enabled: bool) -> str:
    """Enable or disable automatic perp order execution."""
    cfg = _set_cfg_value("perp_auto_execute", enabled)
    _enqueue_command("update_config", perp_auto_execute=bool(enabled))
    return _pretty({"updated": "perp_auto_execute",
                    "value": cfg["perp_auto_execute"]})


# ---------------------------------------------------------------------------
# 22. Signal mode (2)
# ---------------------------------------------------------------------------
@mcp.tool()
def set_perp_signal_mode(mode: str) -> str:
    """Set the perp signal generation mode."""
    valid = {"momentum", "mean_reversion", "breakout", "funding_arb", "multi"}
    if mode not in valid:
        return _pretty({"error": f"mode must be one of {sorted(valid)}"})
    cfg = _set_cfg_value("perp_signal_mode", mode)
    _enqueue_command("update_config", perp_signal_mode=mode)
    return _pretty({"updated": "perp_signal_mode", "value": mode})


@mcp.tool()
def set_perp_position_timeout(seconds: int) -> str:
    """Set the auto-close position timeout in seconds (0 = disable)."""
    cfg = _set_cfg_value("perp_position_timeout_sec", seconds)
    _enqueue_command("update_config", perp_position_timeout_sec=int(seconds))
    return _pretty({"updated": "perp_position_timeout_sec",
                    "value": cfg["perp_position_timeout_sec"]})


# ---------------------------------------------------------------------------
# 23. Testnet toggle (1)
# ---------------------------------------------------------------------------
@mcp.tool()
def set_perp_testnet(enabled: bool) -> str:
    """Switch perp API between testnet and mainnet."""
    cfg = _set_cfg_value("perp_use_testnet", enabled)
    _enqueue_command("update_config", perp_use_testnet=bool(enabled))
    return _pretty({"updated": "perp_use_testnet",
                    "value": cfg["perp_use_testnet"]})


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
