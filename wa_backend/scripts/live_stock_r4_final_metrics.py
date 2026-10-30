"""R4 evidence math: no production latency SLA or recursive buffer summation."""
from __future__ import annotations

import math
import os
import platform
try:
    import resource
except ImportError:
    resource = None
from pathlib import Path


def distribution(values):
    assert values and all(math.isfinite(v) and v >= 0 for v in values)
    ordered = sorted(values)
    def rank(p):
        return round(ordered[max(0, math.ceil(len(ordered) * p) - 1)], 3)
    return {"n": len(values), "method": "nearest rank", "min_ms": round(ordered[0], 3),
            "p50_ms": rank(.50), "p95_ms": rank(.95), "p99_ms": rank(.99),
            "max_ms": round(ordered[-1], 3)}


def nodes(root):
    yield root
    for child in root.get("Plans", []):
        yield from nodes(child)


def plan_evidence(top, catalog_size):
    root = top["Plan"]
    entries, memory = [], []
    for node in nodes(root):
        if "Scan" in node.get("Node Type", "") or node.get("Actual Loops", 0) > 1000 or (
                node.get("Node Type") == "Aggregate" and node.get("Actual Loops", 0) > 1):
            examined = ((node.get("Actual Rows") or 0) +
                        (node.get("Rows Removed by Filter") or 0)) * (node.get("Actual Loops") or 0)
            entries.append({k: node.get(k) for k in (
                "Node Type", "Relation Name", "Alias", "Index Name", "CTE Name",
                "Actual Rows", "Actual Loops", "Rows Removed by Filter",
                "Rows Removed by Join Filter", "Index Cond", "Filter", "Plan Rows")} |
                {"emitted_plus_filter_rows_x_loops": examined,
                 "catalog_sized_work": examined >= catalog_size})
        fields = {k: node[k] for k in (
            "Peak Memory Usage", "Sort Space Used", "Sort Space Type",
            "Hash Batches", "Disk Usage") if k in node}
        if fields:
            memory.append({"node": node["Node Type"], **fields})
    hits, reads = root.get("Shared Hit Blocks", 0), root.get("Shared Read Blocks", 0)
    return {"execution_ms": top["Execution Time"], "planning_ms": top["Planning Time"],
            "root_buffers": {k: root.get(k, 0) for k in (
                "Shared Hit Blocks", "Shared Read Blocks", "Temp Read Blocks", "Temp Written Blocks")},
            "shared_buffer_hit_fraction": hits / (hits + reads) if hits + reads else None,
            "scans": entries, "memory_nodes": memory,
            "indexes": sorted({n["Index Name"] for n in nodes(root) if "Index Name" in n}),
            "warning": "Buffers are inclusive root totals. Scan work is per node, not summed; "
                       "index entries eliminated in Index Cond are not all visible as Actual Rows. "
                       "Shared reads can be OS-cache hits, not physical disk reads. "
                       "Memory-node kB is not total PostgreSQL process memory."}


def assert_constant_counts(records):
    assert records and len(set(records)) == 1, records


def assert_bounded_plan(top, limit, kind):
    all_nodes = list(nodes(top["Plan"]))
    if kind == "list":
        names = {"CTE inventory_page_candidates": limit + 1,
                 "CTE inventory_detail_keys": limit}
        for name, bound in names.items():
            found = [n for n in all_nodes if n.get("Subplan Name") == name]
            assert len(found) == 1 and found[0]["Actual Rows"] <= bound, (name, found)
    elif kind in {"families", "batches"}:
        limits = [n for n in all_nodes if n.get("Node Type") == "Limit" and n.get("Actual Loops", 0)]
        assert limits and limits[0]["Actual Rows"] <= limit + 1, limits


def rss_high_water():
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss if resource else None


def assert_selective_point_scans(entries):
    executed = [n for n in entries if n.get("Relation Name") == "product_variants" and n.get("Actual Loops")]
    assert executed
    assert all(n["emitted_plus_filter_rows_x_loops"] <= 1 and n["Index Name"] in {
        "uq_product_variants_company_id", "pk_product_variants"} for n in executed), executed
    assert not any(n.get("Node Type") == "Aggregate" and n.get("Actual Loops", 0) > 1 for n in entries)


def hardware():
    def read(path):
        p = Path(path)
        return p.read_text().strip() if p.is_file() else None
    cpu = read("/proc/cpuinfo") or ""
    return {"platform": platform.platform(), "python": platform.python_version(),
            "logical_cpus": os.cpu_count(),
            "affinity_cpus": len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else None,
            "cpu_model": next((line.split(":", 1)[1].strip() for line in cpu.splitlines()
                               if line.startswith("model name")), None),
            "meminfo": read("/proc/meminfo"), "cgroup_memory_max": read("/sys/fs/cgroup/memory.max"),
            "rss_high_water_kib": rss_high_water(),
            "runner": os.environ.get("RUNNER_NAME"),
            "limits": "Shared GitHub ubuntu-24.04 runner; one Python process, local ASGI transport, "
                      "loopback PostgreSQL Docker. No TCP/TLS/browser/production load, "
                      "no controlled CPU isolation or guaranteed OS/DB cold cache."}
