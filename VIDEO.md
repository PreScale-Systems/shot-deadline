# 3-minute demo — shot list

Start the service at least 15 minutes before recording so Grafana has the failure pattern. Have the Grafana dashboard open in a second tab.

| Time | On screen | Say |
|---|---|---|
| 0:00–0:20 | Shot board: SEQ040 red-bordered, render-failed ocean shots, ~8 days to lock | "IRONWAKE, three weeks from delivery. Sequence 040 is the storm, and it's slipping. Normally this is five dashboards and three vendor emails. This is Shot Deadline." |
| 0:20–0:35 | Tab to the Grafana dashboard: days to lock, failure table, queue depth climbing | "Everything the farm, the vendors and the reviews report streams into Grafana Cloud as OpenTelemetry metrics and logs." |
| 0:35–1:35 | Back. Ask "Why is Sequence 040 late?" Tool cards: `list_datasources`, `query_prometheus` (show PromQL), `query_loki_logs` (show the RENDER FAILED line), `create_annotation` | "A Gemini agent triages through Grafana's MCP server. Status and days to lock. Where the work is stuck — queue depth, failures by node and error. Then the logs: oceanfx 3.2 missing on halcyon-gpu-07 through 12. Then reviews. And it writes what it found back as an annotation." |
| 1:35–2:00 | Triage findings; the named shots outline on the board | "Two causes, not one: Halcyon's ocean shots are dying on a broken node pool — and Northlight isn't blocked on the farm at all, it's waiting sixty hours on supervisor reviews. The in-house farm is at forty percent." |
| 2:00–2:25 | Planner output: replan + morning note | "The planner turns that into moves with quantities — re-route the ocean shots to the in-house farm, fix the plugin on the pool, a daily review block for Northlight — and the note the producer forwards." |
| 2:25–2:40 | Tab to Grafana: the annotation on the dashboard; ask "Open an incident…" and show `create_incident` | "The annotation is on the dashboard. Ask for an incident and it opens one." |
| 2:40–2:55 | Repo: `agent/pipeline.py` MCPToolset, `telemetry/sim.py` OTel exporter | "One ADK agent network on Cloud Run, the official mcp-grafana server, OpenTelemetry into Grafana Cloud." |
| 2:55–3:00 | Board | "Shot Deadline. Why is the sequence late — and what we're doing about it." |
