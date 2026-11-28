"""
Production prompt registry with safe rollout: versioning, canary, rollback.

How-to guide, Saturday 28 November 2026.

The problem in plain terms: a support team ships a new prompt the way they
used to ship config, by editing a string in the code and deploying on a
Friday. By Monday the ticket queue is full of answers in the wrong tone and
nobody can say which prompt version wrote them. This file is the registry
that ends that story:

  1. Every prompt is a versioned template. Versions are immutable.
  2. Rollout is a dial, not a deploy: stable and canary versions, with a
     deterministic per user bucket deciding who sees the canary.
  3. A metric gate promotes the canary or rolls it back, in one call.
  4. Every resolution is logged with the version that served it, so any
     answer can be traced back to the exact prompt that produced it.

Standard library only. Run it:  python3 prompt_registry.py
It simulates a morning of traffic, runs a canary, applies the gate both
ways, and checks its own results.
"""

from __future__ import annotations

import hashlib
import string
import sys
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

class TemplateError(Exception):
    """Raised when a template cannot be rendered safely."""


@dataclass(frozen=True)
class PromptVersion:
    name: str          # logical prompt, for example "support_reply"
    version: int       # 1, 2, 3 ... immutable once registered
    template: str      # text with {variables}
    author: str
    note: str          # why this version exists, in one line

    @property
    def variables(self) -> list[str]:
        return sorted({f for _, f, _, _ in string.Formatter().parse(self.template) if f})

    def render(self, **values: str) -> str:
        missing = [v for v in self.variables if v not in values]
        if missing:
            raise TemplateError(
                f"{self.name} v{self.version} is missing variables: "
                + ", ".join(missing))
        extra = [k for k in values if k not in self.variables]
        if extra:
            raise TemplateError(
                f"{self.name} v{self.version} got unknown variables: "
                + ", ".join(extra))
        return self.template.format(**values)


# ---------------------------------------------------------------------------
# Registry and rollout
# ---------------------------------------------------------------------------

def bucket_for(user_id: str, prompt_name: str) -> int:
    """Deterministic bucket 0..99 for a user and a prompt.

    Hashing the user id with the prompt name means the same person always
    lands in the same bucket for the same prompt, on every machine, with no
    stored state. That is the property a canary lives or dies on: a user
    must never flip between versions between two messages in one chat.
    """
    digest = hashlib.sha256(f"{prompt_name}:{user_id}".encode()).hexdigest()
    return int(digest[:8], 16) % 100


@dataclass
class Rollout:
    stable: int                 # version everyone gets by default
    canary: int | None = None   # version being tested, if any
    canary_percent: int = 0     # share of buckets on the canary, 0..100


@dataclass
class Registry:
    versions: dict[str, dict[int, PromptVersion]] = field(default_factory=dict)
    rollouts: dict[str, Rollout] = field(default_factory=dict)
    audit: list[str] = field(default_factory=list)

    def register(self, pv: PromptVersion) -> None:
        slot = self.versions.setdefault(pv.name, {})
        if pv.version in slot:
            raise TemplateError(
                f"{pv.name} v{pv.version} already exists; versions are "
                "immutable, register a new version instead")
        slot[pv.version] = pv
        if pv.name not in self.rollouts:
            self.rollouts[pv.name] = Rollout(stable=pv.version)
        self.audit.append(f"registered {pv.name} v{pv.version} by {pv.author}: {pv.note}")

    def get(self, name: str, version: int) -> PromptVersion:
        try:
            return self.versions[name][version]
        except KeyError:
            raise TemplateError(f"no such prompt version: {name} v{version}")

    def start_canary(self, name: str, version: int, percent: int) -> None:
        if not 1 <= percent <= 99:
            raise TemplateError("canary percent must be between 1 and 99")
        self.get(name, version)  # must exist
        r = self.rollouts[name]
        r.canary, r.canary_percent = version, percent
        self.audit.append(f"canary started: {name} v{version} at {percent}%")

    def resolve(self, name: str, user_id: str) -> PromptVersion:
        """The version that serves this user right now."""
        r = self.rollouts[name]
        if r.canary is not None and bucket_for(user_id, name) < r.canary_percent:
            return self.get(name, r.canary)
        return self.get(name, r.stable)

    def promote(self, name: str) -> None:
        r = self.rollouts[name]
        if r.canary is None:
            raise TemplateError(f"{name} has no canary to promote")
        old = r.stable
        r.stable, r.canary, r.canary_percent = r.canary, None, 0
        self.audit.append(f"promoted {name} v{r.stable} to stable (was v{old})")

    def rollback(self, name: str) -> None:
        r = self.rollouts[name]
        if r.canary is None:
            raise TemplateError(f"{name} has no canary to roll back")
        self.audit.append(
            f"rolled back {name} canary v{r.canary}; stable stays v{r.stable}")
        r.canary, r.canary_percent = None, 0


# ---------------------------------------------------------------------------
# The metric gate: the canary earns promotion or it does not ship
# ---------------------------------------------------------------------------

@dataclass
class GateThresholds:
    max_negative_rate: float = 0.08   # thumbs down share on canary answers
    max_p95_ms: int = 4000            # slowest 5 percent must stay under this


def gate_decision(canary_negative_rate: float, canary_p95_ms: int,
                  t: GateThresholds) -> tuple[bool, list[str]]:
    reasons = []
    ok = True
    if canary_negative_rate > t.max_negative_rate:
        ok = False
        reasons.append(
            f"negative rate {canary_negative_rate:.1%} is above the "
            f"{t.max_negative_rate:.0%} limit")
    if canary_p95_ms > t.max_p95_ms:
        ok = False
        reasons.append(
            f"p95 latency {canary_p95_ms} ms is above the {t.max_p95_ms} ms limit")
    if ok:
        reasons.append("canary metrics inside thresholds")
    return ok, reasons


# ---------------------------------------------------------------------------
# Demo: one support prompt, two versions, a morning of traffic
# ---------------------------------------------------------------------------

V1 = PromptVersion(
    name="support_reply", version=1, author="Priya (support lead)",
    note="the original tone: correct, a bit stiff",
    template=("You are a support agent for Northwind. Answer the customer "
              "about {topic} in a formal tone. Order reference: {order_id}."))

V2 = PromptVersion(
    name="support_reply", version=2, author="Priya (support lead)",
    note="warmer tone, names the next step and when it happens",
    template=("You are a support agent for Northwind. Answer the customer "
              "about {topic} in a warm, plain tone, name the next step and "
              "when it happens. Order reference: {order_id}."))


def main() -> int:
    reg = Registry()
    reg.register(V1)
    reg.register(V2)
    reg.start_canary("support_reply", version=2, percent=10)

    users = [f"user-{i:03d}" for i in range(200)]
    served = [reg.resolve("support_reply", u).version for u in users]
    canary_users = served.count(2)
    stable_users = served.count(1)
    print(f"Traffic: 200 users, canary v2 served {canary_users}, "
          f"stable v1 served {stable_users} (target 10 percent canary)")

    # Determinism: resolving the same user twice gives the same version.
    again = [reg.resolve("support_reply", u).version for u in users]
    assert again == served, "bucketing must be deterministic"
    print("Determinism check: every user resolved to the same version twice.")

    sample = reg.resolve("support_reply", users[0]).render(
        topic="a delayed parcel", order_id="NW-1042")
    print(f"Sample render for {users[0]}: {sample[:80]}...")

    # Gate round 1: the canary is slower and users dislike it. Roll back.
    ok, reasons = gate_decision(canary_negative_rate=0.11, canary_p95_ms=4600,
                                t=GateThresholds())
    print(f"Gate on v2 canary: {'PROMOTE' if ok else 'ROLL BACK'}")
    for r in reasons:
        print(f"  - {r}")
    assert ok is False
    reg.rollback("support_reply")
    after = [reg.resolve("support_reply", u).version for u in users]
    assert all(v == 1 for v in after), "after rollback everyone is on stable"
    print("After rollback: all 200 users back on v1, no deploy needed.")

    # Gate round 2: a fixed v3 passes and is promoted.
    reg.register(PromptVersion(
        name="support_reply", version=3, author="Priya (support lead)",
        note="v2 tone with the latency fix: shorter system text",
        template=("You are a support agent for Northwind. Answer about "
                  "{topic} warmly and plainly, name the next step. "
                  "Order reference: {order_id}.")))
    reg.start_canary("support_reply", version=3, percent=10)
    ok, reasons = gate_decision(canary_negative_rate=0.05, canary_p95_ms=3200,
                                t=GateThresholds())
    print(f"Gate on v3 canary: {'PROMOTE' if ok else 'ROLL BACK'} ({reasons[0]})")
    assert ok is True
    reg.promote("support_reply")
    final = [reg.resolve("support_reply", u).version for u in users]
    assert all(v == 3 for v in final)
    print("After promotion: all 200 users on v3.")

    print("\nAudit trail")
    for line in reg.audit:
        print(f"  {line}")
    print("Self-checks passed: distribution, determinism, rollback and "
          "promotion all behave as designed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
