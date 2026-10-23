import { useState } from "react";
import Icon from "./Icon";
import "./LiveDemoShowcase.css";

const STEPS = [
  {
    id: "capacity",
    number: "01",
    title: "Discover capacity",
    icon: "network",
    eyebrow: "CAPACITY MESH",
    heading: "Choose a model or a worker.",
    copy: "Browse authenticated Python workers and model offers configured by the gateway operator. Both lead into the same task control plane.",
    note: "Worker availability comes from live heartbeats. Model offers are operator-configured; permissionless discovery is not enabled.",
    actionLabel: "Browse live capacity",
    action: "market",
  },
  {
    id: "approval",
    number: "02",
    title: "Approve the task",
    icon: "shield",
    eyebrow: "OWNER AUTHORIZATION",
    heading: "Set the boundary before dispatch.",
    copy: "Review the exact source or prompt, inputs, runtime and spend ceiling. A wallet signature binds approval to that task; an agent passport adds owner-set limits and revocation.",
    note: "Each workflow step receives its own review and approval, so later work cannot silently widen an earlier authorization.",
    actionLabel: "Review a Python task",
    action: "studio",
  },
  {
    id: "dispatch",
    number: "03",
    title: "Dispatch bounded work",
    icon: "chip",
    eyebrow: "BOUNDED EXECUTION",
    heading: "One gateway, three workload paths.",
    copy: "Run a reviewed Python job, route a chat request to a configured model adapter, or compose a durable data workflow. Limits and result evidence follow each accepted task.",
    note: "The current worker profile is CPU-based. A configured model endpoint receives the approved prompt; upstream answer quality is not guaranteed.",
    actionLabel: "Try model inference",
    action: "inference",
  },
  {
    id: "settlement",
    number: "04",
    title: "Settle and recover",
    icon: "wallet",
    eyebrow: "PAYMENT + RECOVERY",
    heading: "Keep settlement state with the task.",
    copy: "When Devnet is configured and the owner's payment channel is funded, the gateway can settle within the approved cap. Resumable workflows use a durable journal to recover accepted steps after interruption.",
    note: "OFF_CHAIN preview sends no Solana payment. Updated Devnet source routes 100% of a confirmed task charge to its assigned worker; upstream model API bills remain outside Aperture.",
    actionLabel: "Build a recoverable workflow",
    action: "workflows",
  },
  {
    id: "receipt",
    number: "05",
    title: "Inspect the receipt",
    icon: "check",
    eyebrow: "RESULT EVIDENCE",
    heading: "Trace what was authorized and returned.",
    copy: "The signed receipt links task identity, execution status, charge and output hashes. The console checks gateway and worker signatures and verifies Devnet evidence when present.",
    note: "A valid receipt proves the evidence is bound to the task. It does not prove that a remote worker computed the answer correctly.",
    actionLabel: "Open receipt guide",
    action: "receipt",
  },
];

function settlementStatus(online, health) {
  if (!online) return { value: "Awaiting gateway", detail: "Connect the gateway to read its settlement mode." };
  if (health?.demo_mode) return { value: "OFF_CHAIN", detail: "Execution is real; no on-chain payment is sent." };
  if (health?.protocol_config_initialized) return { value: "Devnet configured", detail: "A funded owner channel is still required to settle." };
  return { value: "Devnet setup needed", detail: "The payment program is not ready on this gateway." };
}

export default function LiveDemoShowcase({
  gatewayOnline = false,
  gatewayHealth = null,
  workerCount = 0,
  modelWorkerCount = 0,
  modelOfferCount = 0,
  onOpenMarket,
  onOpenStudio,
  onOpenInference,
  onOpenWorkflows,
  onOpenReceiptGuide,
}) {
  const [activeId, setActiveId] = useState("capacity");
  const active = STEPS.find((step) => step.id === activeId) || STEPS[0];
  const payment = settlementStatus(gatewayOnline, gatewayHealth);

  const facts = active.id === "capacity"
    ? [
        { label: "Python workers", value: gatewayOnline ? workerCount : "—" },
        { label: "Model offers", value: gatewayOnline ? modelOfferCount : "—" },
        { label: "Inference workers", value: gatewayOnline ? modelWorkerCount : "—" },
      ]
    : active.id === "approval"
      ? [
          { label: "Identity", value: "Owner wallet + agent key" },
          { label: "Task binding", value: "Source or prompt + inputs" },
          { label: "Limits", value: "Spend cap + runtime" },
        ]
      : active.id === "dispatch"
        ? [
            { label: "Python", value: "Reviewed worker task" },
            { label: "Inference", value: "Configured model adapter" },
            { label: "Workflow", value: "Journaled task steps" },
          ]
        : active.id === "settlement"
          ? [
              { label: "Settlement", value: payment.value },
              { label: "Recovery", value: "Durable workflow journal" },
              { label: "Worker payout", value: "100% of confirmed charge" },
            ]
          : [
              { label: "Signatures", value: "Gateway + worker" },
              { label: "Integrity", value: "Output SHA-256" },
              { label: "Scope", value: "Evidence, not correctness" },
            ];

  const actions = {
    market: onOpenMarket,
    studio: () => onOpenStudio?.("risk"),
    inference: onOpenInference,
    workflows: onOpenWorkflows,
    receipt: onOpenReceiptGuide,
  };

  return (
    <section className="console-panel live-demo-showcase" aria-labelledby="protocol-tour-title">
      <div className="demo-showcase-header">
        <div className="demo-header-copy">
          <span className="demo-live-badge"><Icon name="activity" size={14} /> APERTURE PROTOCOL · FIVE STEPS</span>
          <h2 id="protocol-tour-title">From open capacity to accountable AI work.</h2>
          <p>Explore how the earlier compute mesh joins the current owner-approved task flow.</p>
        </div>
        <span className={"demo-tour-connection " + (gatewayOnline ? "connected" : "")}>
          <i aria-hidden="true" /> {gatewayOnline ? "LIVE GATEWAY DATA" : "GATEWAY NOT CONNECTED"}
        </span>
      </div>

      <div className="demo-tour-layout">
        <div className="demo-tour-steps" role="group" aria-label="Aperture protocol stages">
          {STEPS.map((step) => (
            <button
              key={step.id}
              type="button"
              className={"demo-tour-step " + (active.id === step.id ? "selected" : "")}
              aria-pressed={active.id === step.id}
              onClick={() => setActiveId(step.id)}
            >
              <span className="demo-tour-number">{step.number}</span>
              <span className="demo-tour-step-copy">
                <strong>{step.title}</strong>
                <small>{step.eyebrow}</small>
              </span>
              <Icon name="chevron" size={16} />
            </button>
          ))}
        </div>

        <article className="demo-tour-panel" aria-live="polite">
          <div className="demo-tour-panel-head">
            <span className="demo-tour-icon"><Icon name={active.icon} size={21} /></span>
            <span className="demo-tour-stage">STAGE {active.number} <i /> {active.eyebrow}</span>
          </div>
          <h3>{active.heading}</h3>
          <p className="demo-tour-copy">{active.copy}</p>
          <div className="demo-tour-facts">
            {facts.map((fact) => (
              <div className="demo-tour-fact" key={fact.label}>
                <span>{fact.label}</span>
                <strong>{fact.value}</strong>
              </div>
            ))}
          </div>
          <p className="demo-tour-note"><Icon name="shield" size={15} />{active.id === "settlement" ? payment.detail + " " : ""}{active.note}</p>
          <button className="console-button secondary demo-tour-action" type="button" onClick={actions[active.action]}>
            {active.actionLabel}<Icon name="arrow" size={16} />
          </button>
        </article>
      </div>
    </section>
  );
}
