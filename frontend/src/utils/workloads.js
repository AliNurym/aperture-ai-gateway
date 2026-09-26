export const WORKLOADS = [
  {
    id: "risk",
    name: "Agent batch risk scoring",
    category: "Agent analytics",
    icon: "shield",
    description: "Rank a fixed portfolio with reproducible Monte Carlo loss estimates.",
    code: '# Agent tool: deterministic batch scenario scoring\nimport random\nimport statistics\nimport json\n\nrng = random.Random(42)\nportfolios = [("balanced", 0.45, 0.08), ("growth", 0.75, 0.14), ("conservative", 0.20, 0.04)]\nresults = []\nfor name, exposure, volatility in portfolios:\n    losses = [max(0, -(exposure * rng.gauss(0.01, volatility))) for _ in range(20000)]\n    ordered = sorted(losses)\n    tail = ordered[int(len(ordered) * 0.95):]\n    results.append({"portfolio": name, "loss_p95": round(ordered[int(len(ordered) * 0.95)], 6), "tail_mean": round(statistics.fmean(tail), 6)})\nresults.sort(key=lambda item: item["tail_mean"])\nprint(json.dumps({"seed": 42, "scenarios_per_portfolio": 20000, "ranking": results}, sort_keys=True))\n',
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

// Presentation only: never executes Python or authorizes a gateway workload.
export function estimateDemo(code) {
  if (!code.trim()) throw new Error("Add a Python workload before running it.");
  if (code.length > 32000)
    throw new Error("Workloads must be 32,000 characters or smaller.");
  if (new TextEncoder().encode(code).length > 65536)
    throw new Error("Workloads must be 64 KB or smaller.");
  const restricted =
    /(?:^|\n)\s*(?:import\s+(?:os|sys|subprocess|socket)\b|from\s+(?:os|sys|subprocess|socket)\b)/.test(
      code,
    );
  const score = Math.min(
    95,
    18 +
      (code.match(/\bfor\b/g) || []).length * 12 +
      (code.match(/\b(?:math|statistics)\./g) || []).length * 6,
  );
  return { restricted, score, rateLamports: Math.round(400 + score * 11) };
}

export function resultStatus(output, receipt) {
  if (receipt?.execution_status) return receipt.execution_status;
  if (output === "EXECUTION_ABORTED_BY_USER") return "cancelled";
  if (output === "EXECUTION_LEASE_EXPIRED") return "failed";
  return "completed";
}
