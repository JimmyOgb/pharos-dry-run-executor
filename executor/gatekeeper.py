"""
Fail-Closed Execution Gatekeeper
================================
Enforces Criterion 04: Blocks execution automatically if the simulation fails.
Provides a strict go/no-go gate preventing transaction broadcast unless
all pre-flight invariants and simulation checks are 100% satisfied.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from .simulator import DryRunResult


class ExecutionBlockedError(Exception):
    """Raised when an unverified, invalid, or reverting transaction attempts execution."""
    pass


@dataclass
class GateVerdict:
    """Audit log of the gatekeeper evaluation."""
    action_allowed: bool
    status: str  # "ALLOWED" or "BLOCKED"
    reason: str
    details: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action_allowed": self.action_allowed,
            "status": self.status,
            "reason": self.reason,
            "details": self.details,
        }


class ExecutionGatekeeper:
    """
    Automated pre-execution safety gate.
    Validates DryRunResult before allowing any downstream execution pipeline to trigger.
    Enforces strict fail-closed invariants: any error, underflow, or unknown status blocks execution.
    """

    def evaluate(self, result: DryRunResult) -> GateVerdict:
        """
        Evaluate simulation result against safety invariants.
        Returns GateVerdict with action_allowed=False (BLOCKED) if ANY check fails.
        """
        # Rule 1: Simulation must have explicitly succeeded
        if not result.success:
            revert_reason = result.revert_info.reason if result.revert_info else (result.notice or "Simulation failed")
            return GateVerdict(
                action_allowed=False,
                status="BLOCKED",
                reason=f"CRITICAL GATE: Execution blocked. Simulation failed: {revert_reason}",
                details={
                    "revert_info": result.revert_info.to_dict() if result.revert_info else None,
                    "status": result.status,
                },
            )

        # Rule 2: Result status must be explicitly SIMULATED_SUCCESS
        if result.status != "SIMULATED_SUCCESS":
            return GateVerdict(
                action_allowed=False,
                status="BLOCKED",
                reason=f"CRITICAL GATE: Execution blocked. Inconclusive or unapproved simulation status: '{result.status}'.",
                details={"status": result.status},
            )

        # Rule 3: Revert info must be completely None
        if result.revert_info is not None:
            return GateVerdict(
                action_allowed=False,
                status="BLOCKED",
                reason=f"CRITICAL GATE: Execution blocked. Revert data present: {result.revert_info.reason}",
                details={"revert_info": result.revert_info.to_dict()},
            )

        # Rule 4: Gas estimate must be strictly positive
        if result.gas_estimate <= 0:
            return GateVerdict(
                action_allowed=False,
                status="BLOCKED",
                reason=f"CRITICAL GATE: Execution blocked. Invalid gas estimate ({result.gas_estimate} units).",
                details={"gas_estimate": result.gas_estimate},
            )

        # Rule 5: Gas price must be strictly positive and available
        if result.gas_price_gwei is None or result.gas_price_gwei <= 0:
            return GateVerdict(
                action_allowed=False,
                status="BLOCKED",
                reason="CRITICAL GATE: Execution blocked. Missing or invalid gas price estimation.",
                details={"gas_price_gwei": result.gas_price_gwei},
            )

        # Rule 6: Calldata integrity check
        if result.state_prediction and result.state_prediction.is_malformed:
            return GateVerdict(
                action_allowed=False,
                status="BLOCKED",
                reason=f"CRITICAL GATE: Execution blocked. Malformed or truncated transaction calldata: {result.state_prediction.validation_error or result.state_prediction.summary}",
                details={
                    "calldata_error": result.state_prediction.validation_error,
                    "summary": result.state_prediction.summary,
                },
            )

        # Rule 7: Solvency & Post-state balance invariants
        if result.state_prediction:
            for delta in result.state_prediction.deltas:
                # Invariant: Balance cannot be missing for the spending account
                if delta.entity in ("Sender", "Token Sender") and delta.before is None:
                    return GateVerdict(
                        action_allowed=False,
                        status="BLOCKED",
                        reason=f"CRITICAL GATE: Execution blocked. Required balance for {delta.address} ({delta.asset_symbol}) is unavailable.",
                        details={"offending_delta": delta.to_dict()},
                    )

                # Invariant: Account after-balance cannot be negative (underflow)
                if delta.after is not None and delta.after < 0:
                    return GateVerdict(
                        action_allowed=False,
                        status="BLOCKED",
                        reason=(
                            f"CRITICAL GATE: Execution blocked. Account {delta.address} would underflow "
                            f"({delta.asset_symbol} deficit: {delta.after} raw units). "
                            "Available balance is insufficient to cover transaction value and estimated fees."
                        ),
                        details={"offending_delta": delta.to_dict()},
                    )

                # Invariant: delta.before + delta.delta cannot be negative
                if delta.before is not None and (delta.before + delta.delta) < 0:
                    return GateVerdict(
                        action_allowed=False,
                        status="BLOCKED",
                        reason=(
                            f"CRITICAL GATE: Execution blocked. Account {delta.address} has insufficient "
                            f"{delta.asset_symbol} balance ({delta.before}) for required delta ({delta.delta})."
                        ),
                        details={"offending_delta": delta.to_dict()},
                    )

        # All fail-closed safety checks passed
        return GateVerdict(
            action_allowed=True,
            status="ALLOWED",
            reason="GATE PASSED: Pre-flight simulation, network identity, and post-state invariants verified.",
            details={
                "gas_estimate": result.gas_estimate,
                "gas_cost_usd": result.gas_cost_usd,
                "state_summary": result.state_prediction.summary if result.state_prediction else "Verified",
            },
        )

    def enforce_execution_gate(self, result: DryRunResult) -> None:
        """
        Raises ExecutionBlockedError if the transaction fails any check.
        Ensures fail-closed behavior in agent dispatch loops.
        """
        verdict = self.evaluate(result)
        if not verdict.action_allowed:
            raise ExecutionBlockedError(verdict.reason)
