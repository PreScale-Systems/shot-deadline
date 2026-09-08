# Shot Deadline

**Why is Sequence 040 late?** Shot Deadline is a VFX war room: a live shot board for a show in its last weeks, and a Gemini agent that reads the render farm, review pipeline and vendor delivery telemetry through the **Grafana Cloud MCP server**, works out *why* a sequence is slipping — a broken plugin on one node pool, a vendor out of capacity, a supervisor review backlog — records it as a Grafana annotation or incident, and writes the replan and the producer's morning note.

Built for the **Agentic Cinema hackathon — Grafana Labs track**, on Google Cloud Agent Builder (ADK) + Gemini, with the official `mcp-grafana` server at runtime.

## Why this exists

A VFX supervisor tracks hundreds of shots across vendors against a picture-lock date. When a sequence slips, the answer is spread across the farm's queue, GPU nodes, render logs, and review turnaround — five dashboards and three vendor emails. Shot Deadline answers the question in one place, with every PromQL and LogQL query shown, and turns the answer into moves.

## How it works

```
question ─▶ ShotDeadline (ADK SequentialAgent)
             ├─ triage   LlmAgent (Gemini 2.5 Pro) + MCPToolset ──stdio──▶ mcp-grafana ──▶ Grafana Cloud
             │           list_datasources → query_prometheus → query_loki_logs → create_annotation / create_incident
             └─ planner  LlmAgent (Gemini 2.5 Pro) writes the replan + status note

telemetry/sim.py ──OTLP (metrics + logs)──▶ Grafana Cloud OTLP gateway ──▶ Mimir + Loki
```

- **The agent only reads Grafana through the official MCP server** (`agent/pipeline.py`: `MCPToolset` + `StdioConnectionParams` → `mcp-grafana -t stdio`), with a tool filter of query, search, annotation and incident tools. Its instruction is a fixed triage procedure: status → where the work is stuck → log evidence → review latency → distinguish farm fault vs vendor capacity vs review bottleneck → annotate.
- **The telemetry is real OpenTelemetry.** `telemetry/sim.py` runs a time-compressed production (one production hour per `TICK_SECONDS`) and exports observable gauges, counters and logs through the OTLP HTTP exporter to your Grafana Cloud stack: `vfx_shots`, `vfx_shot_days_to_due`, `vfx_sequence_days_to_lock`, `render_queue_depth`, `render_jobs_failed_total`, `render_jobs_completed_total`, `gpu_utilization_ratio`, `review_turnaround_hours`, and `RENDER FAILED …` log lines with shot/node/error attributes.
- **The dashboard** (`grafana/dashboard.json`, imported by `scripts/provision.py`) shows days to lock, shots past due, failures by vendor/node/error, queue depth, GPU utilisation, review turnaround and the render log. Agent annotations appear on it (tag `shot-deadline`). Suggested alert rules are in `grafana/alerts.md`.
- **The UI** (`web/index.html`) is the shot board — sequences, shots coloured by status, farms with queue and GPU load, the live log — with the agent chat beside it. Shots the triage names get outlined on the board.

Runtime integrations, in code:

| Requirement | Where |
|---|---|
| Google ADK | `agent/pipeline.py` (`SequentialAgent`, `LlmAgent`, `MCPToolset`), `app/main.py` (`InMemoryRunner`) |
| Gemini via `google-genai` (through ADK) | `agent/pipeline.py` |
| Grafana Cloud MCP server | `agent/pipeline.py` → `mcp-grafana` v1.3.0 (`query_prometheus`, `query_loki_logs`, `create_annotation`, `create_incident`, …) |
| Grafana Cloud metrics + logs | `telemetry/sim.py` (OpenTelemetry SDK → OTLP gateway) |
| Google Cloud runtime | Cloud Run (`Dockerfile`, `scripts/deploy.sh`), Vertex AI, Secret Manager |

## The show: *IRONWAKE*

A fictional feature in its final weeks: 70 shots across four sequences, three vendors (Halcyon VFX, Northlight, the in-house farm), lock dates from 9 to 21 days out. The simulation seeds a story with more than one cause:

- **Sequence 040 (the storm)** is slipping. Halcyon's ocean shots are pinned to the water-sim pool, `halcyon-gpu-07…12`, which lost `oceanfx 3.2` in a driver update; they fail on every attempt and the Halcyon queue climbs past 100.
- **Northlight's** shots render fine but their supervisor review turnaround has crept to 60+ hours — a review bottleneck, not a farm one.
- **The in-house farm** is under half utilised: spare capacity the replan should use.

## Run it

```bash
# Grafana Cloud (free tier is enough): create a service account token with Editor role,
# and copy the OTLP gateway endpoint + basic-auth header from Connections → OpenTelemetry.
curl -sL https://github.com/grafana/mcp-grafana/releases/download/v1.3.0/mcp-grafana_Linux_x86_64.tar.gz | tar xz mcp-grafana && sudo mv mcp-grafana /usr/local/bin/
cp .env.example .env    # fill GRAFANA_*, OTEL_*, GOOGLE_API_KEY (or Vertex)
set -a; . ./.env; set +a
python scripts/provision.py     # imports the dashboard
./scripts/run_local.sh          # starts the simulation + emitter + UI at http://localhost:8080
```

Give the emitter ten minutes before asking the agent so the failure pattern is visible in Grafana.

## Deploy to Cloud Run

```bash
PROJECT=... REGION=us-central1 GRAFANA_URL=https://yourstack.grafana.net \
OTEL_EXPORTER_OTLP_ENDPOINT=https://otlp-gateway-prod-us-east-2.grafana.net/otlp ./scripts/deploy.sh
```

The service runs with `--min-instances 1 --max-instances 1 --no-cpu-throttling` so the simulation keeps emitting between requests.

## Ask it

- Why is Sequence 040 late?
- Which farm has spare capacity right now?
- Is Northlight blocked on the farm or on reviews?
- Open an incident for the SEQ040 render failures
- Write the morning status note for the producer

## What we learned

- Seed more than one cause. A single root cause makes triage look like pattern matching; two overlapping ones (pipeline fault + review latency) make the agent's *distinguishing* step visible and valuable.
- Observable gauges with rich labels beat counters for production state — "shots by sequence, vendor, status" is one PromQL away from any question a coordinator asks.
- Writing back matters. An annotation on the dashboard is the difference between an answer and a record of the answer.

## License

MIT — see `LICENSE`.
