"""
Unit Tests: Pre/Post State & Balance Prediction (Criterion 03)
"""

import pytest
from executor.state_diff import predict_state_diff


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


def test_erc20_transfer_state_diff():
    sender = "0x1111111111111111111111111111111111111111"
    token_contract = "0xcfc8330f4bcab529c625d12781b1c19466a9fc8b"
    recipient = "0x2222222222222222222222222222222222222222"
    amount = 500 * 10**6  # 500 USDC

    # ERC20 transfer(address,uint256)
    calldata = "0xa9059cbb" + recipient[2:].zfill(64) + hex(amount)[2:].zfill(64)

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
