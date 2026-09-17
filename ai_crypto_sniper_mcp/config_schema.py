"""Shared strategy configuration, validation, and performance analysis.

This module is intentionally dependency-free so the GUI, trading bot, and MCP
server can all use the same setting names and validation rules.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import json
import math
import statistics
from typing import Any, Iterable


PROFILE_NAME = "small_account_guarded_v1"

RISK_LEVEL_MIN = 1
RISK_LEVEL_MAX = 20
RISK_LEVEL_NAMES = (
    "Minimal", "Very Low", "Guarded", "Conservative", "Cautious",
    "Moderately Cautious", "Balanced-Low", "Balanced", "Balanced-Plus",
    "Moderate", "Moderate-Plus", "Growth", "Growth-Plus", "Assertive",
    "Aggressive-Low", "Aggressive", "Very Aggressive", "Speculative",
    "Extreme", "Maximum",
)


def assess_pulse_candidate(result: dict[str, Any], *,
                           min_pulse_score: float = 50,
                           max_creator_holdings_pct: float = 5) -> dict[str, Any]:
    """Classify a Pulse match using completed on-chain safety evidence.

    ``EXCELLENT`` means the token passed the bot's complete configured safety
    funnel, its creator holding is known and below the dedicated Pulse ceiling,
    and its trend score clears the alert threshold. It is deliberately a
    candidate label rather than a promise or automatic-buy instruction.
    """
    pulse_score = float(result.get("pulse_score", 0) or 0)
    creator_value = result.get("creator_holdings_pct")
    try:
        creator_pct = float(creator_value) if creator_value is not None else None
    except (TypeError, ValueError):
        creator_pct = None
    rejection = str(result.get("safety_rejection", "") or "").strip()

    if rejection:
        return {
            "candidate_rating": "REJECTED",
            "excellent_candidate": False,
            "candidate_reason": f"Failed safety check: {rejection.replace('_', ' ')}.",
        }
    if creator_pct is not None and creator_pct > max_creator_holdings_pct:
        return {
            "candidate_rating": "HIGH RISK",
            "excellent_candidate": False,
            "candidate_reason": (
                f"Creator holds {creator_pct:.2f}% (Pulse maximum "
                f"{max_creator_holdings_pct:.2f}%)."
            ),
        }
    if result.get("safety_passed") is True:
        if creator_pct is None:
            return {
                "candidate_rating": "REVIEW",
                "excellent_candidate": False,
                "candidate_reason": "Safety checks passed, but creator holdings are unavailable.",
            }
        if pulse_score >= min_pulse_score:
            return {
                "candidate_rating": "EXCELLENT",
                "excellent_candidate": True,
                "candidate_reason": (
                    f"All configured safety checks passed; creator holds "
                    f"{creator_pct:.2f}% and Pulse score is {pulse_score:.1f}."
                ),
            }
        return {
            "candidate_rating": "PASSED",
            "excellent_candidate": False,
            "candidate_reason": (
                f"Safety checks passed; Pulse score {pulse_score:.1f} is below "
                f"the excellent-alert threshold {min_pulse_score:.1f}."
            ),
        }
    return {
        "candidate_rating": "ANALYZING",
        "excellent_candidate": False,
        "candidate_reason": "Waiting for the bot's on-chain safety evaluation.",
    }


def _rule(kind: str, default: Any, description: str, *, minimum: float | None = None,
          maximum: float | None = None, choices: Iterable[Any] | None = None,
          restart: bool = True) -> dict[str, Any]:
    rule = {
        "type": kind,
        "default": default,
        "description": description,
        "restart_required": restart,
    }
    if minimum is not None:
        rule["minimum"] = minimum
    if maximum is not None:
        rule["maximum"] = maximum
    if choices is not None:
        rule["choices"] = list(choices)
    return rule


CONFIG_RULES: dict[str, dict[str, Any]] = {
    "rpc_http_url": _rule("string", "https://api.mainnet-beta.solana.com", "Solana HTTP RPC endpoint."),
    "rpc_ws_url": _rule("string", "wss://api.mainnet-beta.solana.com", "Solana WebSocket endpoint."),
    "rpc_max_rps": _rule("integer", 30, "Maximum client-side RPC requests per second across the round-robin pool.", minimum=1, maximum=100),
    "simulated_balance_sol": _rule("number", 0, "Fake wallet balance for testing. 0 = use real on-chain balance.", minimum=0, maximum=1000),
    "risk_level": _rule(
        "integer", 5,
        "Unified trading-risk preset from 1 (most restrictive) to 20 (most aggressive).",
        minimum=RISK_LEVEL_MIN, maximum=RISK_LEVEL_MAX, restart=False,
    ),
    # Event source fallback chain: primary (Helius WS), fallback 1 (PumpPortal), fallback 2 (Bitquery)
    "event_source_primary": _rule("string", "helius", "Primary launch-event source: helius, pumpportal, or bitquery."),
    "event_source_fallback_1": _rule("string", "pumpportal", "First fallback if primary fails: helius, pumpportal, bitquery, or none."),
    "event_source_fallback_2": _rule("string", "bitquery", "Second fallback: helius, pumpportal, bitquery, or none."),
    "pumpportal_ws_url": _rule("string", "wss://pumpportal.fun/api/data", "PumpPortal WebSocket endpoint (free, no API key needed)."),
    "bitquery_ws_url": _rule("string", "wss://streaming.bitquery.io/graphql", "Bitquery WebSocket endpoint."),
    "bitquery_api_key": _rule("string", "", "Bitquery API token. Get one at account.bitquery.io. Never share this key."),
    "max_queue_size": _rule("integer", 500, "Maximum pending launch events before backpressure drops new events.", minimum=1, maximum=10000),
    "max_concurrent_evals": _rule("integer", 2, "Maximum token evaluations running concurrently.", minimum=1, maximum=50),
    "ws_reconnect_base_delay": _rule("number", 1.0, "Initial WebSocket reconnect delay in seconds.", minimum=0.1, maximum=60),
    "ws_reconnect_max_delay": _rule("number", 60.0, "Maximum WebSocket reconnect delay in seconds.", minimum=1, maximum=600),
    "seen_sig_ttl_sec": _rule("integer", 120, "Signature de-duplication lifetime in seconds.", minimum=1, maximum=86400),
    "poll_interval_sec": _rule("number", 3, "Legacy slow-scan polling interval in seconds.", minimum=0.1, maximum=300),
    "position_poll_sec": _rule("number", 0.5, "Open-position monitoring interval in seconds.", minimum=0.1, maximum=30),
    "priority_fee_microlamports": _rule("integer", 25000, "Buy priority price in micro-lamports per compute unit.", minimum=0, maximum=10_000_000),
    "sell_priority_fee_multiplier": _rule("number", 4, "Multiplier applied to the configured priority price for sells.", minimum=1, maximum=20),
    "prefetch_threshold_pct": _rule("number", 5, "Pre-build a sell transaction when within this percent of a trigger.", minimum=0, maximum=50),
    "max_sell_retries": _rule("integer", 10, "Failed sell attempts before marking a position for manual review.", minimum=1, maximum=100),
    "auto_execute": _rule("boolean", True, "Allow the bot to execute approved strategy actions automatically."),
    "dry_run": _rule("boolean", True, "Simulate transactions without broadcasting them."),
    "alert_sound": _rule("string", "sounds/buy.mp3", "Sound file played on buy/entry (WAV/MP3/AAC)."),
    "sell_alert_sound": _rule("string", "sounds/sell.mp3", "Sound file played on sell/close (WAV/MP3/AAC)."),
    "win_alert_sound": _rule("string", "sounds/win.mp3", "Sound file played 5s after a profitable close (WAV/MP3/AAC)."),
    "loss_alert_sound": _rule("string", "sounds/loss.mp3", "Sound file played 5s after a losing close (WAV/MP3/AAC)."),
    "use_sounds": _rule("boolean", True, "Master toggle for all Meme bot alert sounds."),
    "buy_pct_of_wallet": _rule("number", 10, "Percentage of available wallet SOL allocated to each entry.", minimum=1, maximum=100),
    "min_wallet_reserve_sol": _rule("number", 0.01, "SOL that must remain available for fees and recovery transactions.", minimum=0, maximum=100),
    "min_trade_size_sol": _rule("number", 0.005, "Reject entries smaller than this amount of SOL.", minimum=0, maximum=100),
    "max_trade_size_sol": _rule("number", 0.025, "Cap each entry at this amount of SOL; zero disables the cap.", minimum=0, maximum=100000),
    "max_positions": _rule("integer", 1, "Maximum number of simultaneous open positions.", minimum=1, maximum=20),
    "position_timeout_sec": _rule("integer", 300, "Exit an unclosed position after this many seconds; zero disables timeout.", minimum=0, maximum=86400),
    "slippage_bps": _rule("integer", 250, "Maximum adverse execution slippage in basis points.", minimum=10, maximum=3000),
    "tp_ladder_enabled": _rule("boolean", True, "Use staged take-profit exits instead of the legacy repeated multiplier."),
    "tp_ladder_steps": _rule("string", "1.3x:50,1.8x:30,3x:10", "Comma-separated multiplier:percent exits based on original token amount."),
    "tp_multiplier": _rule("number", 2.0, "Legacy repeated take-profit multiplier when the ladder is disabled.", minimum=1.01, maximum=100),
    "usd_threshold": _rule("number", 25, "Position USD value that triggers the one-time USD profit take.", minimum=0.01, maximum=1_000_000_000),
    "usd_take_profit": _rule("number", 10, "USD value of tokens sold when the USD threshold is reached.", minimum=0.01, maximum=1_000_000_000),
    "hard_stop_loss_pct": _rule("number", 15, "Exit a position when its value falls this percent below entry, even before trailing-stop activation.", minimum=1, maximum=95),
    "trailing_stop_activation_pct": _rule("number", 10, "Gain from entry required before arming the trailing stop.", minimum=0, maximum=1000),
    "trailing_stop_drawdown_pct": _rule("number", 12, "Peak-to-current drawdown that triggers the armed trailing stop.", minimum=1, maximum=95),
    "momentum_reversal_drop_pct": _rule("number", 12, "Rolling-window price drop that exits the position; zero disables it.", minimum=0, maximum=95),
    "momentum_reversal_window_sec": _rule("integer", 30, "Rolling momentum-reversal window in seconds.", minimum=1, maximum=3600),
    "volume_death_enabled": _rule("boolean", True, "Exit when the quoted sell value stops changing."),
    "volume_death_threshold_sec": _rule("integer", 75, "Unchanged quote duration that triggers the volume-death exit.", minimum=5, maximum=3600),
    "liquidity_drop_check_enabled": _rule("boolean", True, "Exit when quoted sell value collapses from its observed peak."),
    "liquidity_drop_threshold_pct": _rule("number", 15, "Peak quoted-value drop that triggers a liquidity exit.", minimum=1, maximum=95),
    "min_unique_buyers": _rule("integer", 15, "Minimum non-creator buyers; implementation can observe at most 19.", minimum=0, maximum=19),
    "buyer_check_wait_sec": _rule("integer", 20, "Observation window before buyer and activity checks; also gives public RPC time to index new accounts.", minimum=0, maximum=600),
    "buyer_check_max_sigs": _rule("integer", 10, "Maximum recent signatures inspected by buyer checks.", minimum=1, maximum=100),
    "min_liquidity_usd": _rule("number", 10000, "Minimum estimated Jupiter-route liquidity for graduated tokens.", minimum=0, maximum=1_000_000_000),
    "supply_check_mode": _rule("string", "percentage", "Interpret token-supply bounds as raw supply or visible-holder concentration.", choices=("quantity", "percentage")),
    "min_token_supply": _rule("number", 0, "Minimum raw supply, or minimum visible top-holder percent in percentage mode; zero disables it.", minimum=0),
    "max_token_supply": _rule("number", 12, "Maximum raw supply, or maximum visible top-holder percent in percentage mode; zero disables it.", minimum=0),
    "max_dev_holdings_pct": _rule("number", 5, "Maximum token percentage held by the Pump.fun creator; zero disables it.", minimum=0, maximum=100),
    "max_top10_concentration_pct": _rule("number", 70, "Maximum share of visible non-curve holdings controlled by the ten largest accounts.", minimum=0, maximum=100),
    "min_buy_sell_ratio_pct": _rule("number", 50, "Maximum recent sells-to-buys percentage; legacy name retained for compatibility.", minimum=0, maximum=1000),
    "min_bonding_curve_progress_pct": _rule("number", 25, "Minimum normalized Pump.fun bonding-curve progress before entry.", minimum=0, maximum=100),
    "max_bonding_curve_progress_pct": _rule("number", 65, "Maximum normalized Pump.fun bonding-curve progress for entry; zero disables it.", minimum=0, maximum=100),
    "require_pulse_match": _rule("boolean", False, "Require the mint to match a current Pulse trend before entry."),
    "min_pulse_score": _rule("number", 35, "Minimum Pulse score when trend matching is required.", minimum=0, maximum=1000),
    "pulse_match_mode": _rule("string", "word", "Pulse name-matching mode.", choices=("exact", "word", "fuzzy")),
    "pulse_excellent_alert_enabled": _rule("boolean", True, "Play and display an alert for Pulse matches rated EXCELLENT."),
    "pulse_excellent_min_score": _rule("number", 50, "Minimum trend score for an EXCELLENT Pulse candidate.", minimum=0, maximum=1000),
    "pulse_excellent_max_creator_holdings_pct": _rule("number", 5, "Maximum creator share allowed for an EXCELLENT Pulse candidate.", minimum=0, maximum=100),
    "max_buy_price_impact_pct": _rule("number", 3, "Maximum estimated entry price impact for Pump.fun buys; zero disables it.", minimum=0, maximum=100),
    "min_tx_velocity": _rule("integer", 5, "Minimum mint-related transactions during the buyer observation window.", minimum=0, maximum=1000),
    "max_deployer_token_count": _rule("integer", 3, "Maximum recent token creations attributed to the creator; zero disables it.", minimum=0, maximum=1000),
    "blacklist_mints": _rule("list", [], "Mint addresses the bot must never buy."),
    "enable_arbitrage": _rule("boolean", False, "Enable migration-arbitrage scanning and execution."),
    "arb_min_profit_pct": _rule("number", 5.0, "Minimum quoted round-trip arbitrage profit after estimated fees.", minimum=0, maximum=1000),
    "arb_buy_pct_of_wallet": _rule("number", 10, "Wallet percentage allocated to each arbitrage attempt.", minimum=1, maximum=100),
    "enable_auto_savings": _rule("boolean", True, "Move profits from trading to the savings wallet at the configured threshold."),
    "savings_threshold_usd": _rule("number", 100, "Trading-wallet USD value that triggers a savings sweep.", minimum=0),
    "savings_transfer_usd": _rule("number", 20, "USD value moved to savings per sweep.", minimum=0),
    "savings_target_usd": _rule("number", 80, "Desired trading-wallet USD value after a savings sweep.", minimum=0),
}


RESEARCHED_DEFAULT_PROFILE: dict[str, Any] = {
    key: rule["default"] for key, rule in CONFIG_RULES.items()
    if key not in {"rpc_http_url", "rpc_ws_url", "alert_sound", "sell_alert_sound",
                   "win_alert_sound", "loss_alert_sound",
                   "blacklist_mints",
                   "pumpportal_ws_url", "bitquery_ws_url", "bitquery_api_key"}
}


def parse_config_value(key: str, value: Any) -> Any:
    """Parse an MCP/GUI value according to the shared schema."""
    if key not in CONFIG_RULES:
        raise ValueError(f"Unknown config key: {key}")
    rule = CONFIG_RULES[key]
    kind = rule["type"]
    if kind == "boolean":
        if isinstance(value, bool):
            parsed = value
        elif isinstance(value, str) and value.strip().lower() in {"true", "false"}:
            parsed = value.strip().lower() == "true"
        else:
            raise ValueError(f"{key} must be true or false")
    elif kind == "integer":
        if isinstance(value, bool):
            raise ValueError(f"{key} must be an integer")
        parsed = int(value)
        if isinstance(value, float) and not value.is_integer():
            raise ValueError(f"{key} must be an integer")
    elif kind == "number":
        if isinstance(value, bool):
            raise ValueError(f"{key} must be numeric")
        parsed = float(value)
        if not math.isfinite(parsed):
            raise ValueError(f"{key} must be finite")
        if parsed.is_integer() and isinstance(rule["default"], int):
            parsed = int(parsed)
    elif kind == "list":
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                parsed = [part.strip() for part in value.split(",") if part.strip()]
        else:
            parsed = value
        if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
            raise ValueError(f"{key} must be a list of strings")
    else:
        parsed = str(value)

    if "minimum" in rule and parsed < rule["minimum"]:
        raise ValueError(f"{key} must be >= {rule['minimum']}")
    if "maximum" in rule and parsed > rule["maximum"]:
        raise ValueError(f"{key} must be <= {rule['maximum']}")
    if "choices" in rule and parsed not in rule["choices"]:
        raise ValueError(f"{key} must be one of {rule['choices']}")
    return parsed


def parse_tp_ladder(steps: str) -> list[tuple[float, float]]:
    parsed: list[tuple[float, float]] = []
    for raw_step in steps.split(","):
        raw_step = raw_step.strip()
        if not raw_step:
            continue
        multiplier_raw, percent_raw = raw_step.lower().replace("x", "").split(":", 1)
        multiplier = float(multiplier_raw)
        percent = float(percent_raw)
        if multiplier <= 1:
            raise ValueError("take-profit multipliers must be greater than 1x")
        if percent <= 0 or percent > 100:
            raise ValueError("take-profit percentages must be in (0, 100]")
        parsed.append((multiplier, percent))
    if not parsed:
        raise ValueError("at least one take-profit step is required")
    if sum(percent for _, percent in parsed) > 100:
        raise ValueError("take-profit ladder percentages cannot exceed 100%")
    if [multiplier for multiplier, _ in parsed] != sorted(multiplier for multiplier, _ in parsed):
        raise ValueError("take-profit multipliers must be in ascending order")
    return parsed


def validate_config(config: dict[str, Any]) -> dict[str, list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    for key, value in config.items():
        if key not in CONFIG_RULES:
            warnings.append(f"Unknown setting is preserved but not validated: {key}")
            continue
        try:
            parse_config_value(key, value)
        except (TypeError, ValueError) as exc:
            errors.append(str(exc))

    try:
        parse_tp_ladder(str(config.get("tp_ladder_steps", CONFIG_RULES["tp_ladder_steps"]["default"])))
    except (TypeError, ValueError) as exc:
        errors.append(f"tp_ladder_steps: {exc}")

    min_trade = float(config.get("min_trade_size_sol", 0))
    max_trade = float(config.get("max_trade_size_sol", 0))
    if max_trade > 0 and min_trade > max_trade:
        errors.append("min_trade_size_sol cannot exceed max_trade_size_sol")
    min_curve = float(config.get("min_bonding_curve_progress_pct", 0))
    max_curve = float(config.get("max_bonding_curve_progress_pct", 0))
    if max_curve > 0 and min_curve > max_curve:
        errors.append("minimum bonding-curve progress cannot exceed maximum progress")
    if float(config.get("usd_take_profit", 0)) > float(config.get("usd_threshold", 0)):
        errors.append("usd_take_profit cannot exceed usd_threshold")
    if config.get("enable_auto_savings", False):
        threshold = float(config.get("savings_threshold_usd", 0))
        target = float(config.get("savings_target_usd", 0))
        transfer = float(config.get("savings_transfer_usd", 0))
        if target >= threshold:
            errors.append("savings_target_usd must be below savings_threshold_usd")
        if transfer <= 0:
            errors.append("savings_transfer_usd must be positive when auto-savings is enabled")
    if float(config.get("buy_pct_of_wallet", 0)) > 20:
        warnings.append("More than 20% of the wallet per entry creates severe concentration risk.")
    if int(config.get("max_positions", 1)) > 3:
        warnings.append("More than three concurrent meme-token positions can exhaust fee reserves and RPC capacity.")
    if int(config.get("slippage_bps", 0)) > 500:
        warnings.append("Slippage above 5% permits materially adverse fills.")
    if config.get("auto_execute", False) and not config.get("dry_run", True):
        warnings.append("Live automatic execution is enabled.")
    if config.get("require_pulse_match", False):
        warnings.append("Trend-name matching can select both organic launches and impersonation/rug tokens; it is not a safety proof.")
    return {"errors": errors, "warnings": warnings}


def _risk_lerp(low: float, high: float, fraction: float,
               digits: int = 2) -> float:
    return round(low + ((high - low) * fraction), digits)


def _risk_int(low: int, high: int, fraction: float) -> int:
    return int(round(low + ((high - low) * fraction)))


def risk_level_name(level: int) -> str:
    """Return the human-readable label for one of the 20 risk levels."""
    parsed = int(level)
    if not RISK_LEVEL_MIN <= parsed <= RISK_LEVEL_MAX:
        raise ValueError(
            f"risk_level must be between {RISK_LEVEL_MIN} and {RISK_LEVEL_MAX}")
    return RISK_LEVEL_NAMES[parsed - 1]


def build_risk_level_profile(current: dict[str, Any], level: int) -> dict[str, Any]:
    """Overlay a deterministic 20-step trading-risk profile.

    Infrastructure, credentials, wallet behavior, the blacklist, live/dry-run
    mode, and feature enable/disable switches are preserved. Moving right
    along the scale increases allocation, loosens exit thresholds, and relaxes
    entry filters.
    """
    parsed = int(level)
    if not RISK_LEVEL_MIN <= parsed <= RISK_LEVEL_MAX:
        raise ValueError(
            f"risk_level must be between {RISK_LEVEL_MIN} and {RISK_LEVEL_MAX}")

    updated = dict(current)
    updated["risk_level"] = parsed
    updated.setdefault("max_mint_authority", False)
    updated.setdefault("max_freeze_authority", False)

    # fraction goes 0.0 at level 1 → 1.0 at level 20
    frac = (parsed - RISK_LEVEL_MIN) / (RISK_LEVEL_MAX - RISK_LEVEL_MIN)

    # --- Allocation ---
    updated["buy_pct_of_wallet"] = _risk_int(3, 50, frac)
    updated["max_positions"] = _risk_int(1, 10, frac)
    updated["min_trade_size_sol"] = _risk_lerp(0.002, 0.05, frac, 4)
    updated["max_trade_size_sol"] = _risk_lerp(0.01, 0.5, frac, 4)

    # --- Exit thresholds ---
    updated["tp_multiplier"] = _risk_lerp(1.5, 10.0, frac, 1)
    updated["usd_threshold"] = _risk_lerp(10, 500, frac, 0)
    updated["usd_take_profit"] = _risk_lerp(5, 200, frac, 0)
    updated["hard_stop_loss_pct"] = _risk_int(5, 40, frac)
    updated["trailing_stop_activation_pct"] = _risk_int(5, 50, frac)
    updated["trailing_stop_drawdown_pct"] = _risk_int(5, 40, frac)
    updated["momentum_reversal_drop_pct"] = _risk_int(5, 40, frac)
    updated["volume_death_threshold_sec"] = _risk_int(30, 300, frac)
    updated["liquidity_drop_threshold_pct"] = _risk_int(10, 50, frac)
    updated["position_timeout_sec"] = _risk_int(120, 3600, frac)

    # --- Take-profit ladder ---
    if frac < 0.33:
        updated["tp_ladder_steps"] = "1.3x:50,1.8x:30,3x:10"
    elif frac < 0.66:
        updated["tp_ladder_steps"] = "1.5x:40,2.5x:30,5x:20,10x:10"
    else:
        updated["tp_ladder_steps"] = "2x:30,4x:30,8x:20,20x:10"

    # --- Entry filters (relax as risk increases) ---
    updated["min_liquidity_usd"] = _risk_int(20000, 1000, frac)
    updated["min_unique_buyers"] = _risk_int(19, 3, frac)
    updated["buyer_check_wait_sec"] = _risk_int(40, 10, frac)
    updated["supply_check_mode"] = "percentage"
    updated["min_token_supply"] = 0
    updated["max_token_supply"] = _risk_int(8, 40, frac)
    updated["max_dev_holdings_pct"] = _risk_int(3, 25, frac)
    updated["max_top10_concentration_pct"] = _risk_int(50, 90, frac)
    # Despite its legacy name, this setting is the maximum sells-to-buys
    # percentage.  A higher-risk profile must permit more sell pressure.
    updated["min_buy_sell_ratio_pct"] = _risk_int(30, 150, frac)
    updated["min_bonding_curve_progress_pct"] = _risk_int(40, 10, frac)
    updated["max_bonding_curve_progress_pct"] = _risk_int(50, 80, frac)
    updated["max_buy_price_impact_pct"] = _risk_int(1, 10, frac)
    updated["min_tx_velocity"] = _risk_int(10, 1, frac)
    updated["max_deployer_token_count"] = _risk_int(1, 20, frac)
    updated["buyer_check_max_sigs"] = _risk_int(20, 5, frac)

    # --- Slippage ---
    updated["slippage_bps"] = _risk_int(100, 1000, frac)

    return updated


def apply_researched_profile(current: dict[str, Any], *, live_trading: bool = False) -> dict[str, Any]:
    """Return a validated copy with the guarded profile overlaid.

    RPC endpoints, alert sound, and blacklist are deliberately preserved.
    """
    updated = dict(current)
    updated.update(RESEARCHED_DEFAULT_PROFILE)
    updated["auto_execute"] = True
    updated["dry_run"] = not live_trading
    validation = validate_config(updated)
    if validation["errors"]:
        raise ValueError("; ".join(validation["errors"]))
    return updated


def config_catalog(current: dict[str, Any]) -> dict[str, Any]:
    settings = {}
    for key, rule in CONFIG_RULES.items():
        entry = dict(rule)
        entry["current"] = current.get(key, rule["default"])
        entry["profile_value"] = RESEARCHED_DEFAULT_PROFILE.get(key, "preserved")
        settings[key] = entry
    return {
        "profile": PROFILE_NAME,
        "setting_count": len(settings),
        "settings": settings,
        "validation": validate_config(current),
    }


def analyze_trade_history(trades: list[dict[str, Any]]) -> dict[str, Any]:
    sells = [trade for trade in trades if trade.get("type") == "SELL" and "pnl_sol" in trade]
    pnls = [float(trade.get("pnl_sol", 0)) for trade in sells]
    pct_returns = [float(trade.get("pnl_pct", 0)) for trade in sells]
    wins = [value for value in pnls if value > 0]
    losses = [value for value in pnls if value < 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    subtypes = Counter(str(trade.get("subtype", "unknown")) for trade in sells)
    first_timestamp = None
    last_timestamp = None
    timestamps = []
    for trade in trades:
        raw = trade.get("timestamp")
        if not raw:
            continue
        try:
            timestamps.append(datetime.fromisoformat(str(raw).replace("Z", "+00:00")))
        except ValueError:
            continue
    if timestamps:
        first_timestamp = min(timestamps).astimezone(timezone.utc).isoformat()
        last_timestamp = max(timestamps).astimezone(timezone.utc).isoformat()
    return {
        "closed_trades": len(sells),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": round(len(wins) / len(sells) * 100, 2) if sells else 0,
        "net_pnl_sol": round(sum(pnls), 9),
        "gross_profit_sol": round(gross_profit, 9),
        "gross_loss_sol": round(gross_loss, 9),
        "profit_factor": round(gross_profit / gross_loss, 4) if gross_loss else None,
        "average_pnl_sol": round(statistics.fmean(pnls), 9) if pnls else 0,
        "median_pnl_pct": round(statistics.median(pct_returns), 4) if pct_returns else 0,
        "best_pnl_pct": round(max(pct_returns), 4) if pct_returns else 0,
        "worst_pnl_pct": round(min(pct_returns), 4) if pct_returns else 0,
        "exit_reasons": dict(sorted(subtypes.items())),
        "first_trade_at": first_timestamp,
        "last_trade_at": last_timestamp,
    }
