"""
Pre/Post State & Balance Predictor
==================================
Computes deterministic before-and-after state transitions for transactions:
- Native PHRS balances (value transferred + estimated gas fee deduction)
- ERC-20 token balances for transfers (transfer / transferFrom)
- ERC-20 allowances for token approvals (approve)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

ERC20_TRANSFER_SELECTOR = "0xa9059cbb"
ERC20_APPROVE_SELECTOR = "0x095ea7b3"
ERC20_TRANSFER_FROM_SELECTOR = "0x23b872dd"


@dataclass
class BalanceDelta:
    """Represents a state change for a specific asset and account."""
    entity: str  # e.g., "Sender (Alice)", "Recipient (Bob)", "Spender"
    address: str
    asset_symbol: str
    asset_type: str  # "NATIVE", "ERC20_BALANCE", "ERC20_ALLOWANCE"
    decimals: int
    before: int
    after: int
    delta: int
    unit: str

    def to_dict(self) -> Dict[str, Any]:
        fmt_divisor = 10**self.decimals if self.decimals > 0 else 1
        return {
            "entity": self.entity,
            "address": self.address,
            "asset_symbol": self.asset_symbol,
            "asset_type": self.asset_type,
            "decimals": self.decimals,
            "before_raw": str(self.before),
            "after_raw": str(self.after),
            "delta_raw": str(self.delta),
            "before_formatted": f"{self.before / fmt_divisor:.6f}".rstrip("0").rstrip("."),
            "after_formatted": f"{self.after / fmt_divisor:.6f}".rstrip("0").rstrip("."),
            "delta_formatted": f"{'+' if self.delta > 0 else ''}{self.delta / fmt_divisor:.6f}".rstrip("0").rstrip("."),
            "unit": self.unit,
        }


@dataclass
class StatePrediction:
    """Complete prediction of state changes for a dry-run transaction."""
    tx_type: str  # NATIVE_TRANSFER, ERC20_TRANSFER, ERC20_APPROVE, CONTRACT_CALL
    summary: str
    deltas: List[BalanceDelta] = field(default_factory=list)
    gas_deduction_phrs_wei: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tx_type": self.tx_type,
            "summary": self.summary,
            "deltas": [d.to_dict() for d in self.deltas],
            "gas_deduction_phrs_wei": str(self.gas_deduction_phrs_wei),
        }


def parse_address_arg(data_hex: str, offset: int = 0) -> str:
    """Extract address from 32-byte EVM word."""
    chunk = data_hex[offset: offset + 64]
    addr_part = chunk[-40:]
    return "0x" + addr_part.lower()


def parse_uint256_arg(data_hex: str, offset: int = 0) -> int:
    """Extract uint256 from 32-byte EVM word."""
    chunk = data_hex[offset: offset + 64]
    return int(chunk, 16) if chunk else 0


def predict_state_diff(
    sender: str,
    recipient: str,
    value_wei: int,
    data_hex: str,
    estimated_gas_cost_wei: int = 0,
    known_tokens: Optional[Dict[str, Any]] = None,
    mock_balances: Optional[Dict[str, Any]] = None,
) -> StatePrediction:
    """
    Computes before vs predicted after-state deltas for native and ERC-20 state.
    """
    clean_data = data_hex.strip().lower()
    if clean_data.startswith("0x"):
        clean_data = clean_data[2:]

    mock_balances = mock_balances or {}
    deltas: List[BalanceDelta] = []

    # 1. Native PHRS Delta (Value + Gas)
    sender_phrs_before = mock_balances.get(f"{sender.lower()}_PHRS", 10 * 10**18)
    sender_phrs_after = max(0, sender_phrs_before - value_wei - estimated_gas_cost_wei)
    sender_phrs_delta = -(value_wei + estimated_gas_cost_wei)

    deltas.append(
        BalanceDelta(
            entity="Sender",
            address=sender,
            asset_symbol="PHRS",
            asset_type="NATIVE",
            decimals=18,
            before=sender_phrs_before,
            after=sender_phrs_after,
            delta=sender_phrs_delta,
            unit="PHRS",
        )
    )

    if value_wei > 0 and recipient:
        recip_phrs_before = mock_balances.get(f"{recipient.lower()}_PHRS", 0)
        recip_phrs_after = recip_phrs_before + value_wei
        deltas.append(
            BalanceDelta(
                entity="Recipient",
                address=recipient,
                asset_symbol="PHRS",
                asset_type="NATIVE",
                decimals=18,
                before=recip_phrs_before,
                after=recip_phrs_after,
                delta=value_wei,
                unit="PHRS",
            )
        )

    # 2. Check for ERC-20 Interactions
    selector = clean_data[0:8] if len(clean_data) >= 8 else ""

    # Look up token symbol & decimals
    token_address = recipient.lower()
    token_meta = None
    if known_tokens:
        for symbol, info in known_tokens.items():
            if info.get("address", "").lower() == token_address:
                token_meta = info
                break

    token_symbol = token_meta.get("symbol", "ERC20") if token_meta else "TOKEN"
    decimals = token_meta.get("decimals", 18) if token_meta else 18

    # A. ERC-20 transfer(address to, uint256 amount)
    if selector == ERC20_TRANSFER_SELECTOR[2:] and len(clean_data) >= 72:
        target_to = parse_address_arg(clean_data, offset=8)
        amount = parse_uint256_arg(clean_data, offset=72)

        sender_tok_before = mock_balances.get(f"{sender.lower()}_{token_symbol}", 5000 * 10**decimals)
        sender_tok_after = max(0, sender_tok_before - amount)
        deltas.append(
            BalanceDelta(
                entity="Token Sender",
                address=sender,
                asset_symbol=token_symbol,
                asset_type="ERC20_BALANCE",
                decimals=decimals,
                before=sender_tok_before,
                after=sender_tok_after,
                delta=-amount,
                unit=token_symbol,
            )
        )

        recip_tok_before = mock_balances.get(f"{target_to.lower()}_{token_symbol}", 0)
        recip_tok_after = recip_tok_before + amount
        deltas.append(
            BalanceDelta(
                entity="Token Recipient",
                address=target_to,
                asset_symbol=token_symbol,
                asset_type="ERC20_BALANCE",
                decimals=decimals,
                before=recip_tok_before,
                after=recip_tok_after,
                delta=amount,
                unit=token_symbol,
            )
        )

        return StatePrediction(
            tx_type="ERC20_TRANSFER",
            summary=f"Transfers {amount / (10**decimals):.4f} {token_symbol} from {sender[:8]}... to {target_to[:8]}...",
            deltas=deltas,
            gas_deduction_phrs_wei=estimated_gas_cost_wei,
        )

    # B. ERC-20 approve(address spender, uint256 amount)
    if selector == ERC20_APPROVE_SELECTOR[2:] and len(clean_data) >= 72:
        spender = parse_address_arg(clean_data, offset=8)
        amount = parse_uint256_arg(clean_data, offset=72)

        allow_before = mock_balances.get(f"{sender.lower()}_{spender.lower()}_ALLOWANCE", 0)
        allow_after = amount
        deltas.append(
            BalanceDelta(
                entity="Spender Allowance",
                address=spender,
                asset_symbol=token_symbol,
                asset_type="ERC20_ALLOWANCE",
                decimals=decimals,
                before=allow_before,
                after=allow_after,
                delta=allow_after - allow_before,
                unit=f"{token_symbol} Allowance",
            )
        )

        return StatePrediction(
            tx_type="ERC20_APPROVE",
            summary=f"Sets allowance of {amount / (10**decimals):.4f} {token_symbol} for spender {spender[:8]}...",
            deltas=deltas,
            gas_deduction_phrs_wei=estimated_gas_cost_wei,
        )

    # C. Pure Native Transfer
    if not clean_data or clean_data == "":
        return StatePrediction(
            tx_type="NATIVE_TRANSFER",
            summary=f"Transfers {value_wei / 1e18:.4f} PHRS from {sender[:8]}... to {recipient[:8]}...",
            deltas=deltas,
            gas_deduction_phrs_wei=estimated_gas_cost_wei,
        )

    # D. Generic Contract Call
    return StatePrediction(
        tx_type="CONTRACT_CALL",
        summary=f"Executes contract call on {recipient[:8]}... with {len(clean_data)//2} bytes calldata",
        deltas=deltas,
        gas_deduction_phrs_wei=estimated_gas_cost_wei,
    )
