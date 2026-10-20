"""
Dry-Run Executor Command-Line Interface
=======================================
Enables interactive and automated pre-flight transaction simulations.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, Optional

from .client import PharosClient
from .gatekeeper import ExecutionGatekeeper
from .simulator import DryRunSimulator


def get_asset_path(filename: str) -> str:
    """Resolve asset relative to package directory."""
    base = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "assets"))
    return os.path.join(base, filename)


def format_cli_output(result_dict: Dict[str, Any], gate_dict: Dict[str, Any]) -> str:
    """Format human-readable CLI report."""
    lines = []
    lines.append("=" * 65)
    lines.append("      PHAROS SKILLENGINE :: DRY-RUN TRANSACTION SIMULATOR")
    lines.append("=" * 65)

    mode = result_dict.get("execution_mode", "SANDBOX")
    status = result_dict.get("status", "UNKNOWN")
    decision = result_dict.get("decision", "UNKNOWN")
    gate_status = gate_dict.get("status", "BLOCKED")

    badge = "[ GO / SAFE TO BROADCAST ]" if decision == "GO" and gate_status == "ALLOWED" else "[ NO-GO / EXECUTION BLOCKED ]"
    lines.append(f"Gate Verdict     : {badge}")
    lines.append(f"Simulation Mode  : {mode}")
    lines.append(f"Simulation Status: {status}")
    if result_dict.get("block_number"):
        lines.append(f"Network Block    : {result_dict['block_number']}")

    lines.append("-" * 65)
    tx = result_dict.get("tx_params", {})
    lines.append("Transaction Parameters:")
    lines.append(f"  From  : {tx.get('from')}")
    lines.append(f"  To    : {tx.get('to')}")
    lines.append(f"  Value : {tx.get('value')} wei")
    data_preview = tx.get("data", "0x")
    if len(data_preview) > 50:
        data_preview = data_preview[:46] + "..."
    lines.append(f"  Data  : {data_preview}")

    lines.append("-" * 65)
    lines.append("Resource & Cost Estimation:")
    lines.append(f"  Gas Limit Estimate: {result_dict.get('gas_estimate', 0):,} units")
    lines.append(f"  Network Gas Price : {result_dict.get('gas_price_gwei', 0.0):.4f} Gwei")
    lines.append(f"  Est. Gas Cost PHRS: {result_dict.get('gas_cost_phrs', '0.0')} PHRS")
    lines.append(f"  Est. Gas Cost USD : ${result_dict.get('gas_cost_usd', 0.0):.6f}")

    if result_dict.get("revert_info"):
        lines.append("-" * 65)
        rev = result_dict["revert_info"]
        lines.append("Revert Diagnostics:")
        lines.append(f"  Revert Type       : {rev.get('revert_type')}")
        lines.append(f"  Revert Reason     : {rev.get('reason')}")
        if rev.get("selector"):
            lines.append(f"  Error Selector    : {rev.get('selector')}")
        if rev.get("panic_hex"):
            lines.append(f"  Solidity Panic Hex: {rev.get('panic_hex')}")

    if result_dict.get("state_prediction"):
        sp = result_dict["state_prediction"]
        lines.append("-" * 65)
        lines.append(f"Predicted State Outcome: {sp.get('summary')}")
        lines.append("Account Balance Deltas:")
        for d in sp.get("deltas", []):
            lines.append(
                f"  [{d['entity']}] {d['address'][:10]}... | {d['asset_symbol']} ({d['asset_type']}): "
                f"{d['before_formatted']} -> {d['after_formatted']} (delta: {d['delta_formatted']} {d['unit']})"
            )

    lines.append("-" * 65)
    lines.append(f"Safety Gate Reason: {gate_dict.get('reason')}")
    lines.append("=" * 65)
    return "\n".join(lines)


def main(args_list: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Pharos Dry-Run Transaction Simulator & Execution Gatekeeper"
    )
    parser.add_argument("--fixture", help="Predefined fixture ID from assets/test_transactions.json")
    parser.add_argument("--from", dest="tx_from", help="Sender address (0x...)")
    parser.add_argument("--to", dest="tx_to", help="Target contract or recipient address (0x...)")
    parser.add_argument("--data", default="0x", help="Calldata in hex format (default: 0x)")
    parser.add_argument("--value", default="0", help="Value in wei or hex (default: 0)")
    parser.add_argument("--live", action="store_true", help="Execute simulation against live Pharos Atlantic Testnet")
    parser.add_argument("--rpc", default="https://atlantic.dplabs-internal.com", help="Atlantic RPC endpoint")
    parser.add_argument("--json", action="store_true", help="Output raw JSON")

    args = parser.parse_args(args_list)

    fixtures_path = get_asset_path("test_transactions.json")
    tokens_path = get_asset_path("tokens.json")

    client = PharosClient(rpc_url=args.rpc) if args.live else None
    simulator = DryRunSimulator(client=client, tokens_registry_path=tokens_path)
    gatekeeper = ExecutionGatekeeper()

    # Case 1: Fixture mode
    if args.fixture:
        if not os.path.exists(fixtures_path):
            print(f"Error: Fixtures file not found at {fixtures_path}", file=sys.stderr)
            return 1
        with open(fixtures_path, "r", encoding="utf-8") as f:
            fixtures_data = json.load(f).get("fixtures", {})
        if args.fixture not in fixtures_data:
            print(f"Error: Fixture '{args.fixture}' not found. Available: {list(fixtures_data.keys())}", file=sys.stderr)
            return 1
        fixture = fixtures_data[args.fixture]
        result = simulator.simulate_fixture(fixture)

    # Case 2: Custom transaction
    else:
        tx_from = args.tx_from or "0x1111111111111111111111111111111111111111"
        tx_to = args.tx_to or "0x2222222222222222222222222222222222222222"
        val_str = args.value
        val_wei = int(val_str, 16) if val_str.startswith("0x") else int(val_str)

        if args.live:
            result = simulator.simulate_live(
                sender=tx_from,
                recipient=tx_to,
                value_wei=val_wei,
                data_hex=args.data,
            )
        else:
            synthetic_fixture = {
                "id": "custom",
                "name": "Custom User Transaction",
                "from": tx_from,
                "to": tx_to,
                "value": str(val_wei),
                "data": args.data,
                "expected_success": True,
            }
            result = simulator.simulate_fixture(synthetic_fixture)

    verdict = gatekeeper.evaluate(result)

    if args.json:
        output_payload = {
            "simulation": result.to_dict(),
            "gate": verdict.to_dict(),
        }
        print(json.dumps(output_payload, indent=2))
    else:
        print(format_cli_output(result.to_dict(), verdict.to_dict()))

    return 0 if verdict.action_allowed else 2


if __name__ == "__main__":
    sys.exit(main())
