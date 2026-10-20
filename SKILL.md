---
name: pharos-dry-run-executor
description: >
  On-chain transaction simulation and pre-flight execution gatekeeper for the Pharos blockchain. Evaluates eth_call and eth_estimateGas without broadcasting, decodes EVM revert reasons (Error(string), Panic(uint256), custom contract errors), calculates precise gas costs in PHRS and USD, predicts before/after account balance and allowance deltas, and automatically blocks failing transactions.
version: 0.1.0
requires:
  anyBins:
  - python3
  - python
---

# Pharos Dry-Run Executor

A SkillEngine-compatible pre-flight execution simulator and safety gatekeeper that simulates transactions on Pharos Atlantic Testnet (`Chain ID: 688689`) before submission, predicting whether they will succeed, what they will cost, what state they will alter, and automatically blocking execution if the simulation fails.

## Capability Index

| User Need | Capability | Detailed Instructions |
|---|---|---|
| Simulate predefined test fixture | `pharos-dry-run --fixture <id>` | `references/dry-run.md#simulating-a-pre-configured-fixture` |
| Simulate custom transfer or contract call | `pharos-dry-run --from <addr> --to <addr> --value <wei> --data <hex>` | `references/dry-run.md#simulating-a-custom-transaction` |
| Live Atlantic Testnet pre-flight simulation | `pharos-dry-run --live --from <addr> --to <addr>` | `references/dry-run.md#live-atlantic-testnet-simulation` |
| Stream machine-readable JSON simulation trace | `pharos-dry-run --json` | `references/dry-run.md#command-reference` |
| Launch interactive visualizer dashboard | `python scripts/server.py` | `README.md#interactive-web-visualizer` |

## Agent Guidelines Block

When an autonomous AI agent or user intends to broadcast a state-altering transaction on Pharos, the agent MUST follow these safety steps:

1. **Pre-Flight Dry-Run Execution**: Run `python scripts/dry_run.py --live --from <sender> --to <recipient> --data <calldata> --value <wei>` before broadcasting.
2. **Inspect Fail-Closed Gate Verdict**:
   - If `verdict.status == "ALLOWED"` and `decision == "GO"`: Simulation succeeded, gas limit and costs are estimated, and post-state deltas are verified. Proceed with signature and broadcast.
   - If `verdict.status == "BLOCKED"` or `decision == "NO-GO"`: The transaction reverted or gas estimation failed. The agent MUST NOT broadcast the transaction. Log the decoded revert reason (`revert_info.reason`) and notify the user.
3. **Fail-Closed Zero-Broadcast Invariant**: Simulation operations utilize read-only EVM calls (`eth_call`, `eth_estimateGas`). `eth_sendRawTransaction` is never executed during pre-flight checks.
