"""
Live Atlantic Testnet Integration Tests (Chain ID: 688689)
Gated by environment variable PHAROS_LIVE_TESTS=1.
"""

import os
import pytest

from executor.client import PharosClient
from executor.simulator import DryRunSimulator

MULTICALL3_ADDRESS = "0xcA11bde05977b3631167028862bE2a173976CA11"
ALICE_ADDRESS = "0x1111111111111111111111111111111111111111"


@pytest.mark.skipif(
    os.environ.get("PHAROS_LIVE_TESTS") != "1",
    reason="Live testnet tests disabled unless PHAROS_LIVE_TESTS=1"
)
def test_live_atlantic_connectivity():
    client = PharosClient()
    block_num = client.eth_block_number()
    assert block_num > 0

    gas_price = client.eth_gas_price()
    assert gas_price > 0


@pytest.mark.skipif(
    os.environ.get("PHAROS_LIVE_TESTS") != "1",
    reason="Live testnet tests disabled unless PHAROS_LIVE_TESTS=1"
)
def test_live_atlantic_dry_run_call():
    client = PharosClient()
    sim = DryRunSimulator(client=client)

    # Simulate read-only call to canonical Multicall3 getBlockNumber()
    res = sim.simulate_live(
        sender=ALICE_ADDRESS,
        recipient=MULTICALL3_ADDRESS,
        value_wei=0,
        data_hex="0x42cbb15c",
    )

    assert res.execution_mode == "LIVE_ATLANTIC"
    assert res.success is True
    assert res.decision == "GO"
    assert res.gas_estimate > 0
    assert res.block_number is not None
