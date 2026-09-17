"""Read-only on-chain ownership and exit-route auditing for open positions."""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from typing import Any


JUPITER_QUOTE_ENDPOINT = "https://lite-api.jup.ag/swap/v1/quote"
JUPITER_PRICE_ENDPOINT = "https://lite-api.jup.ag/price/v3"
WSOL_MINT = "So11111111111111111111111111111111111111112"
TOKEN_PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
TOKEN_2022_PROGRAM = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"


def _read_json(path: str, default: Any) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _rpc_call(url: str, method: str, params: list[Any]) -> Any:
    payload = json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": method, "params": params,
    }).encode("utf-8")
    request = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=15) as response:
        data = json.loads(response.read().decode("utf-8"))
    if data.get("error"):
        raise RuntimeError(data["error"].get("message", str(data["error"])))
    return data.get("result")


def _pubkey_from_wallet(wallet_path: str) -> str:
    wallet_bytes = bytes(_read_json(wallet_path, []))
    if not wallet_bytes:
        raise FileNotFoundError(f"{os.path.basename(wallet_path)} is missing or empty")
    from solders.keypair import Keypair
    return str(Keypair.from_bytes(wallet_bytes).pubkey())


def _trading_pubkey(project_dir: str) -> str:
    """Return the Meme bot wallet owner (legacy helper name retained)."""
    return _pubkey_from_wallet(os.path.join(project_dir, "meme_wallet.json"))


def get_exit_quote(mint: str, raw_amount: int, slippage_bps: int) -> dict[str, Any]:
    """Return a read-only Jupiter exit quote. No transaction is built or sent."""
    query = urllib.parse.urlencode({
        "inputMint": mint,
        "outputMint": WSOL_MINT,
        "amount": int(raw_amount),
        "slippageBps": int(slippage_bps),
        "swapMode": "ExactIn",
        "restrictIntermediateTokens": "true",
    })
    request = urllib.request.Request(
        f"{JUPITER_QUOTE_ENDPOINT}?{query}",
        headers={"User-Agent": "ai-crypto-sniper-mcp/5.0"},
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        quote = json.loads(response.read().decode("utf-8"))
    if quote.get("error") or not quote.get("outAmount"):
        raise RuntimeError(quote.get("error", "No Jupiter route available"))
    return {
        "input_raw_amount": int(quote["inAmount"]),
        "estimated_output_lamports": int(quote["outAmount"]),
        "minimum_output_lamports": int(quote.get("otherAmountThreshold", 0)),
        "estimated_output_sol": int(quote["outAmount"]) / 1e9,
        "minimum_output_sol": int(quote.get("otherAmountThreshold", 0)) / 1e9,
        "price_impact_pct": float(quote.get("priceImpactPct", 0) or 0) * 100,
        "routes": [
            step.get("swapInfo", {}).get("label", "unknown")
            for step in quote.get("routePlan", [])
        ],
        "read_only": True,
    }


def get_token_price_usd(mint: str) -> float:
    """Return Jupiter's screened USD price for a token, or zero if omitted."""
    query = urllib.parse.urlencode({"ids": mint})
    request = urllib.request.Request(
        f"{JUPITER_PRICE_ENDPOINT}?{query}",
        headers={"User-Agent": "ai-crypto-sniper-mcp/5.0", "Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        result = json.loads(response.read().decode("utf-8"))
    return float(result.get(mint, {}).get("usdPrice", 0) or 0)


def audit_open_positions(project_dir: str) -> dict[str, Any]:
    """Compare persisted positions with wallet token balances and exit routes."""
    config = _read_json(os.path.join(project_dir, "config.json"), {})
    positions = _read_json(os.path.join(project_dir, "open_positions.json"), [])
    rpc_url = config.get("rpc_http_url", "https://api.mainnet-beta.solana.com")
    slippage_bps = int(config.get("slippage_bps", 250))
    owner = _trading_pubkey(project_dir)
    results = []

    for position in positions:
        mint = str(position.get("mint", ""))
        if not mint:
            continue
        recorded_amount = int(position.get("token_amount", 0))
        item: dict[str, Any] = {
            "mint": mint,
            "name": position.get("name", ""),
            "symbol": position.get("symbol", ""),
            "recorded_raw_amount": recorded_amount,
            "graduated": bool(position.get("graduated", False)),
            "manual_review": bool(position.get("manual_review", False)),
        }
        try:
            accounts = _rpc_call(rpc_url, "getTokenAccountsByOwner", [
                owner, {"mint": mint}, {"encoding": "jsonParsed"},
            ]).get("value", [])
            chain_amount = 0
            account_ids = []
            for account in accounts:
                info = account.get("account", {}).get("data", {}).get("parsed", {}).get("info", {})
                chain_amount += int(info.get("tokenAmount", {}).get("amount", 0))
                account_ids.append(account.get("pubkey"))
            item.update({
                "chain_raw_amount": chain_amount,
                "record_matches_chain": recorded_amount == chain_amount,
                "token_accounts": account_ids,
                "owned_on_chain": chain_amount > 0,
            })
            if chain_amount > 0:
                try:
                    item["exit_quote"] = get_exit_quote(mint, chain_amount, slippage_bps)
                    item["route_available"] = True
                except Exception as exc:
                    item["route_available"] = False
                    item["route_error"] = str(exc)
        except Exception as exc:
            item["audit_error"] = str(exc)
        results.append(item)

    return {
        "wallet_pubkey": owner,
        "position_count": len(results),
        "all_records_match_chain": all(
            item.get("record_matches_chain", False) for item in results
        ) if results else True,
        "positions": results,
        "read_only": True,
    }


def get_wallet_summary(project_dir: str) -> dict[str, Any]:
    """Read live SOL balances and value open positions from executable quotes."""
    config = _read_json(os.path.join(project_dir, "config.json"), {})
    rpc_url = config.get("rpc_http_url", "https://api.mainnet-beta.solana.com")
    try:
        sol_price = get_token_price_usd(WSOL_MINT)
    except Exception:
        sol_price = 0.0
    result: dict[str, Any] = {}
    for label, filename in (
        ("funding_wallet", "wallet.json"),
        ("meme_wallet", "meme_wallet.json"),
        ("savings_wallet", "savings_wallet.json"),
        ("perpetuals_wallet", "perp_wallet.json"),
        ("spot_wallet", "spot_wallet.json"),
    ):
        try:
            pubkey = _pubkey_from_wallet(os.path.join(project_dir, filename))
            lamports = int(_rpc_call(rpc_url, "getBalance", [pubkey]).get("value", 0))
            sol = lamports / 1e9
            result[label] = {
                "pubkey": pubkey,
                "sol": round(sol, 9),
                "usd": round(sol * sol_price, 2),
            }
        except Exception as exc:
            result[label] = {"sol": 0, "usd": 0, "error": str(exc)}

    try:
        audit = audit_open_positions(project_dir)
        position_sol = sum(
            float(item.get("exit_quote", {}).get("estimated_output_sol", 0))
            for item in audit["positions"]
        )
        position_count = sum(1 for item in audit["positions"] if item.get("owned_on_chain"))
    except Exception:
        position_sol = 0.0
        position_count = 0
    result["open_positions"] = {
        "sol": round(position_sol, 9),
        "usd": round(position_sol * sol_price, 2),
        "count": position_count,
    }
    # Keep the former key as a compatibility alias without counting it twice.
    result["trading_wallet"] = dict(result.get("meme_wallet", {}))
    result["trading_wallet"]["deprecated_alias_for"] = "meme_wallet"
    total_sol = (
        float(result.get("funding_wallet", {}).get("sol", 0)) +
        float(result.get("meme_wallet", {}).get("sol", 0)) +
        float(result.get("savings_wallet", {}).get("sol", 0)) +
        float(result.get("perpetuals_wallet", {}).get("sol", 0)) +
        float(result.get("spot_wallet", {}).get("sol", 0)) +
        position_sol
    )
    result["total_cash_flow"] = {
        "sol": round(total_sol, 9),
        "usd": round(total_sol * sol_price, 2),
    }
    result["sol_price_usd"] = sol_price
    result["read_only"] = True
    return result


def audit_token_account_rent(project_dir: str) -> dict[str, Any]:
    """Read live token-account rent and identify empty, closable accounts."""
    config = _read_json(os.path.join(project_dir, "config.json"), {})
    rpc_url = config.get("rpc_http_url", "https://api.mainnet-beta.solana.com")
    owner = _trading_pubkey(project_dir)
    accounts: dict[str, dict[str, Any]] = {}
    errors = []
    for program_id in (TOKEN_PROGRAM, TOKEN_2022_PROGRAM):
        try:
            values = _rpc_call(rpc_url, "getTokenAccountsByOwner", [
                owner, {"programId": program_id}, {"encoding": "jsonParsed"},
            ]).get("value", [])
            for account in values:
                accounts[account.get("pubkey", "")] = account
        except Exception as exc:
            errors.append(f"{program_id[:8]}: {exc}")

    locked_lamports = 0
    recoverable_lamports = 0
    empty_accounts = []
    for address, account in accounts.items():
        lamports = int(account.get("account", {}).get("lamports", 0))
        info = account.get("account", {}).get("data", {}).get("parsed", {}).get("info", {})
        amount = int(info.get("tokenAmount", {}).get("amount", 0))
        locked_lamports += lamports
        if amount == 0 and lamports > 0:
            recoverable_lamports += lamports
            empty_accounts.append(address)
    try:
        sol_price = get_token_price_usd(WSOL_MINT)
    except Exception:
        sol_price = 0.0
    return {
        "token_account_count": len(accounts),
        "empty_token_account_count": len(empty_accounts),
        "ata_rent_locked_sol": locked_lamports / 1e9,
        "ata_rent_locked_usd": round(locked_lamports / 1e9 * sol_price, 2),
        "ata_rent_recoverable_sol": recoverable_lamports / 1e9,
        "ata_rent_recoverable_usd": round(recoverable_lamports / 1e9 * sol_price, 2),
        "empty_token_accounts": empty_accounts,
        "errors": errors,
        "read_only": True,
    }
