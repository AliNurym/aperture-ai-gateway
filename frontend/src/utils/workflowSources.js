export const MERGE_SOURCE = `from aperture import read_json, parameters, write_json, write_csv
import math
cfg = parameters()
groups = {}
valid = 0
invalid = 0
for name in cfg["input_names"]:
    report = read_json(name)
    valid += report["valid_rows"]
    invalid += report["invalid_rows"]
    for category, data in report["groups"].items():
        if category not in groups:
            if len(groups) >= 10000:
                raise ValueError("Merged report exceeds the bounded category count")
            groups[category] = {"rows": 0, "total": 0}
        groups[category]["rows"] += data["rows"]
        groups[category]["total"] += data["total"]
        if not math.isfinite(groups[category]["total"]):
            raise ValueError("Merged category total exceeds the supported numeric range")
write_json(cfg["output_name"], {"valid_rows": valid, "invalid_rows": invalid, "groups": groups})
if cfg["final"]:
    rows = [{"category": key, "rows": data["rows"], "total": round(data["total"], 4), "average": round(data["total"] / data["rows"], 4)} for key, data in sorted(groups.items())]
    write_csv("categories.csv", rows, ["category", "rows", "total", "average"])
print("Combined", valid + invalid, "records across", len(groups), "categories")
`;
