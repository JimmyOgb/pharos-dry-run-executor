#!/usr/bin/env python3
"""
Pharos Dry-Run Visualizer Server
================================
Lightweight local HTTP server for interactive reviewer evaluation & demo videos.
Zero external framework dependencies.
"""

from __future__ import annotations

import json
import mimetypes
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict

# Ensure repository root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from executor.client import PharosClient
from executor.gatekeeper import ExecutionGatekeeper
from executor.simulator import DryRunSimulator

PORT = 8088
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
WEB_DIR = os.path.join(REPO_ROOT, "web")
ASSETS_DIR = os.path.join(REPO_ROOT, "assets")

client = PharosClient()
simulator = DryRunSimulator(
    client=client,
    tokens_registry_path=os.path.join(ASSETS_DIR, "tokens.json"),
)
gatekeeper = ExecutionGatekeeper()


class DryRunServerHandler(BaseHTTPRequestHandler):
    """Custom request handler serving static files and dry-run simulation API."""

    def _send_json(self, status: int, data: Dict[str, Any]) -> None:
        payload = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_OPTIONS(self) -> None:
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:
        path = self.path.split("?")[0]

        # Health endpoint
        if path == "/api/health":
            self._send_json(200, {
                "status": "healthy",
                "service": "pharos-dry-run-executor",
                "chain_id": 688689,
                "network": "Pharos Atlantic Testnet",
            })
            return

        # Fixtures endpoint
        if path == "/api/fixtures":
            fixtures_path = os.path.join(ASSETS_DIR, "test_transactions.json")
            if os.path.exists(fixtures_path):
                with open(fixtures_path, "r", encoding="utf-8") as f:
                    self._send_json(200, json.load(f))
            else:
                self._send_json(404, {"error": "Fixtures not found"})
            return

        # Serve static assets
        if path.startswith("/assets/"):
            rel_path = path[len("/assets/"):]
            file_path = os.path.join(ASSETS_DIR, rel_path)
        elif path == "/" or path == "/index.html":
            file_path = os.path.join(WEB_DIR, "index.html")
        else:
            file_path = os.path.join(WEB_DIR, path.lstrip("/"))

        if os.path.exists(file_path) and os.path.isfile(file_path):
            mime_type, _ = mimetypes.guess_type(file_path)
            mime_type = mime_type or "application/octet-stream"
            try:
                with open(file_path, "rb") as f:
                    content = f.read()
                self.send_response(200)
                self.send_header("Content-Type", mime_type)
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
            except Exception as e:
                self.send_error(500, f"Error reading file: {e}")
        else:
            self.send_error(404, "File not found")

    def do_POST(self) -> None:
        if self.path == "/api/simulate":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8")
            try:
                data = json.loads(body)
            except Exception:
                self._send_json(400, {"error": "Invalid JSON body"})
                return

            tx_from = data.get("from", "0x1111111111111111111111111111111111111111")
            tx_to = data.get("to", "0x2222222222222222222222222222222222222222")
            tx_val_str = str(data.get("value", "0"))
            tx_val = int(tx_val_str, 16) if tx_val_str.startswith("0x") else int(tx_val_str)
            tx_data = data.get("data", "0x")
            mode = data.get("mode", "sandbox")

            if mode == "live":
                sim_result = simulator.simulate_live(
                    sender=tx_from,
                    recipient=tx_to,
                    value_wei=tx_val,
                    data_hex=tx_data,
                )
            else:
                # Find matching fixture or synthetic
                fixtures_path = os.path.join(ASSETS_DIR, "test_transactions.json")
                matched_fixture = None
                if os.path.exists(fixtures_path):
                    with open(fixtures_path, "r", encoding="utf-8") as f:
                        fixtures_data = json.load(f).get("fixtures", {})
                        for f_id, f_val in fixtures_data.items():
                            if f_val.get("data", "").lower() == tx_data.lower() and f_val.get("to", "").lower() == tx_to.lower():
                                matched_fixture = f_val
                                break

                if matched_fixture:
                    sim_result = simulator.simulate_fixture(matched_fixture)
                else:
                    synthetic = {
                        "id": "custom",
                        "from": tx_from,
                        "to": tx_to,
                        "value": str(tx_val),
                        "data": tx_data,
                        "expected_success": not (
                            tx_data.startswith("0x08c379a0") or tx_data.startswith("0x4e487b71") or tx_data.startswith("0xd92e233d")
                        ),
                    }
                    sim_result = simulator.simulate_fixture(synthetic)

            verdict = gatekeeper.evaluate(sim_result)
            response_payload = {
                "success": sim_result.success,
                "status": sim_result.status,
                "decision": sim_result.decision,
                "gas": sim_result.gas_estimate,
                "gwei": sim_result.gas_price_gwei,
                "gas_cost_phrs": sim_result.gas_cost_phrs,
                "gas_cost_usd": sim_result.gas_cost_usd,
                "revert": sim_result.revert_info.to_dict() if sim_result.revert_info else None,
                "tx_type": sim_result.state_prediction.tx_type if sim_result.state_prediction else None,
                "summary": sim_result.state_prediction.summary if sim_result.state_prediction else None,
                "deltas": [
                    {
                        "entity": d.entity,
                        "address": d.address,
                        "asset": f"{d.asset_symbol} ({d.asset_type})",
                        "before": d.to_dict()["before_formatted"],
                        "after": d.to_dict()["after_formatted"],
                        "delta": f"{d.to_dict()['delta_formatted']} {d.unit}",
                    }
                    for d in (sim_result.state_prediction.deltas if sim_result.state_prediction else [])
                ],
                "gate": verdict.to_dict(),
            }
            self._send_json(200, response_payload)
            return

        self.send_error(404, "Endpoint not found")


def run(port: int = PORT) -> None:
    server_address = ("", port)
    httpd = HTTPServer(server_address, DryRunServerHandler)
    print(f"Pharos Dry-Run Visualizer Server running at http://localhost:{port}/")
    print("Serving web/index.html & assets. Press Ctrl+C to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server.")
        httpd.server_close()


if __name__ == "__main__":
    port_arg = PORT
    if len(sys.argv) > 1:
        try:
            port_arg = int(sys.argv[1])
        except ValueError:
            pass
    run(port_arg)
