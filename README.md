# Pharos Dry-Run Executor

> **Pharos Season of AI — Agent Arena Task 8**  
> **Track**: `SkillEngine` | **Difficulty**: `Medium` | **Points**: `100 Base + 50 Video = 150 Pts`  
> **Official Task URL**: [https://pharos-agent-arena.vercel.app/tasks/dry-run-executor](https://pharos-agent-arena.vercel.app/tasks/dry-run-executor)  
> **Participant**: `JimmyOgb` (`https://github.com/JimmyOgb`)  
> **Target Network**: Pharos Atlantic Testnet (`Chain ID: 688689`)

---

## 1. Executive Summary

The **Pharos Dry-Run Executor** is an on-chain transaction simulator and pre-flight execution gatekeeper built according to the Pharos SkillEngine specification. It allows autonomous agents and human developers to execute zero-broadcast simulations on Pharos Atlantic Testnet (`Chain ID: 688689`), predicting whether a transaction will succeed, estimating exact resource and fiat costs, forecasting account balance transitions, and enforcing an automated fail-closed execution gate.

---

## 2. Acceptance Criteria Mapping

| # | Official Acceptance Criterion | Project Implementation & Verification |
|---|---|---|
| **01** | **Uses a call or gas estimation to simulate the transaction without broadcasting it** | Evaluates `eth_call` and `eth_estimateGas` over JSON-RPC. Absolutely zero raw transaction broadcasts (`eth_sendRawTransaction`) occur during simulation. |
| **02** | **Reports predicted success or revert, including the revert reason when available, and estimated gas cost** | EVM revert decoder handles standard `Error(string)` (`0x08c379a0`), Solidity 0.8+ `Panic(uint256)` (`0x4e487b71` with human-readable panic codes like `0x11` overflow), and custom contract errors. Computes gas in PHRS and USD. |
| **03** | **Shows the expected outcome, e.g. balances or state before and after where possible** | Computes pre- vs. post-state balance deltas for native PHRS (transferred value + gas fee), ERC-20 token balances (`balanceOf`), and ERC-20 allowances (`approve`). |
| **04** | **Blocks execution automatically if the simulation fails** | Enforces a fail-closed `ExecutionGatekeeper`. If a simulation reverts or fails invariants, it issues a `BLOCKED` verdict (`NO-GO`), preventing transaction submission. |

---

## 3. Architecture & Module Layout

```text
skills/pharos-dry-run-executor/
├── SKILL.md                          # Pharos SkillEngine entrypoint & Capability Index
├── README.md                         # Complete documentation & audit guide
├── pyproject.toml                    # Python project configuration & pytest tooling
├── vercel.json                       # Vercel SPA routing for web visualizer
├── assets/
│   ├── networks.json                 # Atlantic Testnet (688689) & Mainnet configurations
│   ├── tokens.json                   # Verified token registry (USDC, WPHRS, Permit2, MultiCall3)
│   └── test_transactions.json       # Predefined test transaction fixtures
├── references/
│   └── dry-run.md                    # Machine-readable command templates & schemas
├── executor/
│   ├── __init__.py                   # Package exports
│   ├── client.py                     # Dual-engine transport (JSON-RPC + curl fallback + Chain MCP)
│   ├── simulator.py                  # Core simulation engine: eth_call & eth_estimateGas
│   ├── decoder.py                    # EVM revert decoder: Error(string), Panic, custom errors
│   ├── state_diff.py                 # Balance & allowance transition predictor
│   ├── gatekeeper.py                 # Fail-closed execution gatekeeper
│   └── cli.py                        # Standalone CLI interface (pharos-dry-run)
├── tests/
│   ├── test_client.py                # Client transport & RPC error handling tests
│   ├── test_simulation_success.py    # Successful transaction simulation tests
│   ├── test_revert_decoding.py       # Revert reason & panic code decoding tests
│   ├── test_state_diff.py            # Pre/post balance delta prediction tests
│   ├── test_gatekeeper.py            # Execution blocking on failed simulations tests
│   └── test_live_atlantic.py         # Live Atlantic Testnet RPC integration tests
├── web/
│   └── index.html                    # Interactive Tailwind CSS visualizer dashboard
└── scripts/
    ├── dry_run.py                    # Standalone CLI runner script
    └── server.py                     # Lightweight local visualizer server
```

---

## 4. Quick Start & CLI Usage

### Simulating Built-In Fixtures
```bash
# Valid native PHRS transfer (GO)
python scripts/dry_run.py --fixture valid_native_transfer

# Valid ERC-20 approve to Permit2 (GO)
python scripts/dry_run.py --fixture valid_erc20_approve

# Valid ERC-20 transfer (GO)
python scripts/dry_run.py --fixture valid_erc20_transfer

# Reverting transaction: Insufficient balance (NO-GO / BLOCKED)
python scripts/dry_run.py --fixture revert_insufficient_balance

# Reverting transaction: Arithmetic overflow Panic 0x11 (NO-GO / BLOCKED)
python scripts/dry_run.py --fixture revert_panic_overflow

# Reverting transaction: Custom contract error ZeroAddress() (NO-GO / BLOCKED)
python scripts/dry_run.py --fixture revert_custom_error
```

### Simulating Live Against Pharos Atlantic Testnet
```bash
python scripts/dry_run.py \
  --live \
  --from 0x1111111111111111111111111111111111111111 \
  --to 0xcA11bde05977b3631167028862bE2a173976CA11 \
  --data 0x
```

### JSON Mode for Agent Tooling
```bash
python scripts/dry_run.py --fixture valid_native_transfer --json
```

---

## 5. Interactive Web Visualizer

Launch the lightweight local web visualizer:
```bash
python scripts/server.py 8088
```
Open [http://localhost:8088](http://localhost:8088) in your browser. Reviewers can test all 6 preset scenarios with live GO / NO-GO badges, gas cost breakdowns, revert diagnostics, and before/after balance delta tables.

---

## 6. Zero-Cost ($0) Guarantee

- **Zero Gas Expended**: Non-mutating read-only EVM calls (`eth_call`, `eth_estimateGas`).
- **Zero Paid APIs**: Relies exclusively on the public Pharos Atlantic Testnet JSON-RPC (`https://atlantic.dplabs-internal.com`) and Hosted Pharos Chain MCP (`https://mcp.pharos.xyz/mcp`).
- **Zero Real-Money Risk**: Operates on testnet and calibrated sandboxes; no mainnet private keys are required.
