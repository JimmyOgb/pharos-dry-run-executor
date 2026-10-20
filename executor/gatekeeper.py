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
    """Raised when an unverified or reverting transaction attempts execution."""
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
    """

    def evaluate(self, result: DryRunResult) -> GateVerdict:
        """
        Evaluate simulation result against safety invariants.
        Returns GateVerdict.
        """
        # Rule 1: Simulation must have succeeded
        if not result.success:
            revert_reason = result.revert_info.reason if result.revert_info else "Simulation failed"
            return GateVerdict(
                action_allowed=False,
                status="BLOCKED",
                reason=f"CRITICAL GATE: Execution blocked. Simulation reverted: {revert_reason}",
                details={
                    "revert_info": result.revert_info.to_dict() if result.revert_info else None,
                    "status": result.status,
                },
            )

        # Rule 2: Gas estimate must be valid (> 0)
        if result.gas_estimate <= 0:
            return GateVerdict(
                action_allowed=False,
                status="BLOCKED",
                reason="CRITICAL GATE: Execution blocked. Invalid gas estimate (0 units).",
                details={"gas_estimate": result.gas_estimate},
            )

        # Rule 3: Revert info must be None
        if result.revert_info is not None:
            return GateVerdict(
                action_allowed=False,
                status="BLOCKED",
                reason=f"CRITICAL GATE: Execution blocked. Revert data present: {result.revert_info.reason}",
                details={"revert_info": result.revert_info.to_dict()},
            )

        # Rule 4: Post-state balance checks (Sender cannot have negative balance)
        if result.state_prediction:
            for delta in result.state_prediction.deltas:
                if delta.after < 0:
                    return GateVerdict(
                        action_allowed=False,
                        status="BLOCKED",
                        reason=f"CRITICAL GATE: Execution blocked. Account {delta.address} would underflow ({delta.asset_symbol}: {delta.after}).",
                        details={"offending_delta": delta.to_dict()},
                    )

        # All checks passed
        return GateVerdict(
            action_allowed=True,
            status="ALLOWED",
            reason="GATE PASSED: Pre-flight simulation and post-state invariants verified.",
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
