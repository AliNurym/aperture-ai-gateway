import { useCallback, useEffect, useRef, useState } from "react";
import axios from "axios";
import { useWallet } from "@solana/wallet-adapter-react";
import { WalletMultiButton } from "@solana/wallet-adapter-react-ui";
import Dashboard from "./Dashboard";
import Agents from "./Agents";
import Icon from "./components/Icon";
import { WORKLOADS } from "./utils/workloads";
import logo from "./assets/aperture-mark-v3.png";
import "./Console.css";
import "./Motion.css";

const API_URL = (
  import.meta.env.VITE_API_URL || "http://127.0.0.1:8000"
).replace(/\/$/, "");
const PAGES = [
  {
    id: "overview",
    label: "Overview",
    icon: "grid",
    title: "Workspace overview",
    subtitle: "A little less setup. A lot more possibility.",
  },
  {
    id: "studio",
    label: "Compute Studio",
    icon: "code",
    title: "Compute Studio",
    subtitle: "From a few lines of Python to an inspectable result.",
  },
  {
    id: "agents",
    label: "Agent passports",
    icon: "shield",
    title: "Know Your Agent",
    subtitle: "Owner-issued identity. Clear authority. Bounded spending.",
  },
  {
    id: "network",
    label: "Worker network",
    icon: "network",
    title: "Worker network",
    subtitle: "The available capacity behind your workloads.",
  },
  {
    id: "guide",
    label: "Getting started",
    icon: "book",
    title: "Getting started",
    subtitle: "Your workspace, explained.",
  },
];
function currentPage() {
  const id = window.location.hash.slice(1);
  return PAGES.some((page) => page.id === id) ? id : "overview";
}
function readHistory() {
  try {
    const stored = JSON.parse(sessionStorage.getItem("aperture-runs") || "[]");
    return Array.isArray(stored)
      ? stored
          .filter(
            (run) => typeof run.id === "string" && typeof run.name === "string",
          )
          .slice(0, 20)
      : [];
  } catch {
    return [];
  }
}

export default function App() {
  const { connected } = useWallet();
  const [page, setPage] = useState(currentPage);
  const [mode, setMode] = useState(() => {
    try { return sessionStorage.getItem("aperture-active:" + API_URL) ? "gateway" : "demo"; }
    catch { return "demo"; }
  });
  const [busy, setBusy] = useState(false);
  const [selection, setSelection] = useState(null);
  const [history, setHistory] = useState(readHistory);
  const [telemetry, setTelemetry] = useState({
    state: "checking",
    nodes: [],
    stats: null,
    health: null,
    updated: null,
  });
  const [refreshing, setRefreshing] = useState(false);
  const refreshController = useRef(null);
  const activePage = PAGES.find((item) => item.id === page);

  useEffect(() => {
    const onHash = () => setPage(currentPage());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);
  const navigate = (id) => {
    window.location.hash = id;
    setPage(id);
    window.scrollTo({ top: 0, behavior: "instant" });
  };
  const refresh = useCallback(async () => {
    refreshController.current?.abort();
    const controller = new AbortController();
    refreshController.current = controller;
    setRefreshing(true);
    try {
      const config = { timeout: 8000, signal: controller.signal };
      const [health, nodes, stats] = await Promise.all([
        axios.get(API_URL + "/health", config),
        axios.get(API_URL + "/active_nodes", config),
        axios.get(API_URL + "/stats", config),
      ]);
      if (!controller.signal.aborted)
        setTelemetry({
          state: "online",
          health: health.data,
          nodes: Array.isArray(nodes.data) ? nodes.data : [],
          stats: stats.data,
          updated: new Date(),
        });
    } catch {
      if (!controller.signal.aborted)
        setTelemetry((previous) => ({ ...previous, state: "offline" }));
    } finally {
      if (!controller.signal.aborted) setRefreshing(false);
    }
  }, []);
  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, 15000);
    return () => {
      clearInterval(timer);
      refreshController.current?.abort();
    };
  }, [refresh]);

  const recordRun = useCallback((run) => {
    setHistory((previous) => {
      const next = [
        run,
        ...previous.filter((item) => item.id !== run.id),
      ].slice(0, 20);
      // History stores only metadata. Active task recovery uses separate tab storage.
      try {
        sessionStorage.setItem("aperture-runs", JSON.stringify(next));
      } catch {
        /* Storage can be unavailable. */
      }
      return next;
    });
  }, []);
  const openSample = (sample) => {
    if (!busy) setSelection({ ...sample, requestId: crypto.randomUUID() });
    navigate("studio");
  };
  const online = telemetry.state === "online";
  const stateLabel = online
    ? telemetry.health?.status === "ready"
      ? "Gateway connected"
      : "Gateway needs setup"
    : telemetry.state === "checking"
      ? "Checking gateway"
      : "Gateway offline";

  return (
    <div className="console-app">
      <a
        href="#main-content"
        className="console-skip"
        onClick={(event) => {
          event.preventDefault();
          document.getElementById("main-content")?.focus();
        }}
      >
        Skip to content
      </a>
      <aside className="console-sidebar">
        <button
          className="console-brand"
          onClick={() => navigate("overview")}
          aria-label="Aperture home"
        >
          <img src={logo} alt="" width="44" height="44" />
          <span>
            Aperture<span>COMPUTE WORKSPACE</span>
          </span>
        </button>
        <button className="console-new" onClick={() => navigate("studio")}>
          <Icon name="code" />
          New workload
        </button>
        <div className="console-nav-label">WORKSPACE</div>
        <nav aria-label="Main navigation">
          {PAGES.map((item) => (
            <button
              key={item.id}
              className={
                "console-nav-item " + (page === item.id ? "selected" : "")
              }
              aria-current={page === item.id ? "page" : undefined}
              onClick={() => navigate(item.id)}
            >
              <Icon name={item.icon} />
              <span>{item.label}</span>
              {item.id === "studio" && busy && (
                <i className="console-running-dot" />
              )}
            </button>
          ))}
        </nav>
        <div className="console-sidebar-bottom">
          <div className="console-devnet">
            <span className="console-dot" />
            Solana Devnet<span>DEVELOPMENT</span>
          </div>
          <p>
            A space to build, test
            <br />
            and understand your compute.
          </p>
          <span className="console-version">Aperture workspace · v0.2</span>
        </div>
      </aside>
      <div className="console-body">
        <header className="console-topbar">
          <div className="console-breadcrumb">
            Workspace <span>/</span> <strong>{activePage.label}</strong>
          </div>
          <div className="console-top-actions">
            <span className="console-env-chip">Devnet</span>
            <WalletMultiButton />
          </div>
        </header>
        <main id="main-content" tabIndex={-1} className="console-main">
          <div className="console-page-heading">
            <div>
              <h1>{activePage.title}</h1>
              <p>{activePage.subtitle}</p>
            </div>
            <button
              className="console-status"
              onClick={refresh}
              disabled={refreshing}
              title={"Refresh gateway: " + API_URL}
            >
              <span className={"console-dot " + (online ? "" : "muted")} />
              {stateLabel}
              <Icon name="refresh" size={15} />
            </button>
          </div>

          {page === "overview" && (
            <>
              <section className="console-hero">
                <div className="console-hero-copy">
                  <span className="console-eyebrow">
                    <Icon name="spark" size={16} />
                    IDEAS IN. POSSIBILITIES OUT.
                  </span>
                  <h2>
                    Your next idea.
                    <br />
                    <span>Ready to compute.</span>
                  </h2>
                  <p>
                    Write a workload, explore its cost, and follow every step.
                    Your next experiment starts right here.
                  </p>
                  <div className="console-hero-actions">
                    <button
                      className="console-button primary"
                      onClick={() => openSample(WORKLOADS[0])}
                    >
                      Open Compute Studio
                      <Icon name="arrow" size={18} />
                    </button>
                    <button
                      className="console-text-button"
                      onClick={() => navigate("guide")}
                    >
                      Take a quick tour
                      <Icon name="arrow" size={17} />
                    </button>
                  </div>
                  <div className="console-hero-note">
                    <Icon name="check" size={15} />
                    Browser demo available · no wallet needed
                  </div>
                </div>
                <div className="console-orbit" aria-hidden="true">
                  <div className="console-orbit-ring one" />
                  <div className="console-orbit-ring two" />
                  <div className="console-orbit-core">
                    <img src={logo} alt="" width="92" height="92" />
                  </div>
                  <div className="console-orbit-tile code">
                    <Icon name="code" size={28} />
                    <span>your idea.py</span>
                  </div>
                  <div className="console-orbit-tile result">
                    <span className="console-result-icon">
                      <Icon name="check" size={18} />
                    </span>
                    <span>
                      Make it happen<small>One workload at a time</small>
                    </span>
                  </div>
                  <div className="console-orbit-star">✳</div>
                  <div className="console-orbit-dot" />
                </div>
              </section>
              <section
                className="console-metrics"
                aria-label="Gateway telemetry"
              >
                {[
                  [
                    "network",
                    "Available workers",
                    online ? telemetry.nodes.length : "—",
                    online
                      ? "Reporting within the last 45 seconds"
                      : "Connect your gateway to see capacity",
                  ],
                  [
                    "chip",
                    "Execution capability",
                    online
                      ? "Python CPU"
                      : "—",
                    "Reported by registered workers",
                  ],
                  [
                    "check",
                    "Completed workloads",
                    online ? (telemetry.stats?.tasks_completed ?? 0) : "—",
                    "Recorded by the gateway",
                  ],
                ].map(([icon, label, value, caption]) => (
                  <div className="console-metric" key={label}>
                    <div className="console-metric-label">
                      <span>{label}</span>
                      <Icon name={icon} />
                    </div>
                    <strong>{value}</strong>
                    <p>{caption}</p>
                  </div>
                ))}
              </section>
              <div className="console-home-grid">
                <section className="console-panel">
                  <div className="console-section-heading">
                    <div>
                      <h2>Start with a little inspiration</h2>
                      <p>Pick a sample and make it yours.</p>
                    </div>
                    <span className="console-small-label">PYTHON</span>
                  </div>
                  <div className="console-samples">
                    {WORKLOADS.map((sample, index) => (
                      <button
                        className="console-sample"
                        key={sample.id}
                        onClick={() => openSample(sample)}
                      >
                        <span className={"console-sample-icon tone-" + index}>
                          <Icon name={sample.icon} size={23} />
                        </span>
                        <span>
                          <strong>{sample.name}</strong>
                          <small>{sample.description}</small>
                        </span>
                        <Icon name="arrow" size={18} />
                      </button>
                    ))}
                  </div>
                </section>
                <section className="console-panel console-session">
                  <div className="console-section-heading">
                    <div>
                      <h2>Your recent activity</h2>
                      <p>Saved in this browser tab.</p>
                    </div>
                    <Icon name="clock" />
                  </div>
                  {history.length ? (
                    <div className="console-activity">
                      {history.slice(0, 4).map((run) => (
                        <div className="console-activity-row" key={run.id}>
                          <span className="console-activity-icon">
                            <Icon
                              name={
                                run.status === "completed" ? "check" : "code"
                              }
                              size={16}
                            />
                          </span>
                          <div>
                            <strong>{run.name}</strong>
                            <small>
                              {run.mode === "demo" ? "Browser demo" : "Gateway"}{" "}
                              ·{" "}
                              {new Date(run.timestamp).toLocaleTimeString([], {
                                hour: "2-digit",
                                minute: "2-digit",
                              })}
                            </small>
                          </div>
                          <span
                            className={
                              "console-tag " +
                              (["failed", "blocked"].includes(run.status)
                                ? "error"
                                : "")
                            }
                          >
                            {run.status}
                          </span>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="console-empty">
                      <span className="console-empty-icon">
                        <Icon name="clock" size={28} />
                      </span>
                      <h3>A fresh start.</h3>
                      <p>
                        Your runs will appear here.
                        <br />
                        Try a sample to get things moving.
                      </p>
                      <button
                        className="console-text-button"
                        onClick={() => openSample(WORKLOADS[0])}
                      >
                        Run your first demo
                        <Icon name="arrow" size={16} />
                      </button>
                    </div>
                  )}
                </section>
              </div>
              <div className="console-tip">
                <span className="console-tip-icon">
                  <Icon name="book" size={21} />
                </span>
                <div>
                  <strong>Small steps. Clear outcomes.</strong>
                  <p>
                    Browser demos explore the workflow. Connect your wallet and
                    gateway when you're ready to submit a Devnet workload.
                  </p>
                </div>
                <button
                  className="console-text-button"
                  onClick={() => navigate("guide")}
                >
                  How it works
                  <Icon name="arrow" size={17} />
                </button>
              </div>
            </>
          )}

          <section hidden={page !== "studio"} aria-label="Compute workspace">
            <div className="console-mode-bar">
              <div
                className="console-segmented"
                role="group"
                aria-label="Execution mode"
              >
                <button
                  aria-pressed={mode === "demo"}
                  disabled={busy}
                  onClick={() => setMode("demo")}
                >
                  Browser demo
                </button>
                <button
                  aria-pressed={mode === "gateway"}
                  disabled={busy}
                  onClick={() => setMode("gateway")}
                >
                  Devnet gateway
                </button>
              </div>
              <p>
                {mode === "demo"
                  ? "An interactive estimate. Python is not executed and no payments are made."
                  : connected
                    ? telemetry.health?.demo_mode
                      ? "Connected gateway executes Python with off-chain development settlement. No SOL payment."
                      : "Review price and limits, then sign. Requires a configured gateway and Devnet channel."
                    : "Connect a wallet to authorize a Devnet workload."}
              </p>
            </div>
            <Dashboard
              isDemoMode={mode === "demo"}
              selection={selection}
              onBusyChange={setBusy}
              onRecord={recordRun}
            />
          </section>

          {page === "agents" && <Agents />}

          {page === "network" && (
            <>
              <div className="console-network-banner">
                <span className="console-sample-icon tone-0">
                  <Icon name="network" size={28} />
                </span>
                <div>
                  <h2>
                    {online
                      ? telemetry.nodes.length + " workers available"
                      : "Your network is waiting"}
                  </h2>
                  <p>
                    {online
                      ? "Workers appear here while their heartbeat is active."
                      : "Start the local gateway to see worker availability and hardware telemetry."}
                  </p>
                </div>
                <button
                  className="console-button secondary"
                  onClick={refresh}
                  disabled={refreshing}
                >
                  <Icon name="refresh" size={17} />
                  Refresh
                </button>
              </div>
              {online && telemetry.nodes.length > 0 ? (
                <div className="console-worker-grid">
                  {telemetry.nodes.map((node) => (
                    <article
                      className="console-panel console-worker"
                      key={node.node_id}
                    >
                      <div className="console-worker-title">
                        <Icon name="chip" size={26} />
                        <span className="console-tag">{node.status}</span>
                      </div>
                      <h3>{node.gpu_name}</h3>
                      <p className="console-monospace">{node.node_id}</p>
                      <dl>
                        <div>
                          <dt>Memory</dt>
                          <dd>
                            {node.vram_used ?? 0} / {node.vram_total ?? 0} GB
                          </dd>
                        </div>
                        <div>
                          <dt>Utilization</dt>
                          <dd>{node.gpu_util ?? "—"}%</dd>
                        </div>
                        <div>
                          <dt>Temperature</dt>
                          <dd>{node.gpu_temp ?? "—"} °C</dd>
                        </div>
                        <div>
                          <dt>Capacity</dt>
                          <dd>{node.tflops ?? 0} TFLOPS</dd>
                        </div>
                      </dl>
                    </article>
                  ))}
                </div>
              ) : (
                <section className="console-panel console-empty console-network-empty">
                  <span className="console-empty-icon">
                    <Icon name="chip" size={36} />
                  </span>
                  <h3>
                    {online
                      ? "No workers have checked in yet."
                      : "Gateway is not connected."}
                  </h3>
                  <p>
                    Run the gateway, configure your worker, and return here.
                    <br />
                    You can explore the Studio demo in the meantime.
                  </p>
                  <button
                    className="console-button primary"
                    onClick={() => navigate("guide")}
                  >
                    View setup guide
                    <Icon name="arrow" size={17} />
                  </button>
                </section>
              )}
              <p className="console-footnote">
                {telemetry.updated
                  ? "Last successful update: " +
                    telemetry.updated.toLocaleTimeString() +
                    ". "
                  : ""}
                Availability refreshes every 15 seconds. Hardware values are
                reported by workers.
              </p>
            </>
          )}

          {page === "guide" && (
            <div className="console-guide">
              <section className="console-panel">
                <span className="console-eyebrow">THE SHORT VERSION</span>
                <h2>One workspace. Two ways to explore.</h2>
                <div className="console-guide-options">
                  <div>
                    <span className="console-sample-icon tone-0">
                      <Icon name="spark" size={24} />
                    </span>
                    <h3>Try it in your browser</h3>
                    <p>
                      Open Studio, select a Python sample and run the demo. See
                      an illustrative policy check, cost estimate and a
                      downloadable result. No server, wallet or installation
                      required.
                    </p>
                    <button
                      className="console-button primary"
                      onClick={() => {
                        if (!busy) setMode("demo");
                        openSample(WORKLOADS[0]);
                      }}
                    >
                      Try a demo
                      <Icon name="arrow" size={17} />
                    </button>
                  </div>
                  <div>
                    <span className="console-sample-icon tone-1">
                      <Icon name="wallet" size={24} />
                    </span>
                    <h3>Connect your development stack</h3>
                    <p>
                      Start the gateway and an authenticated worker. Connect a
                      Solana wallet, choose Devnet gateway in Studio and sign
                      the workload. A configured payment channel and deployed
                      program are required.
                    </p>
                    <a
                      className="console-text-button"
                      href={API_URL + "/docs"}
                      target="_blank"
                      rel="noreferrer"
                    >
                      Open local API docs
                      <Icon name="external" size={16} />
                    </a>
                  </div>
                </div>
              </section>
              <section className="console-panel console-setup">
                <h2>Run the project locally</h2>
                <p>
                  From the project folder, use the Windows launchers or the
                  commands below.
                </p>
                <div className="console-command">
                  <span>01 · FRONTEND</span>
                  <code>
                    cd frontend
                    <br />
                    npm ci --legacy-peer-deps
                    <br />
                    npm run dev -- --port 3000
                  </code>
                </div>
                <div className="console-command">
                  <span>02 · GATEWAY</span>
                  <code>start_backend.bat</code>
                  <p>
                    Configure backend/.env using .env.example. The worker and
                    gateway must share the same APERTURE_WORKER_TOKEN.
                  </p>
                </div>
                <div className="console-command">
                  <span>03 · WORKER</span>
                  <code>start_worker.bat</code>
                  <p>
                    Build the task image first with docker build -f backend/Dockerfile.sandbox -t aperture-task:local backend.
                    Workers use a separate Docker sandbox for each job, with no network and a fixed resource budget.
                  </p>
                </div>
              </section>
              <section className="console-panel console-guide-lifecycle">
                <h2>What happens to a workload?</h2>
                {[
                  [
                    "Sign",
                    "Review the quoted rate, maximum spend and runtime. Your wallet authorizes that exact source and quote.",
                  ],
                  [
                    "Review",
                    "The gateway checks Python source against its allowed policy and estimates a rate.",
                  ],
                  [
                    "Run",
                    "An authenticated worker claims the task and streams its output.",
                  ],
                  [
                    "Inspect",
                    "View the result and its actual settlement state. Demo, off-chain and Devnet results are labelled separately.",
                  ],
                ].map(([title, detail], index) => (
                  <div className="console-guide-step" key={title}>
                    <span>{index + 1}</span>
                    <div>
                      <h3>{title}</h3>
                      <p>{detail}</p>
                    </div>
                  </div>
                ))}
              </section>
            </div>
          )}
          <footer className="console-footer">
            <span>
              <img src={logo} alt="" width="18" height="18" />
              Built for curious minds.
            </span>
            <span>Development workspace · Solana Devnet</span>
          </footer>
        </main>
      </div>
    </div>
  );
}
