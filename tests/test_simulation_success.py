"""
Unit Tests: Successful Dry-Run Simulations & Cost Modeling
"""

import os
import json
import pytest

from executor.simulator import DryRunSimulator


@pytest.fixture
def fixtures_dict():
    path = os.path.join(os.path.dirname(__file__), "..", "assets", "test_transactions.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)["fixtures"]


def test_simulate_valid_native_transfer(fixtures_dict):
    sim = DryRunSimulator()
    res = sim.simulate_fixture(fixtures_dict["valid_native_transfer"])

    assert res.success is True
    assert res.status == "SIMULATED_SUCCESS"
    assert res.decision == "GO"
    assert res.gas_estimate == 21000
    assert res.gas_price_gwei == 10.0
    assert res.gas_cost_phrs == pytest.approx(0.00021, rel=1e-5)
    assert res.gas_cost_usd == pytest.approx(0.000525, rel=1e-5)
    assert res.revert_info is None
    assert res.state_prediction is not None
    assert res.state_prediction.tx_type == "NATIVE_TRANSFER"


def test_simulate_valid_erc20_approve(fixtures_dict):
    sim = DryRunSimulator()
    res = sim.simulate_fixture(fixtures_dict["valid_erc20_approve"])

    assert res.success is True
    assert res.status == "SIMULATED_SUCCESS"
    assert res.decision == "GO"
    assert res.gas_estimate == 45000
    assert res.state_prediction is not None
    assert res.state_prediction.tx_type == "ERC20_APPROVE"
    assert len(res.state_prediction.deltas) >= 2


def test_simulate_valid_erc20_transfer(fixtures_dict):
    sim = DryRunSimulator()
    res = sim.simulate_fixture(fixtures_dict["valid_erc20_transfer"])

    assert res.success is True
    assert res.status == "SIMULATED_SUCCESS"
    assert res.decision == "GO"
    assert res.gas_estimate == 52000
    assert res.state_prediction is not None
    assert res.state_prediction.tx_type == "ERC20_TRANSFER"
    # Sender and recipient token deltas
    deltas = res.state_prediction.deltas
    tok_deltas = [d for d in deltas if d.asset_type == "ERC20_BALANCE"]
    assert len(tok_deltas) == 2
    sender_d = [d for d in tok_deltas if d.entity == "Token Sender"][0]
    recip_d = [d for d in tok_deltas if d.entity == "Token Recipient"][0]
    assert sender_d.delta == -250000000
    assert recip_d.delta == 250000000
