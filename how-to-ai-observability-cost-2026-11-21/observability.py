"""Production AI observability and cost tracking, standard library only.
Collects one telemetry event per LLM call, prices it from a table,
aggregates by model, feature and user, and checks budget alerts.
"""
from dataclasses import dataclass, field
from collections import defaultdict

# USD per 1 million tokens: (input price, output price)
PRICES = {
    "gpt-5-mini": (0.25, 2.00),
    "gpt-5": (1.25, 10.00),
    "claude-sonnet": (3.00, 15.00),
    "claude-haiku": (1.00, 5.00),
    "gemini-flash": (0.30, 2.50),
    "local-small": (0.0, 0.0),
}

@dataclass
class TelemetryEvent:
    request_id: str
    timestamp: str
    model: str
    feature: str
    user_id: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    status: str = "ok"
    cached: bool = False

    @property
    def total_tokens(self):
        return self.input_tokens + self.output_tokens

def cost_usd(event):
    if event.model not in PRICES:
        raise ValueError(f"unknown model {event.model}")
    if event.cached:
        return 0.0
    inp, outp = PRICES[event.model]
    return (event.input_tokens * inp + event.output_tokens * outp) / 1_000_000

@dataclass
class Collector:
    events: list = field(default_factory=list)

    def record(self, event):
        if event.input_tokens < 0 or event.output_tokens < 0:
            raise ValueError("token counts cannot be negative")
        if event.latency_ms < 0:
            raise ValueError("latency cannot be negative")
        cost_usd(event)
        self.events.append(event)
        return event

    def total_cost(self):
        return round(sum(cost_usd(e) for e in self.events), 6)

    def aggregate(self, key):
        groups = defaultdict(lambda: {"calls": 0, "tokens": 0, "cost": 0.0, "errors": 0, "latency": 0})
        for e in self.events:
            name = getattr(e, key)
            g = groups[name]
            g["calls"] += 1
            g["tokens"] += e.total_tokens
            g["cost"] = round(g["cost"] + cost_usd(e), 6)
            g["latency"] += e.latency_ms
            if e.status != "ok":
                g["errors"] += 1
        for g in groups.values():
            g["avg_latency_ms"] = round(g["latency"] / g["calls"], 1) if g["calls"] else 0
            del g["latency"]
        return dict(groups)

    def error_rate(self):
        if not self.events:
            return 0.0
        errors = sum(1 for e in self.events if e.status != "ok")
        return round(errors / len(self.events), 4)

    def p95_latency_ms(self):
        if not self.events:
            return 0
        values = sorted(e.latency_ms for e in self.events)
        idx = max(0, int(0.95 * len(values)) - 1)
        return values[idx]

def check_budgets(collector, budgets):
    """budgets: dict of feature name to monthly USD limit.
    Returns a list of alert dicts for features at or over 80 percent."""
    alerts = []
    by_feature = collector.aggregate("feature")
    for feature, limit in budgets.items():
        spent = by_feature.get(feature, {}).get("cost", 0.0)
        pct = (spent / limit * 100) if limit else 0.0
        level = "over" if pct >= 100 else "warn" if pct >= 80 else "ok"
        alerts.append({"feature": feature, "spent_usd": round(spent, 4),
                       "budget_usd": limit, "percent": round(pct, 1), "level": level})
    return alerts

SAMPLE_EVENTS = [
    TelemetryEvent("r1", "2026-11-21T09:00:00Z", "gpt-5-mini", "receipt_extract", "u1", 1200, 300, 820),
    TelemetryEvent("r2", "2026-11-21T09:01:00Z", "gpt-5-mini", "receipt_extract", "u2", 1400, 320, 910),
    TelemetryEvent("r3", "2026-11-21T09:02:00Z", "claude-sonnet", "support_chat", "u1", 2500, 900, 2100),
    TelemetryEvent("r4", "2026-11-21T09:03:00Z", "claude-haiku", "support_chat", "u3", 900, 400, 640),
    TelemetryEvent("r5", "2026-11-21T09:04:00Z", "gpt-5", "doc_summary", "u2", 4000, 1500, 3400, status="error"),
    TelemetryEvent("r6", "2026-11-21T09:05:00Z", "gemini-flash", "doc_summary", "u4", 3000, 800, 1250),
    TelemetryEvent("r7", "2026-11-21T09:06:00Z", "gpt-5-mini", "receipt_extract", "u1", 1100, 280, 780, cached=True),
    TelemetryEvent("r8", "2026-11-21T09:07:00Z", "claude-sonnet", "support_chat", "u5", 2800, 1100, 2300),
]

if __name__ == "__main__":
    c = Collector()
    for e in SAMPLE_EVENTS:
        c.record(e)
    print("Total cost USD:", c.total_cost())
    print("By model:", c.aggregate("model"))
