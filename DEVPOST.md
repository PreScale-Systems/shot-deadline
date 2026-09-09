# Devpost submission — Shot Deadline (Grafana Labs track)

## Inspiration
Every VFX show ends the same way: a supervisor with hundreds of shots, three vendors, a lock date, and a sequence that is suddenly late. Finding out why means opening the farm dashboard, the render logs, the review tracker and the vendor emails. We wanted one question — "why is Sequence 040 late" — answered from the telemetry, with the evidence shown and the fix written down.

## What it does
Shot Deadline is a live VFX war room. The render farm, review pipeline and vendor deliveries for a fictional feature, *IRONWAKE*, stream into Grafana Cloud as OpenTelemetry metrics and logs. A Gemini triage agent, connected to Grafana through the official Grafana MCP server, follows a fixed procedure: sequence status and days to lock, where the work is stuck (queues, failed renders by node and error, idle farms), the log evidence, review latency by vendor — then distinguishes a pipeline fault from vendor capacity from a review bottleneck, records it as a dashboard annotation or opens an incident. A planner agent turns the findings into a replan with quantities and the producer's morning note.

## How we built it
- Google ADK `SequentialAgent`: triage `LlmAgent` (Gemini 2.5 Pro) with an `MCPToolset` over stdio to `mcp-grafana` v1.3.0 (`query_prometheus`, `query_loki_logs`, `create_annotation`, `create_incident`, …), and a planner `LlmAgent`. Tool calls stream to the UI as server-sent events.
- OpenTelemetry SDK exporting observable gauges, counters and structured logs through the Grafana Cloud OTLP gateway into Mimir and Loki: shots by status, per-shot slack, days to lock, queue depth, failures by node/error, GPU utilisation, review turnaround.
- A time-compressed production simulation with two overlapping causes: Halcyon's ocean shots failing on the water-sim node pool after a driver update removed `oceanfx 3.2`, and Northlight's review turnaround creeping past 60 hours, while the in-house farm sits half idle.
- A provisioned dashboard (days to lock, shots past due, failure table, queues, GPU, reviews, render log) that receives the agent's annotations; FastAPI on Cloud Run with Gemini via Vertex AI.

## Challenges
Getting the agent to separate causes rather than pick the first one — the ordered procedure with an explicit "farm fault vs vendor capacity vs review bottleneck" step fixed it. Keeping a simulation emitting on Cloud Run between requests (min instances + no CPU throttling). Making the telemetry answerable: rich labels on gauges so any coordinator question is one PromQL query.

## What we learned
An agent that writes back — an annotation, an incident — changes the workflow from "ask a question" to "keep a record". The MCP server's annotation and incident tools made that a single call.

## What's next
Real ingestion from farm managers (Deadline, OpenCue) and review tools (ShotGrid), alert-triggered triage that posts the note before the coordinator asks, and per-vendor SLA reports.

## Built with
google-adk, google-genai, Gemini 2.5 Pro, Vertex AI, Cloud Run, Secret Manager, Grafana Cloud (Mimir, Loki, annotations, IRM), mcp-grafana, OpenTelemetry, FastAPI

## Links
- Hosted app: <CLOUD RUN URL>
- Repo: https://github.com/PreScale-Systems/shot-deadline
- Video: <YOUTUBE URL>
