# 🛠️ Installation & Deployment Guide: Aperture AI
This guide provides a comprehensive walkthrough to deploy and verify the Aperture AI ecosystem. As a distributed high-performance DePIN grid, the architecture spans three decoupled layers:
1. **Solana Smart Contract Layer** (Anchor Framework on Solana Devnet)
2. **AI-Sentinel Oracle Gateway** (FastAPI, AST Static Complexity Visitor, Pyth Hermes Oracle)
3. **Physical Silicon Worker Daemon** (Python subprocess sandbox & real-time NVML telemetry)

---

## 1. Prerequisites

Ensure your host machine meets the following environment dependencies:

| Component | Minimum Version | Purpose |
| :--- | :--- | :--- |
| **Python** | 3.10+ (Recommended: 3.12) | AI-Sentinel Oracle, AST parser, Worker daemon |
| **Node.js** | 18+ (Recommended: 20+) | Vite 5 frontend bundler & React UI |
| **Rust & Cargo** | Latest stable | Solana Anchor smart contract compilation |
| **Solana CLI** | v1.18+ | Devnet deployment & keypair management |
| **Anchor CLI** | v0.29.0+ | Anchor framework build & test tools |
| **NVIDIA GPU** *(Optional)* | GTX 1650+ / RTX 3050+ | Physical silicon acceleration & live NVML telemetry |

---

## 2. Smart Contract Deployment (Solana Devnet)

The Anchor program source code resides in the [`programs/src/lib.rs`](programs/src/lib.rs) directory.

### Build the Program:
```bash
cd programs
anchor build
```

### Deploy to Solana Devnet:
```bash
anchor deploy --provider.cluster devnet
```

> **Note:** The verified contract is deployed on Solana Devnet at Program ID:  
> [`C2q9yxux7b7bxFF64pkZUV6g2Vcs2bQ1FS4GUQy512wv`](https://explorer.solana.com/address/C2q9yxux7b7bxFF64pkZUV6g2Vcs2bQ1FS4GUQy512wv?cluster=devnet)

---

## 3. Running the DePIN Grid

### 🚀 1-Click Master Launch (Recommended on Windows)
Simply double-click the master orchestrator in the project root:
```cmd
start_all.bat
```
This spawns 3 dedicated console windows:
* `start_backend.bat`: AI-Sentinel Oracle Gateway on port `8000`
* `start_worker.bat`: Hardware Worker daemon on physical silicon (`NODE-HOST-GPU-01`)
* `start_frontend.bat`: Vite Command Center on port `3000`

---

### 💻 Manual Multi-Terminal Execution

#### Terminal 1: AI-Sentinel Oracle Gateway
The FastAPI backend acts as the intelligent oracle, intercepting payloads, inspecting AST complexity, and emitting dynamic price signals.
```bash
cd backend
python -m venv venv

# Windows:
.\venv\Scripts\activate
# Linux/macOS:
# source venv/bin/activate

pip install -r requirements.txt
python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

#### Terminal 2: Physical GPU Compute Worker
The worker daemon detects physical NVIDIA GPUs via `pynvml`, connects to the Gateway FIFO queue, executes workloads inside an isolated sandbox, and streams sub-second stdout back to the network.
```bash
cd backend
# Activate venv as above
python -u worker.py --node-id NODE-HOST-GPU-01 --wallet 7wFo7q4EHfKrBNpL4XLXXWAi9TcE6BD27ZoQoBqtFcNQ
```

#### Terminal 3: Command Center Web UI
The React 19 + Vite 5 frontend interface for workload submission, real-time telemetry, and on-chain settlements.
```bash
cd frontend
npm install
npm run dev -- --port 3000
```
Open **http://localhost:3000** in your browser.

---

## 4. End-to-End Workflow Verification

1. **Submit Payload**: Choose a benchmark (e.g. *Matrix Multiplication* or *Deep Neural Network Forward Pass*) or enter custom Python code in the Studio.
2. **AI-Sentinel Pre-Audit**: The Gateway parses the Abstract Syntax Tree, computes loop nesting depth, checks imports against the security whitelist, and signs a complexity-weighted burn rate.
3. **Solana Channel Lock**: Escrows initial Lamport balance into the user's PDA channel (`[b"channel", user.key()]`).
4. **Hardware Execution**: The physical worker daemon picks up the task, executes it on the GPU, and streams incremental stdout lines every ~300ms.
5. **Autonomous Finality**: Upon completion, the exact execution duration is deducted in Lamports, the burn rate resets to 0, and a verifiable settlement receipt is minted on Solana Devnet.

---

## 5. Automated System Integration Tests

Run the full end-to-end integration test suite:
```bash
python backend/test_e2e.py
```
This tests:
* ✅ `/stats` hardware telemetry aggregation
* ✅ `/active_nodes` physical worker registration
* ✅ Linear algebra benchmark execution on silicon
* ✅ Sub-second stdout streaming
* ✅ Deep learning forward pass inference
* ✅ Zero-trust AST security sandboxing (blocking malicious probes with HTTP 403)

---

## 👨‍💻 Author

Built and engineered by **Nemezida** ([@nemezidam](https://t.me/nemezidam)).  
* **GitHub**: [AliNurym/aperture-ai-gateway](https://github.com/AliNurym/aperture-ai-gateway)
