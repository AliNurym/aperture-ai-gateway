import { lazy, Suspense, useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import axios from "axios";
import { useWallet } from "@solana/wallet-adapter-react";
import { WalletMultiButton, useWalletModal } from "@solana/wallet-adapter-react-ui";
import Dashboard from "./Dashboard";
const Agents = lazy(() => import("./Agents"));
const Workflows = lazy(() => import("./Workflows"));
const Storage = lazy(() => import("./Storage"));
const Inference = lazy(() => import("./Inference"));
const ComputeMarket = lazy(() => import("./ComputeMarket"));
const ProviderWorkspace = lazy(() => import("./ProviderWorkspace"));
import Icon from "./components/Icon";
import CommandBlock from "./components/CommandBlock";
import LiveDemoShowcase from "./components/LiveDemoShowcase";
import ProofVerifierModal from "./components/ProofVerifierModal";
import CommandPalette from "./components/CommandPalette";
import { DEFAULT_STUDIO_WORKLOAD, WORKLOADS } from "./utils/workloads";
import { activeModelWorkerCount, buildSentinelPrompt, publicInferenceProviders } from "./utils/inference";
import { installNavigationIndicator, installPressFeedback, syncNavigationIndicator } from "./utils/motion";
import logo from "./assets/aperture-mark-v3.png";
import "./Console.css";
import "./Motion.css";
import "./Workspace.css";
import WorkspaceModes from "./components/WorkspaceModes";

const API_URL = (
  import.meta.env.VITE_API_URL || "http://127.0.0.1:8000"
).replace(/\/$/, "");
const PAGES = [
  {
    id: "overview",
    label: "Overview",
    shortLabel: "Home",
    icon: "grid",
    group: "dispatch",
    title: "AI inference & compute marketplace",
    subtitle: "Route model requests and compute through one owner-controlled gateway.",
  },
  {
    id: "studio",
    label: "Compute Studio",
    shortLabel: "Studio",
    icon: "code",
    group: "dispatch",
    title: "Compute Studio",
    subtitle: "Prepare, review and run a bounded workload.",
  },
  {
    id: "workflows",
    label: "Agent workflows",
    shortLabel: "Flows",
    icon: "network",
    group: "dispatch",
    title: "Agent workflows",
    subtitle: "Delegate data pipelines, enforce spending caps, and recover after failures.",
  },
  {
    id: "storage",
    label: "Files & results",
    shortLabel: "Files",
    icon: "download",
    group: "control",
    title: "Files & results",
    subtitle: "Inspect your retained data and make room for the next workload.",
  },
  {
    id: "agents",
    label: "Agent passports",
    shortLabel: "Agents",
    icon: "shield",
    group: "control",
    title: "Agent permissions",
    subtitle: "Set permissions and spending limits for each agent.",
  },
  {
    id: "network",
    label: "Worker network",
    shortLabel: "Network",
    icon: "network",
    group: "network",
    title: "Worker network",
    subtitle: "Browse active workers and the model offers they can serve.",
  },
  {
    id: "provider",
    label: "Provide compute",
    shortLabel: "Provider",
    icon: "chip",
    group: "network",
    title: "Provide compute",
    subtitle: "Manage your worker, finish active work, and track its earnings.",
  },
  {
    id: "guide",
    label: "Getting started",
    shortLabel: "Guide",
    icon: "book",
    group: "guide",
    title: "Getting started",
    subtitle: "Connect execution and prepare your first workload.",
  },
];
const NAV_GROUPS = [
  { id: "dispatch", label: "Workspace" },
  { id: "control", label: "Resources" },
  { id: "network", label: "Network" },
  { id: "guide", label: "" },
];
const SENTINEL_DRAFT_KEY = "aperture-sentinel-draft-v1";
function readSentinelDraft() {
  try {
    const draft = JSON.parse(sessionStorage.getItem(SENTINEL_DRAFT_KEY) || "null");
    return draft && typeof draft.id === "string" && typeof draft.source === "string"
      && typeof draft.prompt === "string" ? draft : null;
  } catch {
    return null;
  }
}
function clearSentinelDraft() {
  try { sessionStorage.removeItem(SENTINEL_DRAFT_KEY); } catch { /* Tab storage may be unavailable. */ }
}
function currentPage() {
  const id = window.location.hash.slice(1);
  if (id === "inference" || id === "sentinel") return "studio";
  return PAGES.some((page) => page.id === id) ? id : "studio";
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
  const [studioMode, setStudioMode] = useState(() => window.location.hash.slice(1) === "inference" ? "inference" : "python");
  const [inferenceVisited, setInferenceVisited] = useState(() => ["inference", "sentinel"].includes(window.location.hash.slice(1)));
  const [showReceiptGuide, setShowReceiptGuide] = useState(false);
  const [showCommandPalette, setShowCommandPalette] = useState(false);
  const [studioBusy, setStudioBusy] = useState(false);
  const [workflowBusy, setWorkflowBusy] = useState(false);
  const [inferenceBusy, setInferenceBusy] = useState(false);
  const [preferredProviderId, setPreferredProviderId] = useState("");
  const [workerTarget, setWorkerTarget] = useState(null);
  const [sentinelDraft, setSentinelDraft] = useState(readSentinelDraft);
  const [sentinelResult, setSentinelResult] = useState(null);
  const [sentinelLaunchError, setSentinelLaunchError] = useState("");
  const busy = studioBusy || workflowBusy || inferenceBusy;
  const [studioSource, setStudioSource] = useState(() => readSentinelDraft()?.source || DEFAULT_STUDIO_WORKLOAD.code);
  const [selection, setSelection] = useState(null);
  const [releasedObject, setReleasedObject] = useState(null);
  const [history, setHistory] = useState(readHistory);
  const [telemetry, setTelemetry] = useState({
    state: "checking",
    nodes: [],
    stats: null,
    health: null,
    providers: [],
    updated: null,
  });
  const [refreshing, setRefreshing] = useState(false);
  const [theme, setTheme] = useState(() => {
    try {
      return localStorage.getItem('aperture-theme-v2') || 'light';
    } catch {
      return 'light';
    }
  });

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
    document.documentElement.classList.toggle('dark-theme', theme === 'dark');
    try { localStorage.setItem('aperture-theme-v2', theme); } catch {}
  }, [theme]);

  const toggleTheme = () => setTheme((prev) => (prev === 'dark' ? 'light' : 'dark'));

  const [visitedPages, setVisitedPages] = useState(() => new Set([currentPage()]));
  useEffect(() => {
    setVisitedPages((prev) => {
      if (prev.has(page)) return prev;
      const next = new Set(prev);
      next.add(page);
      return next;
    });
  }, [page]);

  const refreshController = useRef(null);
  const appRef = useRef(null);
  const navRef = useRef(null);
  const previousPage = useRef(page);
  const focusContent = useRef(false);
  const activePage = PAGES.find((item) => item.id === page);

  const navigate = useCallback((target) => {
    const inferenceMode = target === "inference";
    const sentinelMode = target === "sentinel";
    const id = inferenceMode || sentinelMode ? "studio" : target;
    if (target === "studio" || inferenceMode) {
      setSentinelDraft(null);
      clearSentinelDraft();
    }
    if (inferenceMode) setInferenceVisited(true);
    if (id === "studio") setStudioMode(inferenceMode ? "inference" : "python");
    if (id !== page)
      focusContent.current = !navRef.current?.contains(document.activeElement);
    window.location.assign("#" + (sentinelMode ? "sentinel" : inferenceMode ? "inference" : id));
    setPage(id);
    window.scrollTo({ top: 0, behavior: "instant" });
  }, [page]);
  const openFunding = useCallback(() => {
    navigate("studio");
    requestAnimationFrame(() => {
      const panel = document.getElementById("studio-payment-channel");
      panel?.scrollIntoView({ block: "center", behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth' });
      panel?.focus({ preventScroll: true });
    });
  }, [navigate]);
  const openInferenceProvider = useCallback((providerId) => {
    setInferenceVisited(true);
    setSentinelDraft(null);
    setPreferredProviderId(providerId);
    navigate("inference");
  }, [navigate]);
  const openGeneralInference = useCallback(() => {
    setInferenceVisited(true);
    setSentinelDraft(null);
    clearSentinelDraft();
    setPreferredProviderId("");
    navigate("inference");
  }, [navigate]);
  const openSentinelReview = useCallback(({ source, prompt }) => {
    setInferenceVisited(true);
    setPreferredProviderId("");
    setSentinelResult(null);
    setSentinelLaunchError("");
    const draft = { id: crypto.randomUUID(), source, prompt };
    try { sessionStorage.setItem(SENTINEL_DRAFT_KEY, JSON.stringify(draft)); } catch { /* The review can continue in this tab. */ }
    setSentinelDraft(draft);
    navigate("sentinel");
  }, [navigate]);
  const openSentinelFromOverview = useCallback(() => {
    try {
      openSentinelReview({ source: studioSource, prompt: buildSentinelPrompt(studioSource) });
    } catch (error) {
      setSentinelLaunchError(error.message);
    }
  }, [openSentinelReview, studioSource]);
  const returnToStudio = useCallback(() => {
    setSentinelDraft(null);
    clearSentinelDraft();
    navigate("studio");
  }, [navigate]);
  const recordSentinelResult = useCallback((result) => setSentinelResult(result), []);

  useEffect(() => installPressFeedback(appRef.current), []);
  useEffect(() => {
    const handleKeyDown = (event) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setShowCommandPalette((prev) => !prev);
        return;
      }
      if (
        event.key === "/" &&
        !["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement?.tagName) &&
        !document.activeElement?.isContentEditable
      ) {
        event.preventDefault();
        setShowCommandPalette(true);
        return;
      }
      if (event.altKey && !event.ctrlKey && !event.metaKey) {
        const num = parseInt(event.key, 10);
        if (num >= 1 && num <= PAGES.length) {
          event.preventDefault();
          navigate(PAGES[num - 1].id);
          return;
        }
        if (event.key.toLowerCase() === "t") {
          event.preventDefault();
          setTheme((prev) => (prev === "dark" ? "light" : "dark"));
          return;
        }
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [navigate]);
  useEffect(() => {
    const onHash = () => {
      const hashPage = window.location.hash.slice(1);
      if (hashPage === "inference") {
        setStudioMode("inference");
        setInferenceVisited(true);
        setSentinelDraft(null);
        clearSentinelDraft();
      }
      else if (hashPage === "sentinel") {
        setStudioMode("python");
        setInferenceVisited(true);
        const draft = readSentinelDraft();
        setSentinelDraft(draft);
        if (draft) setStudioSource(draft.source);
      }
      else if (hashPage === "studio") {
        setStudioMode("python");
        setSentinelDraft(null);
        clearSentinelDraft();
      }
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
  const refresh = useCallback(async () => {
    const started = performance.now();
    refreshController.current?.abort();
    const controller = new AbortController();
    refreshController.current = controller;
    setRefreshing(true);
    try {
      const config = { timeout: 8000, signal: controller.signal };
      const [health, nodes, stats, modelCatalog] = await Promise.all([
        axios.get(API_URL + "/health", config),
        axios.get(API_URL + "/active_nodes", config),
        axios.get(API_URL + "/stats", config),
        axios.get(API_URL + "/inference/providers", config).catch(() => ({ data: { providers: [] } })),
      ]);
      if (!controller.signal.aborted)
        setTelemetry({
          state: "online",
          health: health.data,
          nodes: Array.isArray(nodes.data) ? nodes.data : [],
          stats: stats.data,
          providers: publicInferenceProviders(modelCatalog.data?.providers),
          updated: new Date(),
          refreshDurationMs: Math.round(performance.now() - started),
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
    <div className="console-app aperture-workspace" ref={appRef}>
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
            Aperture<span>SOLANA AI INFERENCE GATEWAY</span>
          </span>
        </button>
        <nav
          aria-label="Main navigation"
          ref={navRef}
        >
          <span className="console-nav-indicator" aria-hidden="true" />
          {NAV_GROUPS.map((group) => (
            <div className="console-nav-group" key={group.id}>
              <div className="console-nav-label">{group.label}</div>
              {PAGES.filter((item) => item.group === group.id).map((item) => (
                <button
                  key={item.id}
                  className={"console-nav-item " + (page === item.id ? "selected" : "")}
                  aria-current={page === item.id ? "page" : undefined}
                  aria-label={item.label}
                  title={item.label}
                  onClick={() => navigate(item.id)}
                >
                  <Icon name={item.icon} />
                  <span className="console-nav-full">{item.label}</span>
                  <span className="console-nav-short" aria-hidden="true">{item.shortLabel}</span>
                  {item.badge && <span className="console-nav-badge">{item.badge}</span>}
                  {(item.id === "studio" && (studioBusy || inferenceBusy) || item.id === "workflows" && workflowBusy) && (
                    <i className="console-running-dot" />
                  )}
                </button>
              ))}
            </div>
          ))}
        </nav>
        <div className="console-sidebar-bottom">
          <div className="console-devnet">
            <span className={"console-dot " + (gatewayReady ? "ready" : "muted")} />
            {telemetry.health?.demo_mode ? 'OFF_CHAIN preview' : telemetry.health?.environment === 'production' ? 'Production · Solana' : 'Development workspace'}
          </div>
          <span className="console-version">{telemetry.providers.length ? 'Model + compute marketplace' : 'Compute gateway · connect Gemini'}</span>
        </div>
      </aside>
      <div className="console-body">
        <header className="console-topbar">
          <div className="console-breadcrumb">
            <img className="console-mobile-mark" src={logo} alt="" width="26" height="26" />
            <span className="console-breadcrumb-root">Aperture</span><span aria-hidden="true">/</span><strong key={page}>{activePage.label}</strong>
          </div>
          <div className="console-top-actions">
            <div className="console-hud-badge" title={"Gateway: " + API_URL + " · Network: " + (telemetry.health?.demo_mode ? "Off-chain" : "Devnet")}>
              <span className={"console-hud-dot " + (gatewayReady ? "ready" : online ? "warning" : "muted")} />
              <span className="console-hud-label">Gateway</span>
              <span className="console-hud-sep">{new URL(API_URL, window.location.origin).port ? ':' + new URL(API_URL, window.location.origin).port : new URL(API_URL, window.location.origin).hostname}</span>
              <span className="console-hud-badge-tag">{online ? (telemetry.health?.demo_mode ? "Off-chain" : "Devnet") : "offline"}</span>
              {online && Number.isFinite(telemetry.refreshDurationMs) && <span className="console-hud-meta" title="Measured refresh duration for health, worker and statistics requests">{telemetry.refreshDurationMs}ms</span>}
            </div>
            <button
              className="console-search-trigger"
              onClick={() => setShowCommandPalette(true)}
              title="Quick Search & Actions (Ctrl + K)"
              aria-label="Search commands"
            >
              <Icon name="search" size={14} />
              <span>Search</span>
              <kbd>Ctrl K</kbd>
            </button>
            <button
              className="console-attestation-btn"
              onClick={() => setShowReceiptGuide(true)}
              title="Learn how receipt verification works"
              aria-label="Receipt Guide"
            >
              <Icon name="shield" size={14} />
              <span>Receipt Guide</span>
            </button>
            <div className="console-topbar-divider" aria-hidden="true" />
            <button
              className="console-theme-toggle"
              onClick={toggleTheme}
              title={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
              aria-label="Toggle theme"
            >
              <Icon name={theme === 'dark' ? 'sun' : 'moon'} size={15} />
            </button>
            {wallet && !connected && (
              <button
                className="console-wallet-choose-btn"
                aria-label="Choose wallet"
                title="Choose wallet"
                onClick={() => chooseWallet(true)}
              >
                <Icon name="wallet" size={16} />
              </button>
            )}
            <WalletMultiButton />
          </div>
        </header>
        <main id="main-content" tabIndex={-1} className="console-main">
          <div data-page={page} className={"console-page-stage" + (page === "studio" ? " is-studio-page" : "")}>
            <div className="console-page-heading">
              <div className="console-heading-copy">
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

          {wallet?.adapter.name === 'Temporary key' && <aside className="console-session-notice"><Icon name="shield" size={15} /><p>Temporary signing key · this tab only</p><details><summary>Key details</summary><p>The private key is lost on reload or disconnect. Use an external wallet for persistent assets.</p></details></aside>}
          {(page === "studio" || page === "workflows") && <WorkspaceModes mode={page === "workflows" ? "workflows" : studioMode}
            onPython={() => navigate("studio")} onInference={openGeneralInference} onWorkflows={() => navigate("workflows")} inferenceBusy={inferenceBusy} />}
          {page === "overview" && (
            <>
              <section className="console-dispatch" aria-label="Workload dispatch">
                <div className="console-dispatch-main">
                  <span className="console-eyebrow"><Icon name="activity" size={14} /> SOLANA · AI INFERENCE + COMPUTE</span>
                  <h2>Choose a model or worker.<br /><span>Approve each request.</span></h2>
                  <p>Browse configured model routes and live workers, set a spending ceiling, then inspect the signed result. Python jobs and recoverable agent workflows use the same gateway.</p>
                  <div className="console-dispatch-paths" aria-label="Available workload types">
                    <button className="console-dispatch-path" onClick={openSentinelFromOverview}>
                      <span className="console-dispatch-icon"><Icon name="shield" size={19} /></span>
                      <span className="console-dispatch-copy"><strong>AI Sentinel → compute</strong><small>Review the current Python source, then approve a separate worker quote</small></span>
                      <span className="console-dispatch-count">Review + run</span>
                      <Icon name="arrow" size={17} />
                    </button>
                    <button className="console-dispatch-path" onClick={openGeneralInference}>
                      <span className="console-dispatch-icon"><Icon name="spark" size={19} /></span>
                      <span className="console-dispatch-copy"><strong>Model inference</strong><small>Prompt · configured provider · elapsed-time quote</small></span>
                      <span className="console-dispatch-count">{online ? `${telemetry.providers.length} offers` : "—"}</span>
                      <Icon name="arrow" size={17} />
                    </button>
                    <button className="console-dispatch-path" onClick={() => navigate("workflows")}>
                      <span className="console-dispatch-icon"><Icon name="network" size={19} /></span>
                      <span className="console-dispatch-copy"><strong>Agent workflow</strong><small>Partitioned data · durable recovery · signed files</small></span>
                      <span className="console-dispatch-count">Multi-step</span>
                      <Icon name="arrow" size={17} />
                    </button>
                    <button className="console-dispatch-path" onClick={() => navigate("studio")}>
                      <span className="console-dispatch-icon"><Icon name="code" size={19} /></span>
                      <span className="console-dispatch-copy"><strong>Python compute</strong><small>Reviewed source · worker quote · hard limits</small></span>
                      <span className="console-dispatch-count">{online ? `${telemetry.nodes.filter(node => (node.runtimes || ["python"]).includes("python")).length} workers` : "—"}</span>
                      <Icon name="arrow" size={17} />
                    </button>
                  </div>
                  {sentinelLaunchError && <p className="console-footnote" role="alert">{sentinelLaunchError}</p>}
                  <button className="console-text-button console-dispatch-market-link" onClick={() => navigate("network")}>
                    Browse the AI and compute market <Icon name="arrow" size={16} />
                  </button>
                </div>
                <div className="console-dispatch-visual" aria-hidden="true">
                  <div className="dispatch-ring dispatch-ring-outer" />
                  <div className="dispatch-ring dispatch-ring-inner" />
                  <div className="dispatch-center"><img src={logo} alt="" /></div>
                  <span className="dispatch-orbit-label dispatch-label-model"><Icon name="spark" size={13} /> MODEL</span>
                  <span className="dispatch-orbit-label dispatch-label-compute"><Icon name="chip" size={13} /> CPU</span>
                  <span className="dispatch-orbit-label dispatch-label-proof"><Icon name="shield" size={13} /> RECEIPT</span>
                </div>
              </section>

              <LiveDemoShowcase
                gatewayOnline={online}
                gatewayHealth={telemetry.health}
                workerCount={online ? telemetry.nodes.filter(node => (node.runtimes || ["python"]).includes("python")).length : 0}
                modelWorkerCount={online ? activeModelWorkerCount(telemetry.nodes, telemetry.providers) : 0}
                modelOfferCount={online ? telemetry.providers.length : 0}
                onOpenMarket={() => navigate("network")}
                onOpenStudio={(presetId) => {
    const sample = WORKLOADS.find(w => w.id === presetId) || DEFAULT_STUDIO_WORKLOAD;
                  openSample(sample);
                }}
                onOpenInference={openGeneralInference}
                onOpenWorkflows={() => navigate("workflows")}
                onOpenReceiptGuide={() => setShowReceiptGuide(true)}
              />
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
                    "Model offers",
                    online ? telemetry.providers.length : "—",
                    online ? "Operator-configured · live route" : "Gateway unavailable",
                  ],
                  [
                    "wallet",
                    "Settlement",
                    online ? telemetry.health?.demo_mode ? "Off-chain" : "Devnet" : "—",
                    online ? telemetry.health?.demo_mode ? "Off-chain ledger · no on-chain settlement" : telemetry.health?.protocol_config_initialized ? "Protocol configured" : "Protocol setup required" : "Gateway unavailable",
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
            className={"console-studio studio-mode-" + studioMode}
            hidden={page !== "studio"}
            aria-label="Compute Studio"
          >
            <div className="console-studio-body">
              <div id="studio-python-panel" className="console-studio-panel" role="region" aria-labelledby="studio-python-tab" hidden={studioMode !== "python"}>
                <Dashboard
                  code={studioSource}
                  onCodeChange={setStudioSource}
                  gatewayHealth={telemetry.health}
                  gatewayOnline={online}
                  workerCount={online ? telemetry.nodes.filter(node => (node.runtimes || ['python']).includes('python') && node.accepting_tasks !== false).length : 0}
                  workers={online ? telemetry.nodes.filter(node => (node.runtimes || ['python']).includes('python')) : []}
                  workerTarget={workerTarget}
                  onWorkerTargetChange={setWorkerTarget}
                  reviewedSourcesOnly={online && telemetry.nodes.some(node => (node.runtimes || ['python']).includes('python')) && telemetry.nodes.filter(node => (node.runtimes || ['python']).includes('python')).every(node => node.source_policy === 'exact_hash_allowlist')}
                  selection={selection}
                  releasedObject={releasedObject}
                  externalBusy={workflowBusy || inferenceBusy}
                  onBusyChange={setStudioBusy}
                  onRecord={recordRun}
                  onSentinelReview={openSentinelReview}
                  sentinelResult={sentinelDraft ? null : sentinelResult}
                  sentinelAvailable={telemetry.providers.some(provider => provider.protocol === "gemini_generate_content" && activeModelWorkerCount(telemetry.nodes, [provider]) > 0)}
                  sentinelPanel={sentinelDraft ? (<section className="console-studio-sentinel" aria-label="AI Sentinel review">
                <Suspense fallback={<div className="console-panel" style={{ padding: "2.5rem", textAlign: "center" }}>Opening AI Sentinel…</div>}>
                  <Inference key={sentinelDraft.id} apiUrl={API_URL} gatewayHealth={telemetry.health} sentinelDraft={sentinelDraft} onSentinelResult={recordSentinelResult} onReturnToStudio={returnToStudio} onOpenFunding={openFunding} onOpenSetup={() => navigate("guide")} externalBusy={studioBusy || workflowBusy} onBusyChange={setInferenceBusy} onRecord={recordRun} />
                </Suspense>
              </section>) : null}
                  sentinelPanelOpen={Boolean(sentinelDraft)}
                />
              </div>

              {inferenceVisited && !sentinelDraft && <div id="studio-inference-panel" className="console-studio-panel" role="region" aria-labelledby="studio-inference-tab" hidden={studioMode !== "inference"}>
                <Suspense fallback={<div className="console-panel" style={{ padding: "2.5rem", textAlign: "center" }}>Loading model workspace…</div>}>
                  <Inference key={preferredProviderId || "general-inference"} apiUrl={API_URL} gatewayHealth={telemetry.health} preferredProviderId={preferredProviderId} onSentinelResult={recordSentinelResult} onOpenFunding={openFunding} onOpenSetup={() => navigate("guide")} externalBusy={studioBusy || workflowBusy} onBusyChange={setInferenceBusy} onRecord={recordRun} />
                </Suspense>
              </div>}
            </div>
          </section>

          <Suspense fallback={<div className="console-panel" style={{ padding: '2.5rem', textAlign: 'center', color: 'var(--text-dim, #888)' }}>Loading workspace module…</div>}>
            {visitedPages.has("workflows") && (
              <section className="console-workflows" hidden={page !== "workflows"} aria-label="Agent workflows">
                <Workflows apiUrl={API_URL} gatewayHealth={telemetry.health} gatewayOnline={online} externalBusy={studioBusy || inferenceBusy} onBusyChange={setWorkflowBusy} onRecord={recordRun} releasedObject={releasedObject} onOpenStudio={openSample} onOpenFunding={openFunding} />
              </section>
            )}

            {visitedPages.has("storage") && (
              <section className="console-storage" hidden={page !== "storage"} aria-label="Private file storage">
                <Storage apiUrl={API_URL} gatewayHealth={telemetry.health} gatewayOnline={online} onOpenStudio={() => navigate('studio')} onObjectReleased={setReleasedObject} />
              </section>
            )}

            {visitedPages.has("agents") && (
              <section className="console-agents" hidden={page !== "agents"} aria-label="Agent passports">
                <Agents />
              </section>
            )}
          </Suspense>

          {page === "network" && (
            <Suspense fallback={<div className="console-panel" style={{ padding: "2rem" }}>Loading capacity directory…</div>}>
              <ComputeMarket
                apiUrl={API_URL}
                online={online}
                health={telemetry.health}
                nodes={telemetry.nodes}
                updated={telemetry.updated}
                refreshing={refreshing}
                onRefresh={refresh}
                onOpenInference={openInferenceProvider}
                onOpenStudio={node => { if (!busy) { setWorkerTarget(node ? { node_id: node.node_id, worker_pubkey: node.worker_pubkey } : null); navigate("studio"); } }}
                busy={busy}
                onOpenProvider={() => navigate("provider")}
                onOpenWorkflows={() => navigate("workflows")}
                onOpenGuide={() => navigate("guide")}
              />
            </Suspense>
          )}

          {page === "provider" && <Suspense fallback={<div className="console-panel" style={{ padding: '2rem' }}>Loading operator workspace…</div>}><ProviderWorkspace apiUrl={API_URL} health={telemetry.health} onOpenGuide={() => navigate('guide')} onOpenNetwork={() => navigate('network')} /></Suspense>}

          {page === "guide" && (
            <div className="console-guide">
              <section className="console-panel console-capacity-setup" aria-labelledby="capacity-setup-title">
                <div className="console-section-heading">
                  <div>
                    <span className="console-eyebrow">CAPACITY OPERATORS</span>
                    <h2 id="capacity-setup-title">Connect this gateway to real compute capacity.</h2>
                    <p>The original Gemini review and Python compute now share the same gateway, workspace and approval rules.</p>
                  </div>
                  <Icon name="network" size={22} />
                </div>
                <div className="console-capacity-options">
                  <article>
                    <h3>Reconnect AI Sentinel with Gemini</h3>
                    <p>The original code review now uses the current Gemini API. The source is sent only after you review the prompt and sign its bounded request.</p>
                    <CommandBlock label="Set Gemini key for this preview" command={"$env:GEMINI_API_KEY = '<Google AI Studio API key>'"}>
                      <p>The key stays in the inference worker environment. Do not add it to frontend files, the provider catalog or browser storage.</p>
                    </CommandBlock>
                    <CommandBlock label="Run the unified Gemini + Python preview" command={'.\\start_preview.bat'}>
                      <p>It runs Gemini and Python through one gateway in OFF_CHAIN preview mode. Owner signatures are exercised; no Solana payment is made.</p>
                    </CommandBlock>
                  </article>
                  <article>
                    <h3>Connect Gemini to your gateway</h3>
                    <p>Copy the Gemini offer, point the gateway and inference worker to it, and expose the API key to the worker only.</p>
                    <CommandBlock label="Create the Gemini offer file" command={'Copy-Item backend\\inference-providers.gemini.example.json backend\\inference-providers.json -NoClobber'} />
                    <CommandBlock label="Start an inference-only worker" command={'backend\\venv\\Scripts\\python.exe backend\\worker.py --inference-only'}>
                      <p>Set the same absolute <code>APERTURE_INFERENCE_CONFIG</code> path in the gateway environment and <code>backend/.worker.env</code>, then restart both. Keep provider credentials in the worker environment, never in the offer file or browser.</p>
                    </CommandBlock>
                  </article>
                </div>
                <p className="console-footnote">Offers appear after an authenticated worker heartbeat matches the gateway configuration. Discovery is operator-configured. Updated source routes the full confirmed Devnet task charge to the assigned worker; deployment and live payout are not yet verified.</p>
              </section>
              <section className="console-panel console-guide-intro">
                <div>
                  <span className="console-eyebrow">YOUR FIRST USEFUL WORKFLOW</span>
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
                <div className="console-section-heading"><div><span className="console-eyebrow">PROVIDE COMPUTE</span><h2>Operate your connected worker</h2><p>Inspect assigned tasks and actual earnings. Drain new admissions while current work finishes.</p></div><Icon name="chip" size={22} /></div>
                <CommandBlock label="Inspect the local preview worker" command={'backend\\venv\\Scripts\\python.exe scripts\\worker_control.py status --credential-file .aperture\\inference-preview\\worker-access.json'} />
                <p>For the browser workspace, open the local <code>.aperture/inference-preview/worker-access.json</code> file and use its <code>worker_id</code> and <code>worker_token</code>. For a separately configured worker, use its ID and credential from <code>backend/.worker.env</code>.</p>
                <button className="console-button secondary" onClick={() => navigate('provider')}>Open provider workspace<Icon name="arrow" size={16} /></button>
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
          </div>
          <footer className="console-footer">
            <span>
              <img src={logo} alt="" width="18" height="18" />
              Built for curious minds.
            </span>
            <span>{online ? telemetry.health?.demo_mode ? "Off-chain execution" : "Solana Devnet" : "Local workspace"}</span>
          </footer>
        </main>
      </div>
      <ProofVerifierModal
        isOpen={showReceiptGuide}
        onClose={() => setShowReceiptGuide(false)}
      />
      <CommandPalette
        isOpen={showCommandPalette}
        onClose={() => setShowCommandPalette(false)}
        onNavigate={navigate}
        onOpenSample={(sampleId) => {
          const sample = WORKLOADS.find((w) => w.id === sampleId) || WORKLOADS[0];
          openSample(sample);
        }}
        onOpenReceiptGuide={() => setShowReceiptGuide(true)}
        onRefresh={refresh}
        onToggleTheme={toggleTheme}
      />
    </div>
  );
}
