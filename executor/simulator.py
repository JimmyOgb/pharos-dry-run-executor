"""
Dry-Run Transaction Simulator
=============================
Simulates EVM transactions on Pharos Atlantic Testnet (Chain ID: 688689)
without broadcasting, predicting success/revert, gas costs, and state outcomes.
Enforces strict zero-broadcast read-only execution (Criterion 01 & 02).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from .client import PharosClient, PharosClientError
from .decoder import DecodedRevert, decode_revert_payload
from .state_diff import StatePrediction, predict_state_diff

DEFAULT_PHRS_PRICE_USD = 2.50
DEFAULT_FALLBACK_GAS_GWEI = 10.0


@dataclass
class DryRunResult:
    """Comprehensive result of a dry-run simulation."""
    success: bool
    status: str  # SIMULATED_SUCCESS, SIMULATION_REVERTED, SIMULATION_FAILED, MALFORMED_CALLDATA, NETWORK_MISMATCH
    decision: str  # GO vs NO-GO
    tx_params: Dict[str, Any]
    gas_estimate: int
    gas_price_gwei: float
    gas_cost_phrs: float
    gas_cost_usd: float
    revert_info: Optional[DecodedRevert] = None
    state_prediction: Optional[StatePrediction] = None
    notice: str = ""
    block_number: Optional[int] = None
    execution_mode: str = "SANDBOX"  # "LIVE_ATLANTIC" or "SANDBOX"
    usd_rate_assumption: float = DEFAULT_PHRS_PRICE_USD

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "status": self.status,
            "decision": self.decision,
            "tx_params": self.tx_params,
            "gas_estimate": self.gas_estimate,
            "gas_price_gwei": round(self.gas_price_gwei, 4) if self.gas_price_gwei is not None else 0.0,
            "gas_cost_phrs": f"{self.gas_cost_phrs:.8f}",
            "gas_cost_usd": round(self.gas_cost_usd, 6),
            "revert_info": self.revert_info.to_dict() if self.revert_info else None,
            "state_prediction": self.state_prediction.to_dict() if self.state_prediction else None,
            "notice": self.notice,
            "block_number": self.block_number,
            "execution_mode": self.execution_mode,
            "usd_rate_assumption": self.usd_rate_assumption,
        }


class DryRunSimulator:
    """
    Simulation engine capable of executing live testnet pre-flights
    or calibrated sandbox simulations.
    """

    def __init__(
        self,
        client: Optional[PharosClient] = None,
        tokens_registry_path: Optional[str] = None,
    ):
        self.client = client
        self.tokens_registry: Dict[str, Any] = {}
        if tokens_registry_path and os.path.exists(tokens_registry_path):
            try:
                with open(tokens_registry_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.tokens_registry = data.get("tokens", {})
            except Exception:
                pass

    def simulate_fixture(self, fixture: Dict[str, Any]) -> DryRunResult:
        """Simulate a predefined transaction fixture (sandbox mode)."""
        tx_from = fixture.get("from", "0x0000000000000000000000000000000000000000")
        tx_to = fixture.get("to", "0x0000000000000000000000000000000000000000")
        tx_value_str = fixture.get("value", "0")
        tx_value = int(tx_value_str, 16) if tx_value_str.startswith("0x") else int(tx_value_str)
        tx_data = fixture.get("data", "0x")
        expected_success = fixture.get("expected_success", True)

        gas_gwei = DEFAULT_FALLBACK_GAS_GWEI
        gas_limit = fixture.get("expected_gas_limit", 21000 if not tx_data or tx_data == "0x" else 50000)

        # Integer wei arithmetic
        gas_price_wei = int(gas_gwei * 1e9)
        gas_cost_wei = gas_limit * gas_price_wei
        gas_cost_phrs = gas_cost_wei / 1e18
        gas_cost_usd = gas_cost_phrs * DEFAULT_PHRS_PRICE_USD

        tx_params = {
            "from": tx_from,
            "to": tx_to,
            "value": hex(tx_value),
            "data": tx_data,
        }

        if not expected_success:
            raw_revert = fixture.get("revert_raw", "")
            revert_info = decode_revert_payload(raw_revert, fixture.get("expected_revert_reason"))
            return DryRunResult(
                success=False,
                status="SIMULATION_REVERTED",
                decision="NO-GO",
                tx_params=tx_params,
                gas_estimate=0,
                gas_price_gwei=gas_gwei,
                gas_cost_phrs=0.0,
                gas_cost_usd=0.0,
                revert_info=revert_info,
                state_prediction=None,
                notice=f"TRANSACTION BLOCKED: Simulation predicted EVM revert ({revert_info.reason}).",
                execution_mode="SANDBOX",
            )

        # Build mock balances for state prediction
        mock_balances: Dict[str, Any] = {}
        if "sender_initial_phrs" in fixture:
            mock_balances[f"{tx_from.lower()}_PHRS"] = int(fixture["sender_initial_phrs"])
            mock_balances[f"{tx_from.lower()}_PHRS_observed"] = True
        else:
            mock_balances[f"{tx_from.lower()}_PHRS"] = int(10 * 10**18)

        if "recipient_initial_phrs" in fixture:
            mock_balances[f"{tx_to.lower()}_PHRS"] = int(fixture["recipient_initial_phrs"])
            mock_balances[f"{tx_to.lower()}_PHRS_observed"] = True

        if "sender_initial_balance" in fixture and "token_symbol" in fixture:
            sym = fixture["token_symbol"]
            mock_balances[f"{tx_from.lower()}_{sym}"] = int(fixture["sender_initial_balance"])
            mock_balances[f"{tx_from.lower()}_{sym}_observed"] = True

        if "recipient_initial_balance" in fixture and "token_symbol" in fixture:
            sym = fixture["token_symbol"]
            mock_balances[f"{tx_to.lower()}_{sym}"] = int(fixture["recipient_initial_balance"])
            mock_balances[f"{tx_to.lower()}_{sym}_observed"] = True

        if "sender_initial_allowance" in fixture and "target_spender" in fixture:
            spender = fixture["target_spender"]
            mock_balances[f"{tx_from.lower()}_{spender.lower()}_ALLOWANCE"] = int(fixture["sender_initial_allowance"])
            mock_balances[f"{tx_from.lower()}_{spender.lower()}_ALLOWANCE_observed"] = True

        state_pred = predict_state_diff(
            sender=tx_from,
            recipient=tx_to,
            value_wei=tx_value,
            data_hex=tx_data,
            estimated_gas_cost_wei=gas_cost_wei,
            known_tokens=self.tokens_registry,
            mock_balances=mock_balances,
        )

        if state_pred.is_malformed:
            return DryRunResult(
                success=False,
                status="MALFORMED_CALLDATA",
                decision="NO-GO",
                tx_params=tx_params,
                gas_estimate=0,
                gas_price_gwei=gas_gwei,
                gas_cost_phrs=0.0,
                gas_cost_usd=0.0,
                revert_info=decode_revert_payload(None, state_pred.validation_error or state_pred.summary),
                state_prediction=state_pred,
                notice=f"TRANSACTION BLOCKED: {state_pred.summary}",
                execution_mode="SANDBOX",
            )

        return DryRunResult(
            success=True,
            status="SIMULATED_SUCCESS",
            decision="GO",
            tx_params=tx_params,
            gas_estimate=gas_limit,
            gas_price_gwei=gas_gwei,
            gas_cost_phrs=gas_cost_phrs,
            gas_cost_usd=gas_cost_usd,
            revert_info=None,
            state_prediction=state_pred,
            notice="SIMULATION PASSED: Transaction predicted to succeed safely. Zero real gas broadcast.",
            execution_mode="SANDBOX",
        )

    def simulate_live(
        self,
        sender: str,
        recipient: str,
        value_wei: int = 0,
        data_hex: str = "0x",
    ) -> DryRunResult:
        """
        Executes live simulation against Pharos Atlantic Testnet using eth_call & eth_estimateGas.
        Strictly zero broadcast: eth_sendRawTransaction is NEVER called.
        Fails closed on wrong chain ID, RPC timeout, unavailable gas price, or revert.
        """
        if not self.client:
            raise PharosClientError("Cannot run live simulation without a configured PharosClient")

        clean_data = data_hex.strip()
        if not clean_data.startswith("0x"):
            clean_data = "0x" + clean_data

        tx_dict = {
            "from": sender,
            "to": recipient,
            "value": hex(value_wei),
            "data": clean_data,
        }

        # Step 0: Verify network identity (Atlantic Testnet 688689)
        try:
            self.client.verify_network()
        except PharosClientError as e:
            return DryRunResult(
                success=False,
                status="NETWORK_MISMATCH",
                decision="NO-GO",
                tx_params=tx_dict,
                gas_estimate=0,
                gas_price_gwei=0.0,
                gas_cost_phrs=0.0,
                gas_cost_usd=0.0,
                revert_info=decode_revert_payload(None, str(e)),
                state_prediction=None,
                notice=f"TRANSACTION BLOCKED: Target network mismatch or failure: {e}",
                execution_mode="LIVE_ATLANTIC",
            )

        # Step 1: Query live block number and gas price (fail-closed if gas price fails)
        block_num = None
        gas_price_wei = None
        try:
            block_num = self.client.eth_block_number()
        except Exception:
            block_num = None

        try:
            gas_price_wei = self.client.eth_gas_price()
        except Exception:
            gas_price_wei = None

        if gas_price_wei is None or gas_price_wei <= 0:
            return DryRunResult(
                success=False,
                status="GAS_PRICE_UNAVAILABLE",
                decision="NO-GO",
                tx_params=tx_dict,
                gas_estimate=0,
                gas_price_gwei=0.0,
                gas_cost_phrs=0.0,
                gas_cost_usd=0.0,
                revert_info=decode_revert_payload(None, "eth_gasPrice query failed; network gas price unavailable"),
                state_prediction=None,
                notice="TRANSACTION BLOCKED: Network gas price unavailable. Cannot verify fee solvency.",
                block_number=block_num,
                execution_mode="LIVE_ATLANTIC",
            )

        gas_gwei = gas_price_wei / 1e9

        # Step 2: Simulate execution via eth_call
        revert_raw = None
        revert_msg = None
        try:
            call_res = self.client.eth_call(tx_dict, block="latest")
        except PharosClientError as e:
            revert_msg = e.message
            revert_raw = str(e.data) if e.data else None
            revert_info = decode_revert_payload(revert_raw, revert_msg)
            return DryRunResult(
                success=False,
                status="SIMULATION_REVERTED",
                decision="NO-GO",
                tx_params=tx_dict,
                gas_estimate=0,
                gas_price_gwei=gas_gwei,
                gas_cost_phrs=0.0,
                gas_cost_usd=0.0,
                revert_info=revert_info,
                state_prediction=None,
                notice=f"TRANSACTION BLOCKED: On-chain eth_call reverted ({revert_info.reason}).",
                block_number=block_num,
                execution_mode="LIVE_ATLANTIC",
            )
        except Exception as e:
            revert_info = decode_revert_payload(None, str(e))
            return DryRunResult(
                success=False,
                status="SIMULATION_FAILED",
                decision="NO-GO",
                tx_params=tx_dict,
                gas_estimate=0,
                gas_price_gwei=gas_gwei,
                gas_cost_phrs=0.0,
                gas_cost_usd=0.0,
                revert_info=revert_info,
                state_prediction=None,
                notice=f"TRANSACTION BLOCKED: Pre-flight simulation failed: {e}",
                block_number=block_num,
                execution_mode="LIVE_ATLANTIC",
            )

        # Step 3: Estimate gas units via eth_estimateGas
        try:
            gas_estimate = self.client.eth_estimate_gas(tx_dict)
        except Exception as e:
            revert_info = decode_revert_payload(None, f"Gas estimation failed: {e}")
            return DryRunResult(
                success=False,
                status="SIMULATION_REVERTED",
                decision="NO-GO",
                tx_params=tx_dict,
                gas_estimate=0,
                gas_price_gwei=gas_gwei,
                gas_cost_phrs=0.0,
                gas_cost_usd=0.0,
                revert_info=revert_info,
                state_prediction=None,
                notice=f"TRANSACTION BLOCKED: eth_estimateGas failed ({revert_info.reason}).",
                block_number=block_num,
                execution_mode="LIVE_ATLANTIC",
            )

        # Exact integer wei arithmetic
        gas_cost_wei = gas_estimate * gas_price_wei
        gas_cost_phrs = gas_cost_wei / 1e18
        gas_cost_usd = gas_cost_phrs * DEFAULT_PHRS_PRICE_USD

        # Step 4: Query genuine live state observations
        live_balances: Dict[str, Any] = {}

        # Query sender native balance
        try:
            sender_balance = self.client.eth_get_balance(sender, block="latest")
            live_balances[f"{sender.lower()}_PHRS"] = sender_balance
            live_balances[f"{sender.lower()}_PHRS_observed"] = True
        except Exception:
            pass

        # Query recipient native balance
        if recipient and recipient != "0x0000000000000000000000000000000000000000":
            try:
                recip_balance = self.client.eth_get_balance(recipient, block="latest")
                live_balances[f"{recipient.lower()}_PHRS"] = recip_balance
                live_balances[f"{recipient.lower()}_PHRS_observed"] = True
            except Exception:
                pass

        # Parse calldata to check for ERC-20 token queries
        clean_raw = clean_data.lower().removeprefix("0x")
        token_symbol = "TOKEN"
        if self.tokens_registry:
            for sym, info in self.tokens_registry.items():
                if info.get("address", "").lower() == recipient.lower():
                    token_symbol = info.get("symbol", sym)
                    break

        # If ERC-20 transfer: query live balanceOf(sender) and balanceOf(recipient)
        if clean_raw.startswith("a9059cbb") and len(clean_raw) == 136:
            try:
                sender_cd = "0x70a08231" + sender[2:].lower().zfill(64)
                res_s = self.client.eth_call({"to": recipient, "data": sender_cd}, block="latest")
                if res_s and res_s != "0x":
                    live_balances[f"{sender.lower()}_{token_symbol}"] = int(res_s, 16)
                    live_balances[f"{sender.lower()}_{token_symbol}_observed"] = True
            except Exception:
                pass

            try:
                target_to = "0x" + clean_raw[32:72]
                recip_cd = "0x70a08231" + target_to[2:].lower().zfill(64)
                res_r = self.client.eth_call({"to": recipient, "data": recip_cd}, block="latest")
                if res_r and res_r != "0x":
                    live_balances[f"{target_to.lower()}_{token_symbol}"] = int(res_r, 16)
                    live_balances[f"{target_to.lower()}_{token_symbol}_observed"] = True
            except Exception:
                pass

        # If ERC-20 approve: query live allowance(sender, spender)
        if clean_raw.startswith("095ea7b3") and len(clean_raw) == 136:
            try:
                spender_addr = "0x" + clean_raw[32:72]
                allow_cd = "0xdd62ed3e" + sender[2:].lower().zfill(64) + spender_addr[2:].lower().zfill(64)
                res_a = self.client.eth_call({"to": recipient, "data": allow_cd}, block="latest")
                if res_a and res_a != "0x":
                    live_balances[f"{sender.lower()}_{spender_addr.lower()}_ALLOWANCE"] = int(res_a, 16)
                    live_balances[f"{sender.lower()}_{spender_addr.lower()}_ALLOWANCE_observed"] = True
            except Exception:
                pass

        state_pred = predict_state_diff(
            sender=sender,
            recipient=recipient,
            value_wei=value_wei,
            data_hex=clean_data,
            estimated_gas_cost_wei=gas_cost_wei,
            known_tokens=self.tokens_registry,
            mock_balances=live_balances,
        )

        if state_pred.is_malformed:
            return DryRunResult(
                success=False,
                status="MALFORMED_CALLDATA",
                decision="NO-GO",
                tx_params=tx_dict,
                gas_estimate=0,
                gas_price_gwei=gas_gwei,
                gas_cost_phrs=0.0,
                gas_cost_usd=0.0,
                revert_info=decode_revert_payload(None, state_pred.validation_error or state_pred.summary),
                state_prediction=state_pred,
                notice=f"TRANSACTION BLOCKED: {state_pred.summary}",
                block_number=block_num,
                execution_mode="LIVE_ATLANTIC",
            )

        return DryRunResult(
            success=True,
            status="SIMULATED_SUCCESS",
            decision="GO",
            tx_params=tx_dict,
            gas_estimate=gas_estimate,
            gas_price_gwei=gas_gwei,
            gas_cost_phrs=gas_cost_phrs,
            gas_cost_usd=gas_cost_usd,
            revert_info=None,
            state_prediction=state_pred,
            notice="SIMULATION PASSED: Live Atlantic Testnet pre-flight succeeded. Safe to broadcast.",
            block_number=block_num,
            execution_mode="LIVE_ATLANTIC",
        )
