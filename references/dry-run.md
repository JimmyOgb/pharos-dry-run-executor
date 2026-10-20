# Pharos Dry-Run Executor Reference

## Overview
The `pharos-dry-run-executor` skill simulates transactions on Pharos Atlantic Testnet (`Chain ID: 688689`) before submission, evaluating whether the transaction will succeed, estimating precise gas and fiat costs, predicting post-state balances and allowances, and enforcing a fail-closed execution gate.

## Capabilities

### 1. Zero-Broadcast Pre-Flight Simulation
- **Method**: Evaluates `eth_call` and `eth_estimateGas` over direct JSON-RPC or Pharos Chain MCP (`https://mcp.pharos.xyz/mcp`).
- **Broadcast Status**: Strictly non-mutating; zero `eth_sendRawTransaction` operations are performed during simulation.

### 2. EVM Revert & Panic Decoding
- **Error(string)** (`0x08c379a0`): Decodes standard revert messages (e.g. `"ERC20: transfer amount exceeds balance"`).
- **Panic(uint256)** (`0x4e487b71`): Decodes Solidity 0.8+ panic codes:
  - `0x01`: Assert failure
  - `0x11`: Arithmetic overflow or underflow
  - `0x12`: Divide by zero
  - `0x21`: Invalid enum value conversion
  - `0x22`: Access to out-of-bounds storage byte array
  - `0x31`: Pop on empty array
  - `0x32`: Array out of bounds
  - `0x41`: Out of memory
  - `0x51`: Zero-initialized variable of internal function type
- **Custom Contract Errors**: Extracts 4-byte selector and matches against canonical error signatures.

### 3. State & Balance Delta Prediction
- **Native PHRS**: Computes `sender_delta = -(value + gas_cost)` and `recipient_delta = +value`.
- **ERC-20 `transfer(to, amount)`**: Computes token balance change for sender and recipient.
- **ERC-20 `approve(spender, amount)`**: Computes updated allowance for the target spender.

### 4. Automated Execution Gatekeeper
- Returns a structured execution verdict:
  - `GO` / `SIMULATED_SUCCESS`: Simulation passed, gas estimated, safe to broadcast.
  - `NO-GO` / `BLOCKED`: Reverted or gas estimation failed; transaction execution is blocked.

## Command Reference

### Simulating a Pre-Configured Fixture
```bash
python scripts/dry_run.py --fixture valid_native_transfer
python scripts/dry_run.py --fixture revert_insufficient_balance
```

### Simulating a Custom Transaction (Offline / Sandbox)
```bash
python scripts/dry_run.py \
  --from 0x1111111111111111111111111111111111111111 \
  --to 0xcfC8330f4BCAB529c625D12781b1C19466A9Fc8B \
  --data 0xa9059cbb0000000000000000000000002222222222222222222222222222222222222222000000000000000000000000000000000000000000000000000000000ee6b280 \
  --value 0
```

### Live Atlantic Testnet Simulation
```bash
python scripts/dry_run.py \
  --live \
  --from 0x1111111111111111111111111111111111111111 \
  --to 0xcA11bde05977b3631167028862bE2a173976CA11 \
  --data 0x
```
