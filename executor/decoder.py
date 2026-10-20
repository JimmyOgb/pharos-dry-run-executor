"""
EVM Revert & Panic Decoder
==========================
Decodes EVM transaction revert payloads, Solidity 0.8+ panic codes,
and custom 4-byte contract error selectors.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Optional

# Standard EVM error selectors
ERROR_STRING_SELECTOR = "0x08c379a0"
PANIC_SELECTOR = "0x4e487b71"

# Known canonical custom errors on Pharos Atlantic & standard DeFi
KNOWN_CUSTOM_ERRORS: Dict[str, str] = {
    "0xd92e233d": "ZeroAddress()",
    "0x80ac58cd": "InsufficientFunds()",
    "0x550a2b97": "Unauthorized()",
    "0xd7ff29ea": "AmountTooSmall()",
    "0x1f2a2005": "TransferFailed()",
    "0xbb55fd27": "InsufficientAllowance()",
    "0xec2f0592": "SlippageExceeded()",
    "0x42966c68": "ContractLocked()",
    "0xb392a8a8": "ZeroAmount()",
}

PANIC_CODES: Dict[int, str] = {
    0x00: "Generic compiler panic",
    0x01: "Assert evaluated to false",
    0x11: "Arithmetic operation overflowed or underflowed (Panic 0x11)",
    0x12: "Division or modulo by zero (Panic 0x12)",
    0x21: "Conversion into an out-of-bounds enum type",
    0x22: "Access to out-of-bounds storage byte array",
    0x31: "Pop operation on empty array",
    0x32: "Array index out of bounds",
    0x41: "Out of memory / allocation error",
    0x51: "Zero-initialized variable of internal function type",
}


@dataclass
class DecodedRevert:
    """Structured representation of a decoded EVM revert."""
    raw: str
    revert_type: str  # Error(string), Panic(uint256), CustomError, GenericRPC, Unknown
    reason: str
    selector: Optional[str] = None
    panic_code: Optional[int] = None
    panic_hex: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "raw": self.raw,
            "revert_type": self.revert_type,
            "reason": self.reason,
            "selector": self.selector,
            "panic_code": self.panic_code,
            "panic_hex": self.panic_hex,
        }


def clean_hex(val: str) -> str:
    """Normalize hex string ensuring leading 0x."""
    val = val.strip()
    if not val.startswith("0x"):
        val = "0x" + val
    return val.lower()


def decode_error_string(raw_hex: str) -> Optional[str]:
    """
    Decodes standard ABI-encoded Error(string) payload.
    Layout: 4-byte selector (0x08c379a0) + 32-byte offset (0x20) + 32-byte length + string data.
    """
    clean = clean_hex(raw_hex)
    if not clean.startswith(ERROR_STRING_SELECTOR):
        return None

    data = clean[len(ERROR_STRING_SELECTOR):]
    if len(data) < 128:  # 64 chars offset + 64 chars length
        return None

    try:
        offset = int(data[0:64], 16)
        # offset is usually 32 (0x20) bytes from start of args, which is 64 hex chars
        length = int(data[64:128], 16)
        str_hex = data[128: 128 + length * 2]
        decoded = bytes.fromhex(str_hex).decode("utf-8", errors="replace")
        return decoded
    except Exception:
        return None


def decode_panic(raw_hex: str) -> Optional[tuple[int, str, str]]:
    """
    Decodes Solidity Panic(uint256) payload.
    Layout: 4-byte selector (0x4e487b71) + 32-byte uint256 panic code.
    Returns (code_int, code_hex, description).
    """
    clean = clean_hex(raw_hex)
    if not clean.startswith(PANIC_SELECTOR):
        return None

    data = clean[len(PANIC_SELECTOR):]
    if len(data) < 64:
        return None

    try:
        code = int(data[0:64], 16)
        hex_code = f"0x{code:02x}"
        desc = PANIC_CODES.get(code, f"Unknown Solidity panic code {hex_code}")
        return code, hex_code, desc
    except Exception:
        return None


def decode_revert_payload(raw_data: Optional[str], err_message: Optional[str] = None) -> DecodedRevert:
    """
    Comprehensive decoder analyzing raw hex revert data and optional RPC error messages.
    """
    # 1. Check if hex payload is present inside err_message (common in geth/reth/pharos RPCs)
    candidate_hex = raw_data or ""
    if not candidate_hex and err_message:
        hex_match = re.search(r"0x[0-9a-fA-F]{8,}", err_message)
        if hex_match:
            candidate_hex = hex_match.group(0)

    clean = clean_hex(candidate_hex) if candidate_hex and candidate_hex.startswith("0x") else ""

    # 2. Check for Error(string)
    if clean.startswith(ERROR_STRING_SELECTOR):
        reason = decode_error_string(clean)
        if reason is not None:
            return DecodedRevert(
                raw=clean,
                revert_type="Error(string)",
                reason=reason,
                selector=ERROR_STRING_SELECTOR,
            )

    # 3. Check for Panic(uint256)
    if clean.startswith(PANIC_SELECTOR):
        panic_info = decode_panic(clean)
        if panic_info is not None:
            code, hex_code, desc = panic_info
            return DecodedRevert(
                raw=clean,
                revert_type="Panic(uint256)",
                reason=desc,
                selector=PANIC_SELECTOR,
                panic_code=code,
                panic_hex=hex_code,
            )

    # 4. Check for 4-byte Custom Error
    if clean and len(clean) >= 10:  # 0x + 8 hex chars
        selector = clean[0:10].lower()
        if selector in KNOWN_CUSTOM_ERRORS:
            name = KNOWN_CUSTOM_ERRORS[selector]
            return DecodedRevert(
                raw=clean,
                revert_type="CustomError",
                reason=f"Custom error [{selector}]: {name}",
                selector=selector,
            )
        elif selector not in (ERROR_STRING_SELECTOR, PANIC_SELECTOR):
            return DecodedRevert(
                raw=clean,
                revert_type="CustomError",
                reason=f"Custom contract error [{selector}]",
                selector=selector,
            )

    # 5. Extract human-readable string from RPC message
    if err_message:
        # Match standard RPC revert text like "execution reverted: <reason>"
        m = re.search(r"execution reverted:\s*(.*)", err_message, re.IGNORECASE)
        if m:
            clean_msg = m.group(1).strip()
            return DecodedRevert(
                raw=clean or "0x",
                revert_type="Error(string)",
                reason=clean_msg,
                selector=ERROR_STRING_SELECTOR,
            )
        return DecodedRevert(
            raw=clean or "0x",
            revert_type="GenericRPC",
            reason=err_message,
        )

    return DecodedRevert(
        raw=clean or "0x",
        revert_type="Unknown",
        reason="Transaction reverted with unspecified reason",
    )
