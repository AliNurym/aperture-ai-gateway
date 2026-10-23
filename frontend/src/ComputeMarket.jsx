import { useCallback, useEffect, useMemo, useState } from "react";
import axios from "axios";
import Icon from "./components/Icon";
import { activeModelWorkerCount, publicInferenceProviders } from "./utils/inference";
import "./ComputeMarket.css";

function formatRate(value) {
  if (!Number.isSafeInteger(value)) return "Quoted per request";
  return `${value.toLocaleString("en-US")} lamports / sec`;
}

function lastSeen(value) {
  return Number.isFinite(value) ? new Date(value * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "Not reported";
}

function executionLabel(node) {
  if (node.execution_mode === "inference_proxy") return "Configured model adapter";
  if (node.execution_mode === "docker") return "Docker container";
  if (node.execution_mode === "trusted_local") return "Trusted local process";
  return "Not reported";
}

function sourceLabel(node) {
  if (node.source_policy === "configured_provider") return "Configured model offers";
  if (node.source_policy === "exact_hash_allowlist") return `${node.approved_source_count ?? 0} reviewed files`;
  if (node.source_policy === "gateway_ast") return "Gateway source policy";
  if (node.source_policy === "operator_trusted") return "Operator trusted code";
  return "Not reported";
}

export default function ComputeMarket({
  apiUrl,
  online,
  health,
  nodes = [],
  updated,
  refreshing,
  onRefresh,
  onOpenInference,
  onOpenStudio,
  onOpenWorkflows,
  onOpenGuide,
  onOpenProvider,
  busy = false,
}) {
  const [providers, setProviders] = useState([]);
  const [directoryState, setDirectoryState] = useState("loading");
  const [filter, setFilter] = useState("all");

  const refreshProviders = useCallback(async (signal) => {
    if (!online) {
      setProviders([]);
      setDirectoryState("offline");
      return;
    }
    try {
      const { data } = await axios.get(apiUrl + "/inference/providers", { timeout: 10000, signal });
      setProviders(publicInferenceProviders(data.providers));
      setDirectoryState("ready");
    } catch {
      if (!signal?.aborted) {
        setProviders([]);
        setDirectoryState("unavailable");
      }
    }
  }, [apiUrl, online]);

  useEffect(() => {
    const controller = new AbortController();
    refreshProviders(controller.signal);
    const timer = setInterval(() => refreshProviders(controller.signal), 15000);
    return () => {
      controller.abort();
      clearInterval(timer);
    };
  }, [refreshProviders]);

  const cpuWorkers = useMemo(() => online ? nodes.filter(node => (node.runtimes || ["python"]).includes("python")) : [], [nodes, online]);
  const inferenceWorkers = useMemo(() => online ? activeModelWorkerCount(nodes, providers) : 0, [nodes, online, providers]);
  const items = useMemo(() => [
    ...(filter !== "models" ? cpuWorkers.map(node => ({ type: "cpu", id: node.node_id, node })) : []),
    ...(filter !== "cpu" ? providers.map(provider => ({ type: "model", id: provider.id, provider })) : []),
  ], [cpuWorkers, filter, providers]);
  const networkLabel = !online ? "Unavailable" : health?.demo_mode ? "OFF_CHAIN" : health?.protocol_config_initialized ? "Solana · Devnet" : "Devnet · setup needed";

  return (
    <div className="compute-market">
      <section className="market-intro" aria-label="Compute network status">
        <div className="market-intro-copy">
          <span className="console-eyebrow"><Icon name="network" size={14} /> APERTURE NETWORK · CAPACITY DIRECTORY</span>
          <h2>Available execution routes</h2>
          <p>Compare live worker capacity with model offers. Each route enters the same owner-authorized task flow, with a bounded quote and signed result.</p>
          <div className="market-intro-actions">
            <button className="console-button primary" onClick={onOpenWorkflows}>Start an agent workflow <Icon name="arrow" size={17} /></button>
            <button className="console-button secondary" onClick={onOpenProvider}>Provide compute</button>
          </div>
        </div>
        <div className="market-snapshot" aria-label="Current network inventory">
          <div><span>Python workers</span><strong>{online ? cpuWorkers.length : "—"}</strong></div>
          <div><span>Model offers</span><strong>{online ? directoryState === "ready" ? providers.length : directoryState === "loading" ? "…" : "—" : "—"}</strong></div>
          <div><span>Model workers</span><strong>{online ? inferenceWorkers : "—"}</strong></div>
          <div className="market-snapshot-network"><span>Settlement path</span><strong>{networkLabel}</strong></div>
        </div>
      </section>

      <section className="market-directory" aria-labelledby="market-directory-title">
        <div className="market-directory-heading">
          <div>
            <span className="console-eyebrow">LIVE DIRECTORY</span>
            <h2 id="market-directory-title">Available capacity</h2>
            <p>Worker status comes from authenticated heartbeats; model endpoints are configured by the gateway operator.</p>
          </div>
          <button className="console-button secondary market-refresh" onClick={() => { onRefresh?.(); refreshProviders(); }} disabled={refreshing} aria-busy={refreshing}>
            <Icon name="refresh" spinning={refreshing} size={16} /> Refresh
          </button>
        </div>

        <div className="market-toolbar">
          <div className="market-filters" role="group" aria-label="Filter capacity">
            {[["all", "All routes"], ["cpu", "CPU compute"], ["models", "Model inference"]].map(([id, label]) => (
              <button key={id} aria-pressed={filter === id} onClick={() => setFilter(id)}>{label}</button>
            ))}
          </div>
          <span className="market-directory-count">{items.length} {items.length === 1 ? "route" : "routes"}</span>
        </div>

        {directoryState === "unavailable" && filter === "all" && cpuWorkers.length > 0 && (
          <p className="market-directory-message" role="status">Model offers could not be refreshed. Live worker capacity remains available below.</p>
        )}

        {items.length > 0 ? (
          <div className="market-list" role="list" aria-label="Compute routes">
            {items.map(item => item.type === "cpu" ? (
              <article className="market-row" role="listitem" key={`cpu:${item.id}`}>
                <span className="market-row-icon"><Icon name="chip" size={20} /></span>
                <div className="market-row-primary">
                  <div className="market-row-title"><h3>Python compute</h3><span className="market-kind">CPU WORKER</span></div>
                  <p>{item.node.node_id}</p>
                    <small className="market-mobile-fields">{item.node.status || "online"} · {executionLabel(item.node)}</small>
                </div>
                <div className="market-row-field"><span>State</span><strong className="market-state"><i />{item.node.status || "online"}</strong></div>
                <div className="market-row-field"><span>Execution</span><strong>{executionLabel(item.node)}</strong></div>
                <div className="market-row-field"><span>Quote</span><strong>Per workload</strong></div>
                <details className="market-row-details">
                  <summary aria-label={`Details for worker ${item.node.node_id}`}><Icon name="chevron" size={16} /></summary>
                  <dl>
                    <div><dt>Signing identity</dt><dd title={item.node.worker_pubkey}>{item.node.worker_pubkey ? `${item.node.worker_pubkey.slice(0, 6)}…${item.node.worker_pubkey.slice(-6)}` : "Not reported"}</dd></div>
                    <div><dt>Last heartbeat</dt><dd>{lastSeen(item.node.last_seen)}</dd></div>
                    <div><dt>Source policy</dt><dd>{sourceLabel(item.node)}</dd></div>
                    <div><dt>Reported hardware</dt><dd>{item.node.gpu_name || "No GPU claim reported"}</dd></div>
                  </dl>
                </details>
                <button className="market-row-action" onClick={() => onOpenStudio(item.node)} disabled={busy || item.node.accepting_tasks === false}>{item.node.accepting_tasks === false ? 'Draining' : 'Use this worker'} <Icon name="arrow" size={15} /></button>
              </article>
            ) : (
              <article className="market-row market-row-model" role="listitem" key={`model:${item.id}`}>
                <span className="market-row-icon market-row-icon-model"><Icon name="spark" size={20} /></span>
                <div className="market-row-primary">
                  <div className="market-row-title"><h3>{item.provider.name}</h3><span className="market-kind">MODEL OFFER</span></div>
                  <p>{item.provider.model}</p>
                    <small className="market-mobile-fields">{item.provider.available_workers} workers · {formatRate(item.provider.rate_lamports_sec)}</small>
                </div>
                <div className="market-row-field"><span>Matching workers</span><strong>{item.provider.available_workers}</strong></div>
                <div className="market-row-field"><span>Rate</span><strong>{formatRate(item.provider.rate_lamports_sec)}</strong></div>
                <div className="market-row-field"><span>Output cap</span><strong>{item.provider.max_output_tokens} tokens</strong></div>
                <details className="market-row-details">
                  <summary aria-label={`Details for model offer ${item.provider.name}`}><Icon name="chevron" size={16} /></summary>
                  <dl>
                    <div><dt>Billing</dt><dd>{item.provider.billing}</dd></div>
                    <div><dt>Offer identity</dt><dd>{item.provider.endpoint_sha256 ? `${item.provider.endpoint_sha256.slice(0, 12)}…` : "Not reported"}</dd></div>
                    <div><dt>Worker settlement</dt><dd>{item.provider.worker_settlement_share_pct ?? 100}% of confirmed Devnet charge</dd></div>
                    <div><dt>Upstream model bill</dt><dd>Paid outside Aperture</dd></div>
                  </dl>
                </details>
                <button className="market-row-action" onClick={() => onOpenInference(item.provider.id)} disabled={item.provider.available_workers < 1}>
                  {item.provider.available_workers > 0 ? "Use this model" : "No matching worker"} <Icon name="arrow" size={15} />
                </button>
              </article>
            ))}
          </div>
        ) : (
          <div className="market-empty">
            <Icon name={online ? "network" : "activity"} size={25} />
            <h3>{!online ? "Gateway is unavailable" : directoryState === "unavailable" && filter !== "cpu" ? "Model directory could not be loaded" : "No routes match this filter"}</h3>
            <p>{!online ? "Reconnect the gateway to read live worker and model capacity." : filter === "cpu" ? "Start an authenticated Python worker to publish compute capacity." : "Configure a model offer and matching inference worker to add a model route."}</p>
            {!online ? <button className="console-button secondary" onClick={onRefresh}>Retry connection</button> : <button className="console-button secondary" onClick={onOpenGuide}>Open setup guide</button>}
          </div>
        )}
      </section>

      <section className="market-boundary" aria-label="Directory scope">
        <div className="market-boundary-symbol"><Icon name="shield" size={18} /></div>
        <div><strong>Live capacity, bounded tasks</strong><p>Worker availability follows authenticated heartbeats. Model offers are managed by the gateway operator.</p><details className="market-settlement-details"><summary>Pricing and settlement details</summary><p>Pricing uses elapsed time, including upstream waiting. Upstream model bills remain outside Aperture. Updated program source routes 100% of a confirmed Devnet task charge to its assigned worker; deployment and live payout are not yet verified.</p></details></div>
        <div className="market-boundary-state"><span>Last network refresh</span><strong>{updated ? updated.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "Not yet"}</strong></div>
      </section>
    </div>
  );
}
