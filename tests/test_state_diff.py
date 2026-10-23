"""
Unit Tests: Pre/Post State & Balance Prediction (Criterion 03)
Includes strict calldata validation (8, 72, 135, 136, 138 chars) and unclamped arithmetic.
"""

import pytest
from executor.state_diff import predict_state_diff, validate_erc20_calldata, ERC20_TRANSFER_SELECTOR, ERC20_APPROVE_SELECTOR


def test_native_transfer_state_diff():
    sender = "0x1111111111111111111111111111111111111111"
    recipient = "0x2222222222222222222222222222222222222222"
    value = 2 * 10**18  # 2 PHRS
    gas_cost = 21000 * 10 * 10**9  # 210,000 gwei

    mock_bals = {
        f"{sender.lower()}_PHRS": 10 * 10**18,
        f"{recipient.lower()}_PHRS": 1 * 10**18,
    }

    pred = predict_state_diff(
        sender=sender,
        recipient=recipient,
        value_wei=value,
        data_hex="0x",
        estimated_gas_cost_wei=gas_cost,
        mock_balances=mock_bals,
    )

    assert pred.tx_type == "NATIVE_TRANSFER"
    assert len(pred.deltas) == 2

    sender_d = [d for d in pred.deltas if d.entity == "Sender"][0]
    recip_d = [d for d in pred.deltas if d.entity == "Recipient"][0]

    assert sender_d.delta == -(value + gas_cost)
    assert recip_d.delta == value
    assert recip_d.after == 3 * 10**18


def test_native_deficit_unclamped_arithmetic():
    """Regression: Balance arithmetic must not be clamped by max(0, ...)."""
    sender = "0x1111111111111111111111111111111111111111"
    recipient = "0x2222222222222222222222222222222222222222"
    value = 100 * 10**18  # 100 PHRS
    gas_cost = 21000 * 10 * 10**9

    mock_bals = {
        f"{sender.lower()}_PHRS": 10 * 10**18,  # Only 10 PHRS
    }

    pred = predict_state_diff(
        sender=sender,
        recipient=recipient,
        value_wei=value,
        data_hex="0x",
        estimated_gas_cost_wei=gas_cost,
        mock_balances=mock_bals,
    )

    sender_d = [d for d in pred.deltas if d.entity == "Sender"][0]
    expected_deficit = (10 * 10**18) - value - gas_cost
    assert sender_d.after == expected_deficit
    assert sender_d.after < 0  # Strict negative balance preserved


def test_erc20_transfer_state_diff():
    sender = "0x1111111111111111111111111111111111111111"
    token_contract = "0xcfc8330f4bcab529c625d12781b1c19466a9fc8b"
    recipient = "0x2222222222222222222222222222222222222222"
    amount = 500 * 10**6  # 500 USDC

    calldata = "0xa9059cbb" + recipient[2:].zfill(64) + hex(amount)[2:].zfill(64)
    assert len(calldata) == 138  # 0x + 136 chars

    known_tokens = {
        "USDC": {
            "address": token_contract,
            "symbol": "USDC",
            "decimals": 6
        }
    }
    mock_bals = {
        f"{sender.lower()}_USDC": 1000 * 10**6,
        f"{recipient.lower()}_USDC": 50 * 10**6,
    }

    pred = predict_state_diff(
        sender=sender,
        recipient=token_contract,
        value_wei=0,
        data_hex=calldata,
        known_tokens=known_tokens,
        mock_balances=mock_bals,
    )

    assert pred.tx_type == "ERC20_TRANSFER"
    tok_deltas = [d for d in pred.deltas if d.asset_type == "ERC20_BALANCE"]
    assert len(tok_deltas) == 2

    s_delta = [d for d in tok_deltas if d.entity == "Token Sender"][0]
    r_delta = [d for d in tok_deltas if d.entity == "Token Recipient"][0]

    assert s_delta.delta == -amount
    assert s_delta.after == 500 * 10**6
    assert r_delta.delta == amount
    assert r_delta.after == 550 * 10**6


def test_erc20_approve_state_diff():
    sender = "0x1111111111111111111111111111111111111111"
    token_contract = "0xcfc8330f4bcab529c625d12781b1c19466a9fc8b"
    spender = "0x000000000022d473030f116ddee9f6b43ac78ba3"
    allowance = 10000 * 10**6

    calldata = "0x095ea7b3" + spender[2:].zfill(64) + hex(allowance)[2:].zfill(64)

    known_tokens = {
        "USDC": {
            "address": token_contract,
            "symbol": "USDC",
            "decimals": 6
        }
    }

    pred = predict_state_diff(
        sender=sender,
        recipient=token_contract,
        value_wei=0,
        data_hex=calldata,
        known_tokens=known_tokens,
    )

    assert pred.tx_type == "ERC20_APPROVE"
    allow_delta = [d for d in pred.deltas if d.asset_type == "ERC20_ALLOWANCE"][0]
    assert allow_delta.after == allowance
    assert allow_delta.delta == allowance


# Stage 3 Regression Tests: Lengths 8, 72, 135, 136, 138
def test_erc20_calldata_validation_length_8():
    """8 hex chars: only selector."""
    calldata = "0xa9059cbb"
    is_valid, addr, amt, err = validate_erc20_calldata(calldata, ERC20_TRANSFER_SELECTOR)
    assert is_valid is False
    assert "Truncated" in str(err)


def test_erc20_calldata_validation_length_72():
    """72 hex chars: selector + address, missing amount."""
    recipient = "0x2222222222222222222222222222222222222222"
    calldata = "0xa9059cbb" + recipient[2:].zfill(64)
    assert len(calldata[2:]) == 72
    is_valid, addr, amt, err = validate_erc20_calldata(calldata, ERC20_TRANSFER_SELECTOR)
    assert is_valid is False
    assert "Truncated" in str(err)

    # predict_state_diff must flag as malformed
    pred = predict_state_diff("0x1", "0x2", 0, calldata)
    assert pred.is_malformed is True
    assert pred.tx_type == "MALFORMED_CALLDATA"


def test_erc20_calldata_validation_length_135():
    """135 hex chars: odd length and truncated."""
    calldata = "0x" + "a" * 135
    is_valid, addr, amt, err = validate_erc20_calldata(calldata, ERC20_TRANSFER_SELECTOR)
    assert is_valid is False
    assert "odd" in str(err).lower() or "truncated" in str(err).lower()


def test_erc20_calldata_validation_length_136_valid():
    """136 hex chars: exact standard ERC-20 calldata."""
    recipient = "0x2222222222222222222222222222222222222222"
    amount = 500 * 10**6
    calldata = "0xa9059cbb" + recipient[2:].zfill(64) + hex(amount)[2:].zfill(64)
    assert len(calldata[2:]) == 136
    is_valid, addr, amt, err = validate_erc20_calldata(calldata, ERC20_TRANSFER_SELECTOR)
    assert is_valid is True
    assert addr == recipient.lower()
    assert amt == amount


def test_erc20_calldata_validation_trailing_data_138():
    """138 hex chars: extra trailing byte (policy: rejected)."""
    recipient = "0x2222222222222222222222222222222222222222"
    amount = 500 * 10**6
    calldata = "0xa9059cbb" + recipient[2:].zfill(64) + hex(amount)[2:].zfill(64) + "ffff"
    assert len(calldata[2:]) == 140
    is_valid, addr, amt, err = validate_erc20_calldata(calldata, ERC20_TRANSFER_SELECTOR)
    assert is_valid is False
    assert "trailing" in str(err).lower()


def test_erc20_calldata_invalid_address_padding():
    """Address word not properly zero-padded in top 12 bytes."""
    bad_addr_word = "1" * 24 + "2222222222222222222222222222222222222222"
    calldata = "0xa9059cbb" + bad_addr_word + hex(100)[2:].zfill(64)
    is_valid, addr, amt, err = validate_erc20_calldata(calldata, ERC20_TRANSFER_SELECTOR)
    assert is_valid is False
    assert "not zero-padded" in str(err).lower()
