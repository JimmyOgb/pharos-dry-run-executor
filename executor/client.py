"""
Pharos Dual-Engine Transport Client
==================================
Dual-engine transport client supporting direct JSON-RPC with curl fallback
and Pharos Hosted Chain MCP (Model Context Protocol).
Strictly read-only with zero broadcast or state-altering capabilities.
"""

from __future__ import annotations

import json
import re
import socket
import subprocess
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

ADDRESS_REGEX = re.compile(r"^0x[a-fA-F0-9]{40}$")
DEFAULT_ATLANTIC_RPC = "https://atlantic.dplabs-internal.com"
DEFAULT_MCP_URL = "https://mcp.pharos.xyz/mcp"
DEFAULT_CHAIN_ID = 688689


class PharosClientError(Exception):
    """Custom exception raised for Pharos transport and communication errors."""
    def __init__(self, message: str, data: Optional[Any] = None):
        super().__init__(message)
        self.message = message
        self.data = data

    def __str__(self) -> str:
        return self.message


class PharosClient:
    """
    Read-only transport client supporting both direct JSON-RPC endpoints and
    the official Pharos Hosted Chain MCP endpoint.
    """

    def __init__(
        self,
        rpc_url: str = DEFAULT_ATLANTIC_RPC,
        mcp_url: str = DEFAULT_MCP_URL,
        chain_id: int = DEFAULT_CHAIN_ID,
        timeout: float = 8.0,
    ):
        self.rpc_url = rpc_url.rstrip("/")
        self.mcp_url = mcp_url.rstrip("/")
        self.chain_id = chain_id
        self.timeout = timeout
        self._mcp_session_id: Optional[str] = None

    def _rpc_call_urllib(self, method: str, params: List[Any]) -> Any:
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": 1,
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.rpc_url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "PharosDryRunExecutor/0.1.0",
            },
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            body = resp.read().decode("utf-8")
            res_json = json.loads(body)
            if "error" in res_json:
                err = res_json["error"]
                err_msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
                err_data = err.get("data") if isinstance(err, dict) else None
                raise PharosClientError(f"RPC Error [{method}]: {err_msg}", err_data)
            return res_json.get("result")

    def _rpc_call_curl_fallback(self, method: str, params: List[Any]) -> Any:
        payload = json.dumps({
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": 1,
        })
        cmd = [
            "curl.exe",
            "-s",
            "--max-time", str(int(self.timeout)),
            "-H", "Content-Type: application/json",
            "--data-binary", "@-",
            self.rpc_url,
        ]
        proc = subprocess.run(cmd, input=payload, capture_output=True, text=True, timeout=self.timeout + 4)
        if proc.returncode != 0:
            raise PharosClientError(f"Curl fallback failed: {proc.stderr}")
        try:
            res_json = json.loads(proc.stdout)
        except json.JSONDecodeError as e:
            raise PharosClientError(f"Failed to decode curl response: {proc.stdout}") from e
        if "error" in res_json:
            err = res_json["error"]
            err_msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
            err_data = err.get("data") if isinstance(err, dict) else None
            raise PharosClientError(f"RPC Error [{method}]: {err_msg}", err_data)
        return res_json.get("result")

    def rpc_call(self, method: str, params: Optional[List[Any]] = None) -> Any:
        """Execute JSON-RPC call with automatic curl fallback for Windows networking."""
        params = params or []
        try:
            return self._rpc_call_urllib(method, params)
        except PharosClientError:
            raise
        except (urllib.error.URLError, socket.timeout, ConnectionResetError, OSError):
            try:
                return self._rpc_call_curl_fallback(method, params)
            except Exception as e:
                raise PharosClientError(f"Connection failure to {self.rpc_url}: {e}") from e

    # Convenience on-chain query methods
    def eth_chain_id(self) -> int:
        """Fetch chain ID from the RPC endpoint."""
        res = self.rpc_call("eth_chainId", [])
        return int(res, 16) if isinstance(res, str) else int(res)

    def verify_network(self, expected_chain_id: Optional[int] = None) -> int:
        """
        Verify that the RPC endpoint chain ID matches expected network (Pharos Atlantic: 688689).
        Fails closed on mismatch, missing result, or communication error.
        """
        expected = expected_chain_id if expected_chain_id is not None else self.chain_id
        try:
            actual_id = self.eth_chain_id()
        except Exception as e:
            raise PharosClientError(f"Failed to query eth_chainId from {self.rpc_url}: {e}") from e

        if actual_id != expected:
            raise PharosClientError(
                f"Network verification failed: RPC endpoint {self.rpc_url} returned "
                f"chain ID {actual_id}, expected {expected} (Pharos Atlantic Testnet)"
            )
        return actual_id

    def eth_call(self, tx_dict: Dict[str, Any], block: str = "latest") -> str:
        """Execute read-only contract call without broadcasting."""
        return self.rpc_call("eth_call", [tx_dict, block])

    def eth_estimate_gas(self, tx_dict: Dict[str, Any]) -> int:
        """Estimate gas units required for a transaction."""
        res = self.rpc_call("eth_estimateGas", [tx_dict])
        return int(res, 16) if isinstance(res, str) else int(res)

    def eth_gas_price(self) -> int:
        """Fetch current network gas price in wei."""
        res = self.rpc_call("eth_gasPrice", [])
        return int(res, 16) if isinstance(res, str) else int(res)

    def eth_block_number(self) -> int:
        """Fetch latest block number."""
        res = self.rpc_call("eth_blockNumber", [])
        return int(res, 16) if isinstance(res, str) else int(res)

    def eth_get_balance(self, address: str, block: str = "latest") -> int:
        """Fetch native balance in wei."""
        res = self.rpc_call("eth_getBalance", [address, block])
        return int(res, 16) if isinstance(res, str) else int(res)

    def eth_get_code(self, address: str, block: str = "latest") -> str:
        """Fetch deployed contract bytecode."""
        return self.rpc_call("eth_getCode", [address, block])

    # Hosted Chain MCP Tool Transport
    def mcp_call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        """Execute an MCP tool call against the official Pharos hosted MCP endpoint."""
        if not self._mcp_session_id:
            init_payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "PharosDryRunExecutor", "version": "0.1.0"},
                },
            }
            req = urllib.request.Request(
                self.mcp_url,
                data=json.dumps(init_payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    self._mcp_session_id = data.get("result", {}).get("sessionId", "active-session")
            except Exception:
                self._mcp_session_id = "default-session"

        call_payload = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        }
        req = urllib.request.Request(
            self.mcp_url,
            data=json.dumps(call_payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Mcp-Session-Id": self._mcp_session_id or "default-session",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data.get("result")
        except Exception as e:
            raise PharosClientError(f"MCP Tool call '{tool_name}' failed: {e}") from e
