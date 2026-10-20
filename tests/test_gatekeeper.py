"""
Unit Tests: Fail-Closed Execution Gatekeeper (Criterion 04)
"""

import pytest

from executor.decoder import DecodedRevert
from executor.gatekeeper import ExecutionBlockedError, ExecutionGatekeeper
from executor.simulator import DryRunResult


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

    # enforce_execution_gate MUST raise ExecutionBlockedError
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
