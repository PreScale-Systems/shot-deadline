"""IRONWAKE — a VFX show in its last weeks, simulated, and emitted to Grafana Cloud over OTLP.

The simulation advances one production hour per tick (TICK_SECONDS real seconds). It keeps a
shot board in memory for the UI and emits:

  metrics (Prometheus via the Grafana Cloud OTLP gateway)
    vfx_shots{sequence,vendor,status}                 shots in each status
    vfx_shot_days_to_due{sequence,shot,vendor}         per-shot slack (negative = late)
    vfx_sequence_days_to_lock{sequence}                days until picture lock for the sequence
    render_queue_depth{farm,vendor}                    jobs waiting
    render_jobs_completed_total{vendor,farm}           counter
    render_jobs_failed_total{vendor,farm,node,error}   counter
    gpu_utilization_ratio{farm,node}                   0..1
    review_turnaround_hours{vendor}                    supervisor review latency
  logs (Loki)
    render failures with shot / node / error, review events, vendor deliveries

The story the agent should find: Sequence 040 is slipping because Halcyon's ocean shots fail on
GPU nodes 07–12 after a driver update removed oceanfx 3.2; Northlight's shots are fine but their
review turnaround has crept to 60h; the in-house farm is half idle.
"""
from __future__ import annotations

import asyncio
import logging
import os
import random
import time
from dataclasses import dataclass, field
from typing import Dict, List

SHOW = "IRONWAKE"
LOCK_IN_DAYS = {"SEQ010": 16, "SEQ040": 9, "SEQ070": 12, "SEQ120": 21}
SEQ_NAMES = {"SEQ010": "Arrival at the rig", "SEQ040": "The storm", "SEQ070": "Deck collapse", "SEQ120": "Finale — flooding"}
VENDORS = ["Halcyon VFX", "Northlight", "Ironwake In-house"]
FARMS = {"Halcyon VFX": "halcyon-farm", "Northlight": "northlight-farm", "Ironwake In-house": "ironwake-farm"}
NODES = {f: [f"{f.split('-')[0]}-gpu-{i:02d}" for i in range(1, 13)] for f in FARMS.values()}
STATUSES = ["not_started", "in_progress", "render_failed", "in_review", "approved", "final"]
OCEANFX_ERROR = "Plugin 'oceanfx' version 3.2 not found (installed: 3.1)"


@dataclass
class Shot:
    sequence: str
    shot: str
    vendor: str
    status: str
    complexity: int          # 1..5
    days_to_due: float
    ocean: bool = False      # needs the oceanfx plugin
    renders_left: int = 3
    review_hours_left: float = 0.0
    fails: int = 0


@dataclass
class World:
    hour: int = 0
    shots: List[Shot] = field(default_factory=list)
    queue: Dict[str, int] = field(default_factory=dict)
    completed: Dict[str, int] = field(default_factory=dict)
    failed: Dict[tuple, int] = field(default_factory=dict)
    gpu: Dict[str, float] = field(default_factory=dict)
    review_turnaround: Dict[str, float] = field(default_factory=lambda: {"Halcyon VFX": 18.0, "Northlight": 44.0, "Ironwake In-house": 12.0})
    events: List[dict] = field(default_factory=list)  # recent log lines for the UI

    def board(self) -> dict:
        seqs = {}
        for s in self.shots:
            d = seqs.setdefault(s.sequence, {"sequence": s.sequence, "name": SEQ_NAMES[s.sequence], "days_to_lock": LOCK_IN_DAYS[s.sequence] - self.hour / 24, "shots": []})
            d["shots"].append(dict(shot=s.shot, vendor=s.vendor, status=s.status, days_to_due=round(s.days_to_due, 1), ocean=s.ocean, fails=s.fails, complexity=s.complexity))
        return {
            "show": SHOW,
            "hour": self.hour,
            "sequences": sorted(seqs.values(), key=lambda x: x["sequence"]),
            "queue": self.queue,
            "review_turnaround": self.review_turnaround,
            "gpu": self.gpu,
            "events": self.events[-40:],
        }


def build_world(seed: int = 11) -> World:
    rng = random.Random(seed)
    w = World()
    plan = {"SEQ010": 14, "SEQ040": 22, "SEQ070": 16, "SEQ120": 18}
    for seq, n in plan.items():
        for i in range(1, n + 1):
            shot = f"{seq}_{i*10:04d}"
            if seq == "SEQ040":
                vendor = "Halcyon VFX" if i <= 14 else "Northlight"
            elif seq == "SEQ120":
                vendor = rng.choice(["Halcyon VFX", "Northlight"])
            else:
                vendor = rng.choice(VENDORS)
            ocean = seq in ("SEQ040", "SEQ120") and vendor == "Halcyon VFX" and rng.random() < 0.8
            status = rng.choices(STATUSES, weights=[1, 4, 0, 2, 2, 1])[0] if seq != "SEQ040" else rng.choices(["in_progress", "in_review", "approved"], weights=[6, 2, 1])[0]
            due = LOCK_IN_DAYS[seq] - rng.uniform(2, 6)
            w.shots.append(Shot(seq, shot, vendor, status, rng.randint(1, 5), due, ocean, renders_left=rng.randint(1, 4)))
    for f in FARMS.values():
        w.queue[f] = rng.randint(4, 30)
        w.completed[f] = 0
        for n in NODES[f]:
            w.gpu[n] = rng.uniform(0.5, 0.95)
    return w


def step(w: World, rng: random.Random) -> List[dict]:
    """Advance one production hour. Returns log records emitted this hour."""
    w.hour += 1
    logs: List[dict] = []
    # nodes 07-12 on halcyon-farm lost oceanfx 3.2 after a driver update at hour 0
    broken = set(NODES["halcyon-farm"][6:])

    for s in w.shots:
        s.days_to_due -= 1 / 24
        farm = FARMS[s.vendor]
        if s.status == "not_started" and rng.random() < 0.04:
            s.status = "in_progress"
        elif s.status in ("in_progress", "render_failed") and rng.random() < 0.10:
            # ocean shots are pinned to the water-sim pool (nodes 07-12) on halcyon-farm
            pool = NODES[farm][6:] if (s.ocean and farm == "halcyon-farm" and rng.random() < 0.9) else NODES[farm]
            node = rng.choice(pool)
            if s.ocean and node in broken:
                s.status = "render_failed"; s.fails += 1
                w.failed[(s.vendor, farm, node, OCEANFX_ERROR)] = w.failed.get((s.vendor, farm, node, OCEANFX_ERROR), 0) + 1
                w.queue[farm] += 1
                logs.append(dict(level="ERROR", body=f"RENDER FAILED shot={s.shot} node={node} error=\"{OCEANFX_ERROR}\"", sequence=s.sequence, shot=s.shot, vendor=s.vendor, farm=farm, node=node, error="oceanfx_missing"))
            elif rng.random() < 0.03:
                err = rng.choice(["Out of GPU memory at frame 1042", "Texture cache read timeout", "License checkout failed: nuke_r"])
                s.status = "render_failed"; s.fails += 1
                w.failed[(s.vendor, farm, node, err)] = w.failed.get((s.vendor, farm, node, err), 0) + 1
                logs.append(dict(level="ERROR", body=f"RENDER FAILED shot={s.shot} node={node} error=\"{err}\"", sequence=s.sequence, shot=s.shot, vendor=s.vendor, farm=farm, node=node, error="other"))
            else:
                s.renders_left -= 1
                w.completed[farm] += 1
                w.queue[farm] = max(0, w.queue[farm] - 1)
                if s.renders_left <= 0:
                    s.status = "in_review"; s.review_hours_left = w.review_turnaround[s.vendor] * rng.uniform(0.7, 1.3)
                    logs.append(dict(level="INFO", body=f"DELIVERED shot={s.shot} vendor=\"{s.vendor}\" version=v{rng.randint(3,9)} for supervisor review", sequence=s.sequence, shot=s.shot, vendor=s.vendor, farm=farm, node="", error=""))
                else:
                    s.status = "in_progress"
        elif s.status == "in_review":
            s.review_hours_left -= 1
            if s.review_hours_left <= 0:
                if rng.random() < 0.7:
                    s.status = "approved"
                    logs.append(dict(level="INFO", body=f"APPROVED shot={s.shot} by VFX supervisor", sequence=s.sequence, shot=s.shot, vendor=s.vendor, farm=farm, node="", error=""))
                else:
                    s.status = "in_progress"; s.renders_left = 1
                    logs.append(dict(level="WARN", body=f"NOTES shot={s.shot}: kicked back with notes (spray density, horizon line)", sequence=s.sequence, shot=s.shot, vendor=s.vendor, farm=farm, node="", error=""))
        elif s.status == "approved" and rng.random() < 0.03:
            s.status = "final"

    # queues and gpu
    for f in FARMS.values():
        w.queue[f] = max(0, w.queue[f] + rng.randint(-2, 2))
    w.queue["halcyon-farm"] += 1  # the failing ocean shots pile up
    for n, u in w.gpu.items():
        base = 0.9 if n.startswith("halcyon") else (0.75 if n.startswith("northlight") else 0.42)
        w.gpu[n] = min(0.99, max(0.05, base + rng.uniform(-0.12, 0.12)))
    # review turnaround: Northlight creeps up
    w.review_turnaround["Northlight"] = min(72.0, w.review_turnaround["Northlight"] + 0.25)
    for r in logs:
        r["hour"] = w.hour
    w.events.extend(logs)
    w.events = w.events[-200:]
    return logs


# ----------------------------------------------------------------------------- OpenTelemetry


class Emitter:
    """Observable-gauge metrics + counters + logs through the OTLP HTTP exporter."""

    def __init__(self, world: World):
        self.w = world
        self.enabled = bool(os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"))
        if not self.enabled:
            logging.getLogger("shot-deadline").warning("OTEL_EXPORTER_OTLP_ENDPOINT not set: simulation runs, nothing is exported")
            return
        from opentelemetry import metrics
        from opentelemetry._logs import set_logger_provider
        from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
        from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
        from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
        from opentelemetry.sdk.resources import Resource

        res = Resource.create({"service.name": "ironwake-vfx-pipeline", "service.namespace": "shot-deadline", "deployment.environment": "production"})
        reader = PeriodicExportingMetricReader(OTLPMetricExporter(), export_interval_millis=int(float(os.environ.get("TICK_SECONDS", "10")) * 1000))
        metrics.set_meter_provider(MeterProvider(resource=res, metric_readers=[reader]))
        m = metrics.get_meter("shot-deadline")

        m.create_observable_gauge("vfx_shots", callbacks=[self._shots], description="Shots by status")
        m.create_observable_gauge("vfx_shot_days_to_due", callbacks=[self._due], description="Days until each shot's delivery date (negative = late)")
        m.create_observable_gauge("vfx_sequence_days_to_lock", callbacks=[self._lock], description="Days until picture lock")
        m.create_observable_gauge("render_queue_depth", callbacks=[self._queue], description="Render jobs waiting")
        m.create_observable_gauge("gpu_utilization_ratio", callbacks=[self._gpu], description="GPU utilisation 0..1")
        m.create_observable_gauge("review_turnaround_hours", callbacks=[self._review], description="Supervisor review latency")
        self.c_done = m.create_counter("render_jobs_completed_total", description="Completed renders")
        self.c_fail = m.create_counter("render_jobs_failed_total", description="Failed renders")

        lp = LoggerProvider(resource=res)
        lp.add_log_record_processor(BatchLogRecordProcessor(OTLPLogExporter()))
        set_logger_provider(lp)
        self.log = logging.getLogger("ironwake.render")
        self.log.setLevel(logging.INFO)
        self.log.addHandler(LoggingHandler(level=logging.INFO, logger_provider=lp))
        self.log.propagate = False

    # observable callbacks
    def _shots(self, options):
        from opentelemetry.metrics import Observation
        counts = {}
        for s in self.w.shots:
            counts[(s.sequence, s.vendor, s.status)] = counts.get((s.sequence, s.vendor, s.status), 0) + 1
        return [Observation(v, {"sequence": k[0], "vendor": k[1], "status": k[2]}) for k, v in counts.items()]

    def _due(self, options):
        from opentelemetry.metrics import Observation
        return [Observation(round(s.days_to_due, 2), {"sequence": s.sequence, "shot": s.shot, "vendor": s.vendor, "status": s.status}) for s in self.w.shots]

    def _lock(self, options):
        from opentelemetry.metrics import Observation
        return [Observation(round(d - self.w.hour / 24, 2), {"sequence": seq}) for seq, d in LOCK_IN_DAYS.items()]

    def _queue(self, options):
        from opentelemetry.metrics import Observation
        inv = {v: k for k, v in FARMS.items()}
        return [Observation(v, {"farm": f, "vendor": inv[f]}) for f, v in self.w.queue.items()]

    def _gpu(self, options):
        from opentelemetry.metrics import Observation
        return [Observation(round(u, 3), {"farm": n.rsplit("-gpu-", 1)[0] + "-farm", "node": n}) for n, u in self.w.gpu.items()]

    def _review(self, options):
        from opentelemetry.metrics import Observation
        return [Observation(round(h, 1), {"vendor": v}) for v, h in self.w.review_turnaround.items()]

    def emit_step(self, logs: List[dict], completed_delta: Dict[str, int], failed_delta: Dict[tuple, int]):
        if not self.enabled:
            return
        inv = {v: k for k, v in FARMS.items()}
        for farm, n in completed_delta.items():
            if n:
                self.c_done.add(n, {"vendor": inv[farm], "farm": farm})
        for (vendor, farm, node, err), n in failed_delta.items():
            if n:
                self.c_fail.add(n, {"vendor": vendor, "farm": farm, "node": node, "error": err})
        for r in logs:
            level = {"ERROR": logging.ERROR, "WARN": logging.WARNING}.get(r["level"], logging.INFO)
            self.log.log(level, r["body"], extra={k: v for k, v in r.items() if k not in ("body", "level")})


async def run_simulation(world: World, stop: asyncio.Event, seed: int = 3):
    rng = random.Random(seed)
    em = Emitter(world)
    tick = float(os.environ.get("TICK_SECONDS", "10"))
    while not stop.is_set():
        before_c = dict(world.completed)
        before_f = dict(world.failed)
        logs = step(world, rng)
        em.emit_step(
            logs,
            {f: world.completed[f] - before_c.get(f, 0) for f in world.completed},
            {k: world.failed[k] - before_f.get(k, 0) for k in world.failed},
        )
        try:
            await asyncio.wait_for(stop.wait(), timeout=tick)
        except asyncio.TimeoutError:
            pass


if __name__ == "__main__":  # quick dry run
    w = build_world()
    rng = random.Random(3)
    for _ in range(72):
        step(w, rng)
    b = w.board()
    for sq in b["sequences"]:
        from collections import Counter
        print(sq["sequence"], f"lock in {sq['days_to_lock']:.1f}d", Counter(s["status"] for s in sq["shots"]))
    print("queue", b["queue"], "review", {k: round(v) for k, v in b["review_turnaround"].items()})
    print("failures by error:", Counter(k[3] for k in w.failed for _ in range(w.failed[k])))
    print(w.events[-2])
