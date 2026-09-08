# Alert rules (create in Grafana Cloud → Alerting; the agent reads them via the MCP server)

| Name | Query | Condition | For |
|---|---|---|---|
| Sequence lock at risk | `count(vfx_shot_days_to_due < 0) by (sequence)` | > 2 | 10m |
| Render failure storm | `sum(increase(render_jobs_failed_total[15m])) by (vendor, node)` | > 5 | 5m |
| Review backlog | `review_turnaround_hours` | > 48 | 30m |
| Farm idle while queue grows | `avg(gpu_utilization_ratio) by (farm) < 0.5 and on() max(render_queue_depth) > 60` | true | 15m |
