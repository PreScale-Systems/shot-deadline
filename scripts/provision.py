"""Import the Shot Deadline dashboard into Grafana Cloud, wiring it to your Prometheus and Loki datasources.

    GRAFANA_URL=https://yourstack.grafana.net GRAFANA_SERVICE_ACCOUNT_TOKEN=... python scripts/provision.py
"""
import json
import os
import sys
from pathlib import Path

import requests

url = os.environ["GRAFANA_URL"].rstrip("/")
h = {"Authorization": f"Bearer {os.environ['GRAFANA_SERVICE_ACCOUNT_TOKEN']}", "Content-Type": "application/json"}
ds = requests.get(f"{url}/api/datasources", headers=h, timeout=30).json()


def pick(dtype: str):
    # Grafana Cloud stacks ship internal datasources of the same type
    # (alert-state-history, usage insights, ML); prefer the primary stack ones.
    cands = [d for d in ds if d["type"] == dtype]
    internal = ("alert-state", "usage-insight", "ml-metrics", "demoinfra")
    cands = [d for d in cands if not any(t in d["uid"] for t in internal)] or cands
    for key in ("grafanacloud-logs", "grafanacloud-prom"):
        for d in cands:
            if d["uid"] == key:
                return d
    return next((d for d in cands if d.get("isDefault")), cands[0] if cands else None)


prom = pick("prometheus")
loki = pick("loki")
if not prom or not loki:
    sys.exit(f"need a Prometheus and a Loki datasource; found {[d['type'] for d in ds]}")
raw = (Path(__file__).resolve().parent.parent / "grafana" / "dashboard.json").read_text()
raw = raw.replace("${DS_PROMETHEUS}", prom["uid"]).replace("${DS_LOKI}", loki["uid"])
dash = json.loads(raw)
dash.pop("id", None)
r = requests.post(f"{url}/api/dashboards/db", headers=h, json={"dashboard": dash, "overwrite": True, "folderId": 0}, timeout=30)
r.raise_for_status()
print("dashboard:", url + r.json()["url"])
print("prometheus uid:", prom["uid"], "| loki uid:", loki["uid"])
