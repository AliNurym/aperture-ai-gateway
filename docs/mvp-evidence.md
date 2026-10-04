# What this MVP proves

Aperture currently serves a developer who delegates a bounded CSV report to a
separate agent. The owner uploads data, approves a known report plan and maximum
budget, and receives verified files in the console. An SDK receiver or MCP host
holds the agent key and durable journal. It does not need to copy dataset bytes
into a model prompt. The inbox currently accepts the reviewed CSV preset;
generic Python jobs use the separate Studio/SDK tools.

The CSV result covers grouped totals, row counts, averages, minima/maxima and
excluded-row reasons. It is deterministic data processing, not an included AI
model, business interpretation, duplicate detection or forecasting.

## Reproduce the product path

```powershell
backend\venv\Scripts\python.exe scripts\demo_workflow.py --rows 17000 --owner-handoff --regional-csv --console-workflow --compare-local --output .aperture-runs\comparison
backend\venv\Scripts\python.exe scripts\check_mcp_stdio.py --assigned --output .aperture-runs\mcp-assigned
```

The first check generates regional CSV data, uploads it as the owner, assigns it
to another agent, approves a chain and interrupts the first admission before its
local journal commit. Recovery must finish exactly five tasks, with no duplicate
admission. Exact totals/exclusions, owner downloads and all three result-file
hashes are checked. Direct Python runs the same sources on identical batch bytes;
the final reports must match byte for byte.

The second uses the actual MCP stdio transport. It closes the first agent-host
process after an admission, restarts with the retained journal and finishes the
same three-step chain. All 19 tools are advertised; the approved inbox returns
compact metadata rather than full plans. SDK/MCP result bytes must match and
synthetic storage must be released.

Both checks use reviewed trusted-local CPU execution and OFF_CHAIN receipts.
They do not establish Docker isolation, Devnet payment, remote throughput or UI
usability. Functional tests cover owner stop before admission and cancellation
of a tracked task while no agent host is publishing progress.

## CPU profile and economic claims

`cpu-csv-v2` binds the exact reviewed batch/merge source hashes. It streams CSV
input, uses the Python standard library and decimal arithmetic, and permits at
most 10,000 groups and six fractional digits. Docker tasks are configured for
1 CPU, 512 MiB, no network, 64 MiB of inputs and at most 180 seconds per step.
Output files are limited to 8 MiB each and 16 MiB total. Preflight resolves the
Docker image to an immutable ID used for subsequent jobs; receipt metadata
reports that ID. Trusted-local metadata reports its actual Python version.

Start around 5,000 rows per batch, then measure actual columns and cardinality:

```powershell
backend\venv\Scripts\python.exe scripts\benchmark_csv_profile.py --rows 50000 --groups 10000 --output .aperture-runs\cpu-profile.json
```

The benchmark records per-step elapsed time, peak process memory, source hashes,
Python version and platform, and independently checks the exact decimal total.
It runs direct local Python without enforcing Docker resource limits; its
measurement is a sizing aid, not a guaranteed capacity certificate.

The CSV price is an operator-set tariff (`APERTURE_CSV_RATE_LAMPORTS_SEC`, default
1,000). It is not inferred from hardware performance or SOL market value. The
quote binds rate, budget and affordable runtime. Custom/legacy sources retain
their explicitly labeled AST heuristic. OFF_CHAIN receipts make no payment;
the comparison reports an equivalent tariff estimate separately. No USD cost,
provider margin or claim of being cheaper than cloud compute is established.

A same-host run on 4 October 2026, Python 3.13.14/Windows 11, measured 17,000
rows in 0.86 seconds for direct Python and 7.83 seconds for the gateway path.
The latter includes uploads, assignment, approvals, intentional interruption,
recovery and verified downloads; neither includes service startup or a human's
wallet response time. It made no payment; its equivalent tariff estimate was
859 lamports. Input batches occupied 238,131 bytes, while their JSON descriptors
occupied 685 bytes. Those are byte counts, not measured LLM context or tokens.
These timings describe one run and do not establish speed superiority.

Separate local sizing runs processed 50,000 rows with 4 groups in 2.21 seconds
(20.4 MiB peak process memory) and 10,000 groups in 2.62 seconds (34.0 MiB peak).
They used short synthetic values and no Docker CPU limit. Real exports can be
larger or slower; rerun the benchmark on the intended host.

The demonstrated advantage is bounded delegation, recoverable accepted work and
verified result delivery. For a one-off calculation on a machine where you
already trust and control Python, that extra infrastructure may be unnecessary.
Repeat use by independent users, supported deployment profiles and measured
real-world workload economics remain necessary before broader product claims.
