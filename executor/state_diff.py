"""
Pre/Post State & Balance Predictor
==================================
Computes deterministic before-and-after state transitions for transactions:
- Native PHRS balances (value transferred + estimated gas fee deduction)
- ERC-20 token balances for transfers (transfer)
- ERC-20 allowances for token approvals (approve)

Enforces strict integer wei arithmetic, calldata validation, and un-clamped deficit reporting.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

ERC20_TRANSFER_SELECTOR = "0xa9059cbb"
ERC20_APPROVE_SELECTOR = "0x095ea7b3"
ERC20_TRANSFER_FROM_SELECTOR = "0x23b872dd"


@dataclass
class BalanceDelta:
    """Represents an exact state change for a specific asset and account."""
    entity: str  # e.g., "Sender", "Recipient", "Spender Allowance"
    address: str
    asset_symbol: str
    asset_type: str  # "NATIVE", "ERC20_BALANCE", "ERC20_ALLOWANCE"
    decimals: int
    before: Optional[int]
    after: Optional[int]
    delta: int
    unit: str
    is_observed: bool = False

    def to_dict(self) -> Dict[str, Any]:
        fmt_divisor = 10**self.decimals if self.decimals > 0 else 1
        before_fmt = (
            "Unavailable"
            if self.before is None
            else f"{self.before / fmt_divisor:.6f}".rstrip("0").rstrip(".")
        )
        after_fmt = (
            "Unavailable"
            if self.after is None
            else f"{self.after / fmt_divisor:.6f}".rstrip("0").rstrip(".")
        )
        delta_fmt = (
            f"{'+' if self.delta > 0 else ''}{self.delta / fmt_divisor:.6f}".rstrip("0").rstrip(".")
        )

        return {
            "entity": self.entity,
            "address": self.address,
            "asset_symbol": self.asset_symbol,
            "asset_type": self.asset_type,
            "decimals": self.decimals,
            "before_raw": str(self.before) if self.before is not None else None,
            "after_raw": str(self.after) if self.after is not None else None,
            "delta_raw": str(self.delta),
            "before_formatted": before_fmt or "0",
            "after_formatted": after_fmt or "0",
            "delta_formatted": delta_fmt or "0",
            "unit": self.unit,
            "is_observed": self.is_observed,
        }


@dataclass
class StatePrediction:
    """Complete prediction of state changes for a dry-run transaction."""
    tx_type: str  # NATIVE_TRANSFER, ERC20_TRANSFER, ERC20_APPROVE, CONTRACT_CALL, MALFORMED_CALLDATA
    summary: str
    deltas: List[BalanceDelta] = field(default_factory=list)
    gas_deduction_phrs_wei: int = 0
    is_malformed: bool = False
    validation_error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tx_type": self.tx_type,
            "summary": self.summary,
            "deltas": [d.to_dict() for d in self.deltas],
            "gas_deduction_phrs_wei": str(self.gas_deduction_phrs_wei),
            "is_malformed": self.is_malformed,
            "validation_error": self.validation_error,
        }


def validate_erc20_calldata(
    clean_data: str, expected_selector: str
) -> Tuple[bool, Optional[str], Optional[int], Optional[str]]:
    """
    Validates and decodes ERC-20 standard calldata: selector(8) + address(64) + uint256(64).
    Returns (is_valid, parsed_address, parsed_amount, error_message).
    Exact required length: 136 hexadecimal characters (68 bytes).
    Policy: Trailing calldata or truncated calldata is rejected as malformed.
    """
    clean = clean_data.lower()
    if clean.startswith("0x"):
        clean = clean[2:]

    if not clean:
        return (False, None, None, "Empty calldata")

    # Character validity
    if not all(c in "0123456789abcdef" for c in clean):
        return (False, None, None, "Calldata contains invalid non-hexadecimal characters")

    # Byte alignment
    if len(clean) % 2 != 0:
        return (False, None, None, "Calldata has odd hexadecimal character count")

    exp_sel = expected_selector.lower().removeprefix("0x")
    if len(clean) < 8 or clean[:8] != exp_sel:
        return (False, None, None, f"Selector mismatch: expected 0x{exp_sel}, got 0x{clean[:8]}")

    if len(clean) < 136:
        return (
            False,
            None,
            None,
            f"Truncated ERC-20 calldata: length is {len(clean)} hex chars ({len(clean)//2} bytes), expected exactly 136 hex chars (68 bytes)",
        )

    if len(clean) > 136:
        return (
            False,
            None,
            None,
            f"Malformed ERC-20 calldata: rejected unexpected trailing calldata ({len(clean)} hex chars, expected exactly 136)",
        )

    # Word 1 (address): Must have 12 leading zero bytes
    addr_word = clean[8:72]
    if addr_word[:24] != "0" * 24:
        return (
            False,
            None,
            None,
            f"Malformed ABI address word: leading 12 bytes not zero-padded ({addr_word[:24]})",
        )

    parsed_addr = "0x" + addr_word[24:64]

    # Word 2 (uint256 amount)
    amount_word = clean[72:136]
    try:
        parsed_amount = int(amount_word, 16)
    except ValueError:
        return (False, None, None, "Malformed ABI uint256 amount word")

    return (True, parsed_addr, parsed_amount, None)


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
    Preserves exact integer arithmetic without clamping negative balances.
    """
    clean_data = data_hex.strip().lower()
    if clean_data.startswith("0x"):
        clean_data = clean_data[2:]

    mock_balances = mock_balances or {}
    deltas: List[BalanceDelta] = []

    # Calldata hex sanity check
    if clean_data:
        if not all(c in "0123456789abcdef" for c in clean_data):
            return StatePrediction(
                tx_type="MALFORMED_CALLDATA",
                summary="Rejected transaction: calldata contains non-hexadecimal characters",
                deltas=[],
                gas_deduction_phrs_wei=estimated_gas_cost_wei,
                is_malformed=True,
                validation_error="Non-hexadecimal calldata",
            )
        if len(clean_data) % 2 != 0:
            return StatePrediction(
                tx_type="MALFORMED_CALLDATA",
                summary=f"Rejected transaction: calldata has odd hex length ({len(clean_data)} chars)",
                deltas=[],
                gas_deduction_phrs_wei=estimated_gas_cost_wei,
                is_malformed=True,
                validation_error="Odd length calldata",
            )

    # 1. Native PHRS Delta (Value + Gas) - STRICT UNCLAMPED ARITHMETIC
    sender_key = f"{sender.lower()}_PHRS"
    sender_phrs_before: Optional[int] = mock_balances.get(sender_key)
    sender_observed = mock_balances.get(f"{sender_key}_observed", False)

    if sender_phrs_before is not None:
        sender_phrs_after: Optional[int] = sender_phrs_before - value_wei - estimated_gas_cost_wei
    else:
        sender_phrs_after = None

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
            is_observed=bool(sender_observed),
        )
    )

    if recipient:
        recip_key = f"{recipient.lower()}_PHRS"
        recip_phrs_before: Optional[int] = mock_balances.get(recip_key)
        recip_observed = mock_balances.get(f"{recip_key}_observed", False)

        if recip_phrs_before is not None:
            recip_phrs_after: Optional[int] = recip_phrs_before + value_wei
        else:
            recip_phrs_after = None

        if value_wei > 0 or recip_phrs_before is not None:
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
                    is_observed=bool(recip_observed),
                )
            )

    # 2. Check for ERC-20 Interactions
    selector = clean_data[0:8] if len(clean_data) >= 8 else ""

    token_address = recipient.lower() if recipient else ""
    token_meta = None
    if known_tokens:
        for symbol, info in known_tokens.items():
            if info.get("address", "").lower() == token_address:
                token_meta = info
                break

    token_symbol = token_meta.get("symbol", "ERC20") if token_meta else "TOKEN"
    decimals = token_meta.get("decimals", 18) if token_meta else 18

    # A. ERC-20 transfer(address to, uint256 amount)
    if selector == ERC20_TRANSFER_SELECTOR[2:]:
        is_valid, target_to, amount, err_msg = validate_erc20_calldata(clean_data, ERC20_TRANSFER_SELECTOR)
        if not is_valid or target_to is None or amount is None:
            return StatePrediction(
                tx_type="MALFORMED_CALLDATA",
                summary=f"Rejected malformed ERC-20 transfer: {err_msg}",
                deltas=deltas,
                gas_deduction_phrs_wei=estimated_gas_cost_wei,
                is_malformed=True,
                validation_error=err_msg,
            )

        sender_tok_key = f"{sender.lower()}_{token_symbol}"
        sender_tok_before: Optional[int] = mock_balances.get(sender_tok_key)
        sender_tok_obs = mock_balances.get(f"{sender_tok_key}_observed", False)
        sender_tok_after: Optional[int] = (
            (sender_tok_before - amount) if sender_tok_before is not None else None
        )

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
                is_observed=bool(sender_tok_obs),
            )
        )

        recip_tok_key = f"{target_to.lower()}_{token_symbol}"
        recip_tok_before: Optional[int] = mock_balances.get(recip_tok_key)
        recip_tok_obs = mock_balances.get(f"{recip_tok_key}_observed", False)
        recip_tok_after: Optional[int] = (
            (recip_tok_before + amount) if recip_tok_before is not None else None
        )

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
                is_observed=bool(recip_tok_obs),
            )
        )

        return StatePrediction(
            tx_type="ERC20_TRANSFER",
            summary=f"Transfers {amount / (10**decimals):.4f} {token_symbol} from {sender[:8]}... to {target_to[:8]}...",
            deltas=deltas,
            gas_deduction_phrs_wei=estimated_gas_cost_wei,
            is_malformed=False,
        )

    # B. ERC-20 approve(address spender, uint256 amount)
    if selector == ERC20_APPROVE_SELECTOR[2:]:
        is_valid, spender, amount, err_msg = validate_erc20_calldata(clean_data, ERC20_APPROVE_SELECTOR)
        if not is_valid or spender is None or amount is None:
            return StatePrediction(
                tx_type="MALFORMED_CALLDATA",
                summary=f"Rejected malformed ERC-20 approve: {err_msg}",
                deltas=deltas,
                gas_deduction_phrs_wei=estimated_gas_cost_wei,
                is_malformed=True,
                validation_error=err_msg,
            )

        allow_key = f"{sender.lower()}_{spender.lower()}_ALLOWANCE"
        allow_before: Optional[int] = mock_balances.get(allow_key)
        allow_obs = mock_balances.get(f"{allow_key}_observed", False)
        allow_after = amount
        allow_delta = (allow_after - allow_before) if allow_before is not None else amount

        deltas.append(
            BalanceDelta(
                entity="Spender Allowance",
                address=spender,
                asset_symbol=token_symbol,
                asset_type="ERC20_ALLOWANCE",
                decimals=decimals,
                before=allow_before,
                after=allow_after,
                delta=allow_delta,
                unit=f"{token_symbol} Allowance",
                is_observed=bool(allow_obs),
            )
        )

        return StatePrediction(
            tx_type="ERC20_APPROVE",
            summary=f"Sets allowance of {amount / (10**decimals):.4f} {token_symbol} for spender {spender[:8]}...",
            deltas=deltas,
            gas_deduction_phrs_wei=estimated_gas_cost_wei,
            is_malformed=False,
        )

    # C. Pure Native Transfer
    if not clean_data or clean_data == "":
        return StatePrediction(
            tx_type="NATIVE_TRANSFER",
            summary=f"Transfers {value_wei / 1e18:.4f} PHRS from {sender[:8]}... to {recipient[:8]}...",
            deltas=deltas,
            gas_deduction_phrs_wei=estimated_gas_cost_wei,
            is_malformed=False,
        )

    # D. Generic Contract Call
    return StatePrediction(
        tx_type="CONTRACT_CALL",
        summary=(
            f"Executes contract call on {recipient[:8]}... with {len(clean_data)//2} bytes calldata. "
            "NOTICE: Arbitrary contract side-effects (internal storage changes, token transfers, DEX swaps, "
            "fee-on-transfer hooks) are not fully modeled by static prediction."
        ),
        deltas=deltas,
        gas_deduction_phrs_wei=estimated_gas_cost_wei,
        is_malformed=False,
    )
