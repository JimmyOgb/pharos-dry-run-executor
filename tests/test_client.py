"""
Unit Tests: Pharos Transport Client & MCP Interface
Includes network identity verification (Chain ID 688689).
"""

import json
from unittest.mock import MagicMock, patch
import pytest

from executor.client import PharosClient, PharosClientError


def test_client_initialization():
    client = PharosClient(rpc_url="https://atlantic.dplabs-internal.com", chain_id=688689)
    assert client.rpc_url == "https://atlantic.dplabs-internal.com"
    assert client.chain_id == 688689
    assert client.timeout == 8.0


@patch("urllib.request.urlopen")
def test_rpc_call_success(mock_urlopen):
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "result": "0x14d1120d7b160000"
    }).encode("utf-8")
    mock_urlopen.return_value.__enter__.return_value = mock_resp

    client = PharosClient()
    res = client.rpc_call("eth_getBalance", ["0x1111111111111111111111111111111111111111", "latest"])
    assert res == "0x14d1120d7b160000"


@patch("urllib.request.urlopen")
def test_rpc_call_error_propagation(mock_urlopen):
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "error": {
            "code": -32000,
            "message": "execution reverted: ERC20: transfer amount exceeds balance",
            "data": "0x08c379a0"
        }
    }).encode("utf-8")
    mock_urlopen.return_value.__enter__.return_value = mock_resp

    client = PharosClient()
    with pytest.raises(PharosClientError) as exc_info:
        client.rpc_call("eth_call", [{}, "latest"])
    assert "execution reverted" in str(exc_info.value)


@patch("urllib.request.urlopen")
def test_convenience_methods(mock_urlopen):
    client = PharosClient()

    # eth_gasPrice
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps({"jsonrpc": "2.0", "id": 1, "result": "0x2540be400"}).encode("utf-8") # 10 Gwei
    mock_urlopen.return_value.__enter__.return_value = mock_resp
    assert client.eth_gas_price() == 10000000000

    # eth_blockNumber
    mock_resp.read.return_value = json.dumps({"jsonrpc": "2.0", "id": 1, "result": "0x100"}).encode("utf-8")
    assert client.eth_block_number() == 256

    # eth_estimateGas
    mock_resp.read.return_value = json.dumps({"jsonrpc": "2.0", "id": 1, "result": "0x5208"}).encode("utf-8") # 21000
    assert client.eth_estimate_gas({"from": "0x1", "to": "0x2"}) == 21000

    # eth_chainId
    mock_resp.read.return_value = json.dumps({"jsonrpc": "2.0", "id": 1, "result": "0xa8231"}).encode("utf-8") # 688689
    assert client.eth_chain_id() == 688689


@patch("urllib.request.urlopen")
def test_verify_network_success(mock_urlopen):
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps({"jsonrpc": "2.0", "id": 1, "result": "0xa8231"}).encode("utf-8")
    mock_urlopen.return_value.__enter__.return_value = mock_resp

    client = PharosClient(chain_id=688689)
    verified_id = client.verify_network()
    assert verified_id == 688689


@patch("urllib.request.urlopen")
def test_verify_network_mismatch_fails_closed(mock_urlopen):
    mock_resp = MagicMock()
    # Mocking Ethereum Mainnet (chain ID 1) instead of Atlantic (688689)
    mock_resp.read.return_value = json.dumps({"jsonrpc": "2.0", "id": 1, "result": "0x1"}).encode("utf-8")
    mock_urlopen.return_value.__enter__.return_value = mock_resp

    client = PharosClient(chain_id=688689)
    with pytest.raises(PharosClientError) as exc_info:
        client.verify_network()
    assert "Network verification failed" in str(exc_info.value)
    assert "expected 688689" in str(exc_info.value)


@patch("urllib.request.urlopen")
def test_verify_network_transport_failure(mock_urlopen):
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps({"jsonrpc": "2.0", "id": 1, "error": {"message": "Network timeout"}}).encode("utf-8")
    mock_urlopen.return_value.__enter__.return_value = mock_resp

    client = PharosClient(chain_id=688689)
    with pytest.raises(PharosClientError) as exc_info:
        client.verify_network()
    assert "Failed to query eth_chainId" in str(exc_info.value) or "RPC Error" in str(exc_info.value)
