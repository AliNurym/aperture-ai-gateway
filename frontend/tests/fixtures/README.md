# Synthetic SDK output fixtures

`report.json` and `categories.csv` were produced by the local OFF_CHAIN demo:

```text
python scripts/demo_workflow.py --rows 12000 --mcp-workflow --output OUTPUT_DIRECTORY
```

They contain synthetic data only: 11988 accepted records, 12 skipped records and
four categories. Counts, category totals and file hashes were independently
checked on 2026-10-02. The frontend tests retain these actual SDK outputs to
check compatibility with its JSON report and CSV table preview.
