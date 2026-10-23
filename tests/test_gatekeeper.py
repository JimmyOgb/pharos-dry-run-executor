"""
Unit Tests: Fail-Closed Execution Gatekeeper (Criterion 04)
Includes regressions for underflow, missing balance, zero/invalid gas price, and malformed calldata.
"""

import pytest

from executor.decoder import DecodedRevert
from executor.gatekeeper import ExecutionBlockedError, ExecutionGatekeeper
from executor.simulator import DryRunResult
from executor.state_diff import BalanceDelta, StatePrediction


def test_gatekeeper_allows_valid_simulation():
    gate = ExecutionGatekeeper()
    valid_res = DryRunResult(
        success=True,
        status="SIMULATED_SUCCESS",
        decision="GO",
        tx_params={"from": "0x1", "to": "0x2"},
        gas_estimate=21000,
        gas_price_gwei=10.0,
        gas_cost_phrs=0.00021,
        gas_cost_usd=0.000525,
        revert_info=None,
    )

    verdict = gate.evaluate(valid_res)
    assert verdict.action_allowed is True
    assert verdict.status == "ALLOWED"
    assert "GATE PASSED" in verdict.reason

    # enforce_execution_gate should not raise
    gate.enforce_execution_gate(valid_res)


def test_gatekeeper_blocks_reverting_simulation():
    gate = ExecutionGatekeeper()
    rev_info = DecodedRevert(
        raw="0x08c379a0",
        revert_type="Error(string)",
        reason="ERC20: transfer amount exceeds balance",
        selector="0x08c379a0"
    )
    reverting_res = DryRunResult(
        success=False,
        status="SIMULATION_REVERTED",
        decision="NO-GO",
        tx_params={"from": "0x1", "to": "0x2"},
        gas_estimate=0,
        gas_price_gwei=10.0,
        gas_cost_phrs=0.0,
        gas_cost_usd=0.0,
        revert_info=rev_info,
    )

    verdict = gate.evaluate(reverting_res)
    assert verdict.action_allowed is False
    assert verdict.status == "BLOCKED"
    assert "Execution blocked" in verdict.reason
    assert "ERC20: transfer amount exceeds balance" in verdict.reason

    with pytest.raises(ExecutionBlockedError) as exc_info:
        gate.enforce_execution_gate(reverting_res)
    assert "Execution blocked" in str(exc_info.value)


def test_gatekeeper_blocks_zero_gas_valid_status():
    gate = ExecutionGatekeeper()
    anomalous_res = DryRunResult(
        success=True,
        status="SIMULATED_SUCCESS",
        decision="GO",
        tx_params={},
        gas_estimate=0,  # invalid gas
        gas_price_gwei=10.0,
        gas_cost_phrs=0.0,
        gas_cost_usd=0.0,
    )

    verdict = gate.evaluate(anomalous_res)
    assert verdict.action_allowed is False
    assert verdict.status == "BLOCKED"
    assert "Invalid gas estimate" in verdict.reason


def test_gatekeeper_blocks_negative_balance_deficit():
    """Regression: Sender spending more than available balance must be BLOCKED."""
    gate = ExecutionGatekeeper()
    underflow_delta = BalanceDelta(
        entity="Sender",
        address="0x1111111111111111111111111111111111111111",
        asset_symbol="PHRS",
        asset_type="NATIVE",
        decimals=18,
        before=10 * 10**18,
        after=-(90 * 10**18),  # Negative deficit after 100 PHRS spend
        delta=-(100 * 10**18),
        unit="PHRS",
    )
    pred = StatePrediction(
        tx_type="NATIVE_TRANSFER",
        summary="Deficit transfer",
        deltas=[underflow_delta],
    )
    res = DryRunResult(
        success=True,
        status="SIMULATED_SUCCESS",
        decision="GO",
        tx_params={},
        gas_estimate=21000,
        gas_price_gwei=10.0,
        gas_cost_phrs=0.00021,
        gas_cost_usd=0.000525,
        state_prediction=pred,
    )

    verdict = gate.evaluate(res)
    assert verdict.action_allowed is False
    assert verdict.status == "BLOCKED"
    assert "would underflow" in verdict.reason


def test_gatekeeper_blocks_value_plus_gas_greater_than_balance():
    """Regression: Value alone fits, but value + gas exceeds available balance."""
    gate = ExecutionGatekeeper()
    gas_cost = 21000 * 10 * 10**9
    balance = 1 * 10**18
    # value is exactly 1 PHRS, so value + gas causes deficit
    underflow_delta = BalanceDelta(
        entity="Sender",
        address="0x1111111111111111111111111111111111111111",
        asset_symbol="PHRS",
        asset_type="NATIVE",
        decimals=18,
        before=balance,
        after=-gas_cost,
        delta=-(balance + gas_cost),
        unit="PHRS",
    )
    pred = StatePrediction(
        tx_type="NATIVE_TRANSFER",
        summary="Exact value plus fee underflow",
        deltas=[underflow_delta],
    )
    res = DryRunResult(
        success=True,
        status="SIMULATED_SUCCESS",
        decision="GO",
        tx_params={},
        gas_estimate=21000,
        gas_price_gwei=10.0,
        gas_cost_phrs=0.00021,
        gas_cost_usd=0.000525,
        state_prediction=pred,
    )

    verdict = gate.evaluate(res)
    assert verdict.action_allowed is False
    assert verdict.status == "BLOCKED"
    assert "would underflow" in verdict.reason


def test_gatekeeper_exact_balance_boundary():
    """Regression: Exact boundary where balance covers value + gas exactly (after == 0)."""
    gate = ExecutionGatekeeper()
    gas_cost = 21000 * 10 * 10**9
    value = 1 * 10**18
    exact_delta = BalanceDelta(
        entity="Sender",
        address="0x1111111111111111111111111111111111111111",
        asset_symbol="PHRS",
        asset_type="NATIVE",
        decimals=18,
        before=value + gas_cost,
        after=0,
        delta=-(value + gas_cost),
        unit="PHRS",
    )
    pred = StatePrediction(
        tx_type="NATIVE_TRANSFER",
        summary="Exact balance spend",
        deltas=[exact_delta],
    )
    res = DryRunResult(
        success=True,
        status="SIMULATED_SUCCESS",
        decision="GO",
        tx_params={},
        gas_estimate=21000,
        gas_price_gwei=10.0,
        gas_cost_phrs=0.00021,
        gas_cost_usd=0.000525,
        state_prediction=pred,
    )

    verdict = gate.evaluate(res)
    assert verdict.action_allowed is True
    assert verdict.status == "ALLOWED"


def test_gatekeeper_blocks_missing_sender_balance():
    """Regression: Missing sender balance must fail closed."""
    gate = ExecutionGatekeeper()
    missing_delta = BalanceDelta(
        entity="Sender",
        address="0x1111111111111111111111111111111111111111",
        asset_symbol="PHRS",
        asset_type="NATIVE",
        decimals=18,
        before=None,
        after=None,
        delta=-1000,
        unit="PHRS",
    )
    pred = StatePrediction(
        tx_type="NATIVE_TRANSFER",
        summary="Missing balance",
        deltas=[missing_delta],
    )
    res = DryRunResult(
        success=True,
        status="SIMULATED_SUCCESS",
        decision="GO",
        tx_params={},
        gas_estimate=21000,
        gas_price_gwei=10.0,
        gas_cost_phrs=0.00021,
        gas_cost_usd=0.000525,
        state_prediction=pred,
    )

    verdict = gate.evaluate(res)
    assert verdict.action_allowed is False
    assert verdict.status == "BLOCKED"
    assert "unavailable" in verdict.reason.lower()


def test_gatekeeper_blocks_missing_or_failed_gas_price():
    """Regression: Missing or 0 gas price must fail closed."""
    gate = ExecutionGatekeeper()
    res = DryRunResult(
        success=True,
        status="SIMULATED_SUCCESS",
        decision="GO",
        tx_params={},
        gas_estimate=21000,
        gas_price_gwei=0.0,  # 0 or missing gas price
        gas_cost_phrs=0.0,
        gas_cost_usd=0.0,
    )

    verdict = gate.evaluate(res)
    assert verdict.action_allowed is False
    assert verdict.status == "BLOCKED"
    assert "gas price" in verdict.reason.lower()


def test_gatekeeper_blocks_malformed_calldata():
    """Regression: Calldata integrity failure must fail closed."""
    gate = ExecutionGatekeeper()
    pred = StatePrediction(
        tx_type="MALFORMED_CALLDATA",
        summary="Rejected truncated ERC-20 transfer calldata",
        deltas=[],
        is_malformed=True,
        validation_error="Truncated calldata (72 hex chars, expected 136)",
    )
    res = DryRunResult(
        success=True,
        status="SIMULATED_SUCCESS",
        decision="GO",
        tx_params={},
        gas_estimate=21000,
        gas_price_gwei=10.0,
        gas_cost_phrs=0.00021,
        gas_cost_usd=0.000525,
        state_prediction=pred,
    )

    verdict = gate.evaluate(res)
    assert verdict.action_allowed is False
    assert verdict.status == "BLOCKED"
    assert "calldata" in verdict.reason.lower()
