"""Shot Deadline agent network (Google ADK + Gemini + the official Grafana MCP server).

    ShotDeadline (SequentialAgent)
      ├── triage    LlmAgent + MCPToolset(mcp-grafana)   queries Prometheus/Loki through Grafana, finds why a
      │                                                  sequence is late, records an annotation / incident
      └── planner   LlmAgent                             writes the replan and the supervisor's status note

All observability access goes through `mcp-grafana` (stdio). Only read/annotate/incident tools are enabled.
"""
from __future__ import annotations

import os

from google.adk.agents import LlmAgent, SequentialAgent
from google.adk.tools.mcp_tool import MCPToolset, StdioConnectionParams
from google.genai import types
from mcp import StdioServerParameters

TRIAGE_MODEL = os.environ.get("TRIAGE_MODEL", "gemini-2.5-pro")
PLANNER_MODEL = os.environ.get("PLANNER_MODEL", "gemini-2.5-pro")

TOOLS = [
    "list_datasources",
    "query_prometheus",
    "list_prometheus_label_values",
    "list_prometheus_metric_names",
    "query_loki_logs",
    "query_loki_patterns",
    "search_dashboards",
    "get_dashboard_summary",
    "create_annotation",
    "create_incident",
    "add_activity_to_incident",
    "list_incidents",
]


def grafana_toolset() -> MCPToolset:
    return MCPToolset(
        connection_params=StdioConnectionParams(
            server_params=StdioServerParameters(
                command=os.environ.get("MCP_GRAFANA_BIN", "mcp-grafana"),
                args=["-t", "stdio", "-disable-write"] if os.environ.get("GRAFANA_READ_ONLY") == "true" else ["-t", "stdio"],
                env={
                    "GRAFANA_URL": os.environ["GRAFANA_URL"],
                    "GRAFANA_SERVICE_ACCOUNT_TOKEN": os.environ["GRAFANA_SERVICE_ACCOUNT_TOKEN"],
                    "PATH": os.environ.get("PATH", ""),
                },
            ),
            timeout=60,
        ),
        tool_filter=TOOLS,
    )


TRIAGE_INSTRUCTION = """You are the VFX production coordinator's triage agent for the show IRONWAKE.
You answer questions like "why is Sequence 040 late" using Grafana Cloud through the tools —
`query_prometheus` for metrics and `query_loki_logs` for render logs. Never guess; every number
must come from a query you ran.

Start by calling `list_datasources` once to get the Prometheus and Loki datasource UIDs.

Metrics (Prometheus). All gauges unless noted. Labels in braces.
- vfx_shots{sequence,vendor,status}                 shots per status: not_started, in_progress,
                                                    render_failed, in_review, approved, final
- vfx_shot_days_to_due{sequence,shot,vendor,status} negative = late
- vfx_sequence_days_to_lock{sequence}
- render_queue_depth{farm,vendor}
- render_jobs_failed_total{vendor,farm,node,error}  counter — use rate()/increase() over 30m
- render_jobs_completed_total{vendor,farm}          counter
- gpu_utilization_ratio{farm,node}
- review_turnaround_hours{vendor}

Logs (Loki): service_name="ironwake-vfx-pipeline". Render failures are ERROR lines like
  RENDER FAILED shot=SEQ040_0070 node=halcyon-gpu-09 error="Plugin 'oceanfx' version 3.2 not found (installed: 3.1)"
with labels/attributes sequence, shot, vendor, farm, node, error.

Procedure for "why is sequence X late":
1. Status: vfx_shots for the sequence by vendor and status; vfx_sequence_days_to_lock; count of shots
   with vfx_shot_days_to_due < 0.
2. Where the work is stuck: render_queue_depth by farm; increase(render_jobs_failed_total[30m]) by
   vendor, node, error; gpu_utilization_ratio by farm (is any farm idle?).
3. Evidence: query_loki_logs for the failing shots in the last hour, take the most common error text.
4. Reviews: review_turnaround_hours by vendor — is a vendor blocked on the supervisor rather than the farm?
5. Distinguish the causes: farm/pipeline fault (a plugin, a node pool, a driver), vendor capacity,
   review bottleneck. There may be more than one.
6. Record it: create_annotation on the dashboard tagged with the sequence and cause
   (text like "Triage: SEQ040 ocean shots failing on halcyon-gpu-07..12, oceanfx 3.2 missing").
   If the user asks to open an incident, or the cause is a pipeline fault blocking a lock date,
   also call create_incident with a clear title and severity. If incident tools error (IRM not
   enabled on this stack), say so and continue.

Keep to at most 10 tool calls. Then write findings as compact markdown:
- One-sentence answer with the numbers (shots late, days to lock, failed shots, queue depth).
- Causes, each with the evidence (metric values, log line, which nodes/vendor).
- What is healthy (spare capacity, vendors on track).
- Which annotation / incident you created, with ids if returned.
- A `Data` section listing every PromQL / LogQL you ran, verbatim.
"""

PLANNER_INSTRUCTION = """You are the VFX supervisor's production planner on IRONWAKE. Below are the
triage findings. Write two things, plain prose, 200-280 words total:

1. The replan. Concrete moves that hit the lock date: which shots to move to which farm or vendor,
   what to fix on the pipeline (name the plugin/nodes), whether to re-route the water-sim pool,
   what to escalate about reviews (e.g. daily review block with the supervisor for the vendor
   whose turnaround is high). Give quantities: "move the 8 render_failed SEQ040 ocean shots to
   ironwake-farm, which is at 42% utilisation". Order by impact on the lock date.

2. The morning status note to the producer: four or five sentences a producer can forward —
   where the sequence stands, the root cause, what is being done, the risk to the lock date.

No headings, no bullet points, no SQL/PromQL. Do not invent numbers not in the findings.

Triage findings:
{findings}
"""


def build_pipeline() -> SequentialAgent:
    triage = LlmAgent(
        name="triage",
        model=TRIAGE_MODEL,
        description="Finds why a VFX sequence is late using Grafana metrics and logs; annotates and opens incidents.",
        # provider form: ADK must not treat the literal PromQL braces ({sequence,...}) as state templates
        instruction=lambda _ctx: TRIAGE_INSTRUCTION,
        tools=[grafana_toolset()],
        output_key="findings",
        generate_content_config=types.GenerateContentConfig(temperature=0.1),
    )
    planner = LlmAgent(
        name="planner",
        model=PLANNER_MODEL,
        description="Writes the replan and the status note.",
        instruction=PLANNER_INSTRUCTION,
        include_contents="none",
        output_key="plan",
        generate_content_config=types.GenerateContentConfig(temperature=0.4),
    )
    return SequentialAgent(name="ShotDeadline", sub_agents=[triage, planner])
