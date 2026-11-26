"""Production AI incident response and on-call triage system.

Receives alerts from model and platform monitoring, classifies severity,
assigns the on-call owner, escalates on timers, opens an incident record,
and drafts the postmortem timeline. Standard library only.
Run: python3 incident_response.py
"""
from __future__ import annotations
import time
from dataclasses import dataclass, field

SEVERITY = {
    "SEV1": {"ack_min": 5, "escalate_min": 15, "channel": "page"},
    "SEV2": {"ack_min": 15, "escalate_min": 30, "channel": "page"},
    "SEV3": {"ack_min": 60, "escalate_min": 240, "channel": "slack"},
    "SEV4": {"ack_min": 480, "escalate_min": 1440, "channel": "ticket"},
}

def classify(alert):
    """Map an alert signal to a severity from impact and scope."""
    if alert.get("user_facing") and alert.get("error_rate", 0) >= 0.25:
        return "SEV1"
    if alert.get("user_facing") and alert.get("error_rate", 0) >= 0.05:
        return "SEV2"
    if alert.get("model_quality_drop", 0) >= 0.10 or alert.get("cost_spike_x", 1) >= 3:
        return "SEV3"
    return "SEV4"

@dataclass
class Incident:
    id: str
    title: str
    severity: str
    owner: str
    created: float
    timeline: list = field(default_factory=list)
    acked: bool = False
    resolved: bool = False
    def log(self, ts, msg):
        self.timeline.append((ts, msg))

class OnCall:
    def __init__(self, rotation):
        self.rotation = rotation  # list of names, primary first
    def primary(self):
        return self.rotation[0]
    def escalate(self, incident):
        if len(self.rotation) > 1:
            self.rotation = self.rotation[1:] + self.rotation[:1]
        incident.owner = self.rotation[0]
        return incident.owner

class IncidentManager:
    def __init__(self, oncall):
        self.oncall = oncall
        self.incidents = {}
        self.counter = 0
    def open(self, alert, now=None):
        now = now or time.time()
        self.counter += 1
        sev = classify(alert)
        inc = Incident(f"INC-{self.counter:04d}", alert["title"], sev, self.oncall.primary(), now)
        inc.log(now, f"Opened as {sev} via {SEVERITY[sev]['channel']}, owner {inc.owner}")
        self.incidents[inc.id] = inc
        return inc
    def ack(self, inc, now=None):
        inc.acked = True
        inc.log(now or time.time(), f"Acknowledged by {inc.owner}")
    def check_escalations(self, now):
        out = []
        for inc in self.incidents.values():
            if inc.resolved or inc.acked:
                continue
            limit = SEVERITY[inc.severity]["escalate_min"] * 60
            if now - inc.created > limit:
                new_owner = self.oncall.escalate(inc)
                inc.log(now, f"No ack in time, escalated to {new_owner}")
                out.append(inc)
        return out
    def resolve(self, inc, now=None):
        inc.resolved = True
        inc.log(now or time.time(), "Resolved")
    def postmortem(self, inc):
        lines = [f"# Postmortem {inc.id}: {inc.title}", f"Severity: {inc.severity}", f"Owner: {inc.owner}", "", "## Timeline"]
        for ts, msg in inc.timeline:
            lines.append(f"- {time.strftime('%H:%M', time.gmtime(ts))} {msg}")
        lines += ["", "## Follow ups", "- Add an alert for the first failing signal.", "- Add a runbook link to the alert payload."]
        return "\n".join(lines)

def demo():
    base = 1700000000.0
    mgr = IncidentManager(OnCall(["alice", "bruno", "carla"]))
    a = mgr.open({"title": "Checkout model error rate 32 percent", "user_facing": True, "error_rate": 0.32}, now=base)
    b = mgr.open({"title": "Nightly eval quality drop 12 percent", "model_quality_drop": 0.12}, now=base)
    c = mgr.open({"title": "Token cost spike 1.4x on one route", "cost_spike_x": 1.4}, now=base)
    print(a.id, a.severity, a.owner)
    print(b.id, b.severity, b.owner)
    print(c.id, c.severity, c.owner)
    assert (a.severity, b.severity, c.severity) == ("SEV1", "SEV3", "SEV4")
    esc = mgr.check_escalations(base + 16 * 60)
    print("escalated:", [i.id for i in esc])
    assert [i.id for i in esc] == [a.id]
    mgr.ack(a, now=base + 17 * 60)
    mgr.resolve(a, now=base + 55 * 60)
    print(mgr.postmortem(a))
    print("OK: severity, escalation and postmortem flow verified")

if __name__ == "__main__":
    demo()
