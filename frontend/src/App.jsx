import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import axios from "axios";
import { useWallet } from "@solana/wallet-adapter-react";
import { WalletMultiButton, useWalletModal } from "@solana/wallet-adapter-react-ui";
import Dashboard from "./Dashboard";
import Agents from "./Agents";
import Workflows from "./Workflows";
import Storage from "./Storage";
import Icon from "./components/Icon";
import CommandBlock from "./components/CommandBlock";
import { WORKLOADS } from "./utils/workloads";
import { installNavigationIndicator, installPressFeedback, syncNavigationIndicator } from "./utils/motion";
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
    shortLabel: "Home",
    icon: "grid",
    title: "Workspace overview",
    subtitle: "Your workloads, available capacity and recent results.",
  },
  {
    id: "studio",
    label: "Compute Studio",
    shortLabel: "Studio",
    icon: "code",
    title: "Compute Studio",
    subtitle: "Prepare your source, review the limits, inspect the result.",
  },
  {
    id: "workflows",
    label: "Agent workflows",
    shortLabel: "Flows",
    icon: "network",
    title: "Agent workflows",
    subtitle: "Prepare data, combine batches and retain the results of every step.",
  },
  {
    id: "storage",
    label: "Files & results",
    shortLabel: "Files",
    icon: "download",
    title: "Files & results",
    subtitle: "Inspect your retained data and make room for the next workload.",
  },
  {
    id: "agents",
    label: "Agent passports",
    shortLabel: "Agents",
    icon: "shield",
    title: "Agent passports",
    subtitle: "Set permissions and spending limits for each agent.",
  },
  {
    id: "network",
    label: "Worker network",
    shortLabel: "Workers",
    icon: "network",
    title: "Worker network",
    subtitle: "The available capacity behind your workloads.",
  },
  {
    id: "guide",
    label: "Getting started",
    shortLabel: "Guide",
    icon: "book",
    title: "Getting started",
    subtitle: "Connect execution and prepare your first workload.",
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
            (run) => run.mode === "gateway" && typeof run.id === "string" && typeof run.name === "string",
          )
          .slice(0, 20)
      : [];
  } catch {
    return [];
  }
}

export default function App() {
  const { connected, wallet } = useWallet();
  const { setVisible: chooseWallet } = useWalletModal();
  const [page, setPage] = useState(currentPage);
  const [studioBusy, setStudioBusy] = useState(false);
  const [workflowBusy, setWorkflowBusy] = useState(false);
  const busy = studioBusy || workflowBusy;
  const [selection, setSelection] = useState(null);
  const [releasedObject, setReleasedObject] = useState(null);
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
  const appRef = useRef(null);
  const navRef = useRef(null);
  const previousPage = useRef(page);
  const focusContent = useRef(false);
  const activePage = PAGES.find((item) => item.id === page);

  useEffect(() => installPressFeedback(appRef.current), []);
  useEffect(() => {
    const onHash = () => {
      const nextPage = currentPage();
      if (nextPage !== previousPage.current)
        focusContent.current = !navRef.current?.contains(document.activeElement);
      setPage(nextPage);
    };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);
  useLayoutEffect(() => {
    syncNavigationIndicator(navRef.current);
    if (previousPage.current !== page && focusContent.current)
      document.getElementById('main-content')?.focus({ preventScroll: true });
    previousPage.current = page;
    focusContent.current = false;
  }, [page]);
  useLayoutEffect(() => installNavigationIndicator(navRef.current), []);
  const navigate = (id) => {
    if (id !== page)
      focusContent.current = !navRef.current?.contains(document.activeElement);
    window.location.assign("#" + id);
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
  const gatewayReady = online && telemetry.health?.status === "ready";
  const activeWorkerCount = online ? telemetry.nodes.length : 0;
  const stateLabel = gatewayReady
    ? "Gateway connected"
    : online
      ? telemetry.health?.status === "workers_unavailable"
        ? "Waiting for a worker"
        : "Gateway needs setup"
      : telemetry.state === "checking"
        ? "Checking gateway"
        : "Gateway offline";

  return (
    <div className="console-app" ref={appRef}>
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
        <div className="console-nav-label">WORKSPACE</div>
        <nav
          aria-label="Main navigation"
          ref={navRef}
        >
          <span className="console-nav-indicator" aria-hidden="true" />
          {PAGES.map((item) => (
            <button
              key={item.id}
              className={
                "console-nav-item " + (page === item.id ? "selected" : "")
              }
              aria-current={page === item.id ? "page" : undefined}
              aria-label={item.label}
              title={item.label}
              onClick={() => navigate(item.id)}
            >
              <Icon name={item.icon} />
              <span className="console-nav-full">{item.label}</span>
              <span className="console-nav-short" aria-hidden="true">{item.shortLabel}</span>
              {(item.id === "studio" && studioBusy || item.id === "workflows" && workflowBusy) && (
                <i className="console-running-dot" />
              )}
            </button>
          ))}
        </nav>
        <div className="console-sidebar-bottom">
          <div className="console-devnet">
            <span className={"console-dot " + (gatewayReady ? "ready" : "muted")} />
            {telemetry.health?.environment === 'production' ? 'Production workspace' : 'Development workspace'}
          </div>
          <span className="console-version">Python CPU · Aperture</span>
        </div>
      </aside>
      <div className="console-body">
        <header className="console-topbar">
          <div className="console-breadcrumb">
            <img className="console-mobile-mark" src={logo} alt="" width="26" height="26" />
            <span className="console-breadcrumb-root">Workspace</span><span aria-hidden="true">/</span><strong key={page}>{activePage.label}</strong>
          </div>
          <div className="console-top-actions">
            <span className="console-env-chip">{online ? telemetry.health?.demo_mode ? "Off-chain" : "Devnet" : "Gateway offline"}</span>
            {wallet && !connected && <button className="console-icon-button" aria-label="Choose wallet" title="Choose wallet" onClick={() => chooseWallet(true)}><Icon name="wallet" size={18} /></button>}
            <WalletMultiButton />
          </div>
        </header>
        <main id="main-content" tabIndex={-1} className="console-main">
          <div className="console-page-heading">
            <div className="console-heading-copy" key={page}>
              <h1>{activePage.title}</h1>
              <p>{activePage.subtitle}</p>
            </div>
            <button
              className="console-status"
              onClick={refresh}
              disabled={refreshing}
              aria-busy={refreshing}
              title={"Refresh gateway: " + API_URL}
            >
              <span
                className={
                  "console-dot " +
                  (gatewayReady ? "ready" : online ? "warning" : "muted")
                }
              />
              {stateLabel}
              <Icon name="refresh" spinning={refreshing} size={15} />
            </button>
          </div>

          {wallet?.adapter.name === 'Temporary key' && <div className="console-tip"><Icon name="shield" size={19} /><p>Temporary development key. Its private key exists only in this tab and is lost on reload or disconnect. Use an external wallet for persistent assets.</p></div>}
          {page === "overview" && (
            <>
              <section className="console-hero">
                <div className="console-hero-copy">
                  <span className="console-eyebrow">
                    <Icon name="spark" size={16} />
                    COMPUTE FOR AI AGENTS
                  </span>
                  <h2>
                    Give your agent
                    <br />
                    <span>room to compute.</span>
                  </h2>
                  <p>
                    Process your data, chain useful jobs and collect reusable files.
                    Keep every step inside an approved spending limit.
                  </p>
                  <div className="console-hero-actions">
                    <button
                      className="console-button primary"
                      onClick={() => navigate("studio")}
                    >
                      Open Compute Studio
                      <Icon name="arrow" size={18} />
                    </button>
                    <button
                      className="console-text-button"
                      onClick={() => navigate("workflows")}
                    >
                      Build an agent workflow
                      <Icon name="arrow" size={17} />
                    </button>
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
                    <span>data → compute</span>
                  </div>
                  <div className="console-orbit-tile result">
                    <span className="console-result-icon">
                      <Icon name="check" size={18} />
                    </span>
                    <span>
                      Useful results<small>JSON · CSV · signed files</small>
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
                    "Workers online",
                    online ? telemetry.nodes.length : "—",
                    online
                      ? "Available capacity"
                      : "Gateway unavailable",
                  ],
                  [
                    "check",
                    "Completed workloads",
                    online ? (telemetry.stats?.tasks_completed ?? "—") : "—",
                    "Gateway total",
                  ],
                  [
                    "shield",
                    "Data isolation",
                    "0 context leaks",
                    "256 MiB quota · signed files",
                  ],
                  [
                    "wallet",
                    "Settlement",
                    online ? telemetry.health?.demo_mode ? "Off-chain" : "Devnet" : "—",
                    online ? telemetry.health?.demo_mode ? "Local verified receipt" : telemetry.health?.protocol_config_initialized ? "Protocol configured" : "Protocol setup required" : "Gateway unavailable",
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

              <section className="console-panel console-pipeline" aria-label="Aperture computation pipeline">
                <div className="console-section-heading">
                  <div>
                    <span className="console-eyebrow">
                      <Icon name="spark" size={14} />
                      ZERO-LEAK PIPELINE
                    </span>
                    <h2>How Aperture Protects Your Agent's Context</h2>
                    <p>Dataset bytes stream directly into verified sandbox containers. Only cryptographic hashes and structured results return to the agent.</p>
                  </div>
                </div>
                <div className="pipeline-steps">
                  <div className="pipeline-step">
                    <div className="pipeline-step-badge">1</div>
                    <div className="pipeline-step-content">
                      <strong>Private Inputs</strong>
                      <p>CSV / JSON files stored with SHA-256 integrity</p>
                      <span className="pipeline-pill">Up to 64 MiB</span>
                    </div>
                  </div>
                  <div className="pipeline-connector"><Icon name="arrow" size={16} /></div>
                  <div className="pipeline-step">
                    <div className="pipeline-step-badge">2</div>
                    <div className="pipeline-step-content">
                      <strong>Signed Quote</strong>
                      <p>Deterministic tariff & bounded runtime authorization</p>
                      <span className="pipeline-pill">Ed25519 Sign</span>
                    </div>
                  </div>
                  <div className="pipeline-connector"><Icon name="arrow" size={16} /></div>
                  <div className="pipeline-step active">
                    <div className="pipeline-step-badge">3</div>
                    <div className="pipeline-step-content">
                      <strong>Worker Sandbox</strong>
                      <p>Isolated Python execution without network access</p>
                      <span className="pipeline-pill">Docker / cgroups</span>
                    </div>
                  </div>
                  <div className="pipeline-connector"><Icon name="arrow" size={16} /></div>
                  <div className="pipeline-step">
                    <div className="pipeline-step-badge">4</div>
                    <div className="pipeline-step-content">
                      <strong>Verified Artifacts</strong>
                      <p>Named result files & on-chain / off-chain receipt</p>
                      <span className="pipeline-pill">report.json · CSV</span>
                    </div>
                  </div>
                </div>
              </section>
              <div className="console-home-grid">
                <section className="console-panel">
                  <div className="console-section-heading">
                    <div>
                      <h2>Sample workloads</h2>
                      <p>Open a starting point in Studio.</p>
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
                      <h2>Recent runs</h2>
                      <p>Results from this browser tab.</p>
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
                              Gateway{" "}
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
                              (["failed", "blocked", "unverified"].includes(run.status)
                                ? "error"
                                : run.status === "cancelled"
                                  ? "neutral"
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
                      <h3>No runs yet</h3>
                      <p>Your first result will appear here after you run a workload.</p>
                    </div>
                  )}
                </section>
              </div>
              {!gatewayReady && <div className="console-setup-nudge">
                <Icon name="chip" size={18} />
                <p>{online && activeWorkerCount === 0 ? "Connect a worker when you are ready to execute." : "Connect your execution stack to run workloads."} You can prepare source in Studio now.</p>
                <button className="console-text-button" onClick={() => navigate("guide")}>Setup guide<Icon name="arrow" size={16} /></button>
              </div>}
            </>
          )}

          <section
            className="console-studio"
            hidden={page !== "studio"}
            aria-label="Compute workspace"
          >
            <div className="console-mode-bar">
              <span className="console-execution-label"><Icon name="chip" size={17} />Python CPU</span>
              <p>
                {online
                  ? activeWorkerCount === 0
                    ? "No worker connected. You can prepare source and review a quote."
                    : telemetry.health?.demo_mode
                    ? "Signed worker results. No on-chain payment."
                    : connected
                      ? "Review price and limits, then sign the exact workload."
                      : "Connect your wallet to authorize a workload and Devnet payment."
                  : "Gateway offline. You can still prepare your source."}
              </p>
            </div>
            <Dashboard
              gatewayHealth={telemetry.health}
              gatewayOnline={online}
              workerCount={activeWorkerCount}
              reviewedSourcesOnly={online && telemetry.nodes.length > 0 && telemetry.nodes.every(node => node.source_policy === 'exact_hash_allowlist')}
              selection={selection}
              releasedObject={releasedObject}
              externalBusy={workflowBusy}
              onBusyChange={setStudioBusy}
              onRecord={recordRun}
            />
          </section>

          <section className="console-workflows" hidden={page !== "workflows"} aria-label="Agent workflows"><Workflows apiUrl={API_URL} gatewayHealth={telemetry.health} gatewayOnline={online} externalBusy={studioBusy} onBusyChange={setWorkflowBusy} onRecord={recordRun} releasedObject={releasedObject} onOpenStudio={openSample} /></section>

          <section className="console-storage" hidden={page !== "storage"} aria-label="Private file storage"><Storage apiUrl={API_URL} gatewayHealth={telemetry.health} gatewayOnline={online} onOpenStudio={() => navigate('studio')} onObjectReleased={setReleasedObject} /></section>


          {page === "agents" && <Agents />}

          {page === "network" && (
            <>
              {online && activeWorkerCount > 0 && <div className="console-network-banner">
                <span className="console-sample-icon tone-0">
                  <Icon name="network" size={28} />
                </span>
                <div>
                  <h2>
                    {activeWorkerCount} {activeWorkerCount === 1 ? "worker" : "workers"} online
                  </h2>
                  <p>
                    Authenticated capacity for your Python workloads.
                  </p>
                </div>
                <button
                  className="console-button secondary"
                  onClick={refresh}
                  disabled={refreshing}
                  aria-busy={refreshing}
                >
                  <Icon name="refresh" spinning={refreshing} size={17} />
                  Refresh
                </button>
              </div>}
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
                      <h3>{node.gpu_name || "Python CPU worker"}</h3>
                      <p className="console-monospace">{node.node_id}</p>
                      <details className="console-disclosure console-worker-details"><summary>Worker details</summary>
                      <dl>
                        <div>
                          <dt>Signing identity</dt>
                          <dd title={node.worker_pubkey}>{node.worker_pubkey ? `${node.worker_pubkey.slice(0, 6)}…${node.worker_pubkey.slice(-6)}` : "Not reported"}</dd>
                        </div>
                        <div>
                          <dt>Last heartbeat</dt>
                          <dd>{Number.isFinite(node.last_seen) ? new Date(node.last_seen * 1000).toLocaleTimeString() : "Not reported"}</dd>
                        </div>
                        <div>
                          <dt>Execution</dt>
                          <dd>{node.execution_mode === "docker" ? "Docker container" : node.execution_mode === "trusted_local" ? "Trusted local process" : "Not reported"}</dd>
                        </div>
                        <div>
                          <dt>Source approval</dt>
                          <dd>{node.source_policy === "exact_hash_allowlist" ? `${node.approved_source_count} reviewed files` : node.source_policy === "gateway_ast" ? "Gateway source policy" : node.source_policy === "operator_trusted" ? "Operator trusted code" : "Not reported"}</dd>
                        </div>
                      </dl>
                      </details>
                    </article>
                  ))}
                </div>
              ) : (
                <section className="console-panel console-empty console-network-empty">
                  <span className="console-empty-icon">
                    <Icon name="chip" size={36} />
                  </span>
                  <h2>
                    {online
                      ? "Connect your first worker"
                      : "Connect your execution stack"}
                  </h2>
                  <p>
                    {online ? "Your gateway is online. Start an authenticated worker to make execution available." : "Start the gateway and an authenticated worker to make execution available."}
                  </p>
                  <button
                    className="console-button primary"
                    onClick={() => navigate("guide")}
                  >
                    Set up execution
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
                Availability refreshes every 15 seconds. Worker identities and
                states come from authenticated heartbeats.
              </p>
            </>
          )}

          {page === "guide" && (
            <div className="console-guide">
              <section className="console-panel console-guide-intro">
                <div>
                  <span className="console-eyebrow">YOUR FIRST USEFUL RESULT</span>
                  <h2>Turn data into a report.</h2>
                  <p>Add CSV batches, approve a bounded chain and open verified category totals. Start with your own data or two small example batches.</p>
                  <button className="console-button primary" onClick={() => navigate("workflows")}>Build an agent workflow<Icon name="arrow" size={17} /></button>
                </div>
                <ol className="console-guide-path">
                  {[
                    ["Add data", "Upload CSV batches with category and amount columns."],
                    ["Review & sign", "Approve each step's source, input hashes and spending limit."],
                    ["Compute", "Worker results feed the next step in your saved chain."],
                    ["Use the result", "Open a verified JSON report or CSV table and download its files."],
                  ].map(([title, detail], index) => <li className="console-guide-step" key={title}><span>{index + 1}</span><div><h3>{title}</h3><p>{detail}</p></div></li>)}
                </ol>
              </section>
              <section className="console-panel console-setup">
                <div className="console-section-heading"><div><h2>Start your local workspace</h2><p>One Windows launcher starts the console, gateway and reviewed CPU worker.</p></div><Icon name="network" /></div>
                <CommandBlock label="Complete local preview" command={'.\\start_preview.bat'}><p>Open 127.0.0.1:3000, choose Temporary key and try the example batches. Keep the launcher open; Ctrl+C stops its services and preserves saved files.</p></CommandBlock>
                <p className="console-footnote">Real local computation in off-chain mode, without a Solana payment. This preview executes the reviewed templates on the host; container isolation requires the Docker worker below.</p>
                <details className="console-disclosure console-setup-details"><summary>Configure Docker or Devnet execution</summary>
                  <div className="console-setup-grid">
                    <CommandBlock label="01 · Frontend" command="start_frontend.bat" />
                    <CommandBlock label="02 · Gateway" command="start_backend.bat" />
                    <CommandBlock label="03 · Docker worker" command="start_worker.bat" />
                  </div>
                  <p>Configure <code>backend/.env</code> and <code>backend/.worker.env</code> from their example files. Set the same <code>APERTURE_WORKER_TOKEN</code> in both.</p>
                  <p>The worker launcher builds the per-task sandbox image if needed. Each job runs without network access and with a fixed resource budget.</p>
                  <p>Devnet settlement requires a deployed program, initialized protocol configuration and a funded payment channel. Off-chain mode returns signed worker output without an on-chain payment.</p>
                  <a className="console-text-button" href={API_URL + "/docs"} target="_blank" rel="noreferrer">Open local API docs<Icon name="external" size={16} /></a>
                </details>
              </section>
              <section className="console-panel console-guide-agent">
                <div>
                  <span className="console-eyebrow">OPTIONAL · MCP</span>
                  <h2>Connect an AI agent</h2>
                  <p>Let a compatible agent request quotes, start bounded Python workloads and collect receipts through the SDK.</p>
                  <button className="console-text-button" onClick={() => navigate("agents")}>Set up an agent passport<Icon name="arrow" size={16} /></button>
                </div>
                <div>
                  <CommandBlock label="Python SDK + MCP" command={'python -m pip install -e ".\\sdk[mcp]"'} />
                  <p className="console-footnote">See <code>docs/mcp-agent.md</code> for host setup. MCP execution stays disabled until its local operator enables it.</p>
                </div>
              </section>
            </div>
          )}
          <footer className="console-footer">
            <span>
              <img src={logo} alt="" width="18" height="18" />
              Built for curious minds.
            </span>
            <span>{online ? telemetry.health?.demo_mode ? "Off-chain execution" : "Solana Devnet" : "Local workspace"}</span>
          </footer>
        </main>
      </div>
    </div>
  );
}
