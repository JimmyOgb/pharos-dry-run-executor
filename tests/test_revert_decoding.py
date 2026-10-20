"""
Unit Tests: EVM Revert & Panic Payload Decoding (Criterion 02)
"""

import os
import json
import pytest

from executor.decoder import (
    decode_error_string,
    decode_panic,
    decode_revert_payload,
    ERROR_STRING_SELECTOR,
    PANIC_SELECTOR,
)


@pytest.fixture
def fixtures_dict():
    path = os.path.join(os.path.dirname(__file__), "..", "assets", "test_transactions.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)["fixtures"]


def test_decode_standard_error_string(fixtures_dict):
    fix = fixtures_dict["revert_insufficient_balance"]
    raw = fix["revert_raw"]

    # Test direct helper
    msg = decode_error_string(raw)
    assert msg == "ERC20: transfer amount exceeds balance"

    # Test comprehensive decoder
    res = decode_revert_payload(raw)
    assert res.revert_type == "Error(string)"
    assert res.selector == ERROR_STRING_SELECTOR
    assert res.reason == "ERC20: transfer amount exceeds balance"


def test_decode_panic_arithmetic_overflow(fixtures_dict):
    fix = fixtures_dict["revert_panic_overflow"]
    raw = fix["revert_raw"]

    panic_tuple = decode_panic(raw)
    assert panic_tuple is not None
    code, hex_code, desc = panic_tuple
    assert code == 0x11
    assert hex_code == "0x11"
    assert "overflowed or underflowed" in desc

    res = decode_revert_payload(raw)
    assert res.revert_type == "Panic(uint256)"
    assert res.selector == PANIC_SELECTOR
    assert res.panic_code == 0x11
    assert res.panic_hex == "0x11"
    assert "overflow" in res.reason.lower()


def test_decode_custom_error(fixtures_dict):
    fix = fixtures_dict["revert_custom_error"]
    raw = fix["revert_raw"]

    res = decode_revert_payload(raw)
    assert res.revert_type == "CustomError"
    assert res.selector == "0xd92e233d"
    assert "ZeroAddress()" in res.reason


def test_decode_from_rpc_error_string():
    err_str = "execution reverted: SafeERC20: low-level call failed"
    res = decode_revert_payload(None, err_message=err_str)
    assert res.revert_type == "Error(string)"
    assert res.reason == "SafeERC20: low-level call failed"


def test_decode_unknown_payload():
    res = decode_revert_payload("0x1234")
    assert res.revert_type in ("Unknown", "CustomError")
