"""Print the interesting server-side spans from a /metrics JSON snapshot (stdin)."""

import json
import sys

SPANS = [
    "http POST /inventory/reserve",
    "inventory.lock_wait",
    "inventory.lock_held",
    "db.pool_acquire",
    "db.transaction",
    "db.select_stock",
    "db.update_stock",
    "db.insert_reservation",
]

snapshot = json.load(sys.stdin)
print(f"  {'span':32} {'count':>8} {'p50 ms':>9} {'p99 ms':>9}")
for name in SPANS:
    s = snapshot["spans"].get(name)
    if s:
        print(f"  {name:32} {s['count']:>8} {s['p50_ms']:>9.2f} {s['p99_ms']:>9.2f}")
process = snapshot["process"]
print(f"  app process: cpu {process['cpu_percent']}%  rss {process['rss_mb']} MB")
