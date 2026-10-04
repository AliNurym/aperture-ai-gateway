import csvSources from '../../../backend/workloads/csv_sources.json' with { type: 'json' };

export const WORKLOADS = [
  {
    id: 'dataset', name: 'Dataset → category report', category: 'Agent data jobs', icon: 'network', dataJob: true,
    description: 'Process your CSV dataset and return a reusable JSON summary and CSV report.',
    parameters: { input_name: 'dataset.csv' },
    code: csvSources.batch,
  },
  {
    id: "risk",
    name: "Agent batch risk scoring",
    category: "Agent analytics",
    icon: "shield",
    description: "Calculate 1.5 million reproducible loss scenarios and rank three portfolios.",
    code: `# Agent tool: deterministic batch scenario scoring
import random
import statistics
import json

# Synthetic inputs for a reproducible compute example; not financial advice.
rng = random.Random(42)
scenarios = 500_000
portfolios = [("balanced", 0.45, 0.08), ("growth", 0.75, 0.14), ("conservative", 0.20, 0.04)]
results = []
print(json.dumps({"stage": "started", "total_scenarios": scenarios * len(portfolios)}), flush=True)
for name, exposure, volatility in portfolios:
    losses = [max(0, -(exposure * rng.gauss(0.01, volatility))) for _ in range(scenarios)]
    ordered = sorted(losses)
    tail = ordered[int(len(ordered) * 0.95):]
    result = {"portfolio": name, "loss_p95": round(ordered[int(len(ordered) * 0.95)], 6), "tail_mean": round(statistics.fmean(tail), 6)}
    results.append(result)
    print(json.dumps({"stage": "portfolio_completed", "completed_scenarios": scenarios * len(results), **result}), flush=True)
results.sort(key=lambda item: item["tail_mean"])
print(json.dumps({"seed": 42, "scenarios_per_portfolio": scenarios, "ranking": results}, sort_keys=True))
`,
  },
  {
    id: "math",
    name: "Numerical analysis",
    category: "Mathematics",
    icon: "grid",
    description: "A small deterministic calculation. A good place to start.",
    code: '# Numerical analysis\nimport math\n\nvalues = [math.sqrt(n) for n in range(1, 2000)]\nmean = sum(values) / len(values)\nprint(f"Mean root score: {mean:.6f}")\n',
  },
  {
    id: "statistics",
    name: "Statistical summary",
    category: "Data processing",
    icon: "network",
    description: "Calculate the mean and spread of a generated dataset.",
    code: '# Statistical summary\nimport statistics\n\nsamples = [((n * 17) % 101) / 10 for n in range(512)]\nmean = statistics.fmean(samples)\nspread = statistics.pstdev(samples)\nprint(f"Mean: {mean:.3f}; standard deviation: {spread:.3f}")\n',
  },
  {
    id: "policy",
    name: "Policy rejection",
    category: "Policy example",
    icon: "shield",
    description: "See how a restricted import is handled before dispatch.",
    code: '# Policy rejection example\n# No system command is invoked by this sample.\nimport os\nprint("This import is outside the allowed policy.")\n',
  },
];

// Client input limits only. Source policy and quotes are evaluated by the gateway.
export const MAX_SOURCE_BYTES = 32000;

export function validateSource(code) {
  if (!code.trim()) throw new Error("Add a Python workload before running it.");
  if (code.length > 32000)
    throw new Error("Workloads must be 32,000 characters or smaller.");
  if (new TextEncoder().encode(code).length > MAX_SOURCE_BYTES)
    throw new Error("Workloads must be 32,000 UTF-8 bytes or smaller.");
}

export function resultStatus(output, receipt) {
  if (receipt?.execution_status) return receipt.execution_status;
  if (output === "EXECUTION_ABORTED_BY_USER") return "cancelled";
  if (output === "EXECUTION_LEASE_EXPIRED") return "failed";
  return "completed";
}
