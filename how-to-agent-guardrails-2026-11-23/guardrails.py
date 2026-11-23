"""Production AI agent guardrails system.
Policy checks, sensitive data redaction, tool allowlist, budget caps and audit log.
Standard library only.
"""
import hashlib, json, re, time
from dataclasses import dataclass

EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
CARD = re.compile(r"\b(?:\d[ -]?){13,16}\b")

@dataclass
class Decision:
    allowed: bool
    reason: str
    redacted: str = ""

class Policy:
    def __init__(self, allowed_tools, budget_usd=5.0, max_output_chars=4000):
        self.allowed_tools = set(allowed_tools)
        self.budget_usd = budget_usd
        self.max_output_chars = max_output_chars
        self.spent = 0.0
        self.audit = []
    def _log(self, kind, detail):
        self.audit.append({"ts": round(time.time(), 3), "kind": kind, "detail": detail})
    def redact(self, text):
        text = EMAIL.sub("[email removed]", text)
        text = CARD.sub("[card removed]", text)
        return text
    def check_input(self, text):
        redacted = self.redact(text)
        low = text.lower()
        if "ignore your instructions" in low or "disable monitoring" in low:
            self._log("blocked_input", "instruction override attempt")
            return Decision(False, "instruction override attempt", redacted)
        self._log("input_ok", hashlib.sha256(redacted.encode()).hexdigest()[:10])
        return Decision(True, "input accepted", redacted)
    def check_tool(self, name, est_cost=0.05):
        if name not in self.allowed_tools:
            self._log("blocked_tool", name)
            return Decision(False, f"tool {name} is not on the allowlist")
        if self.spent + est_cost > self.budget_usd:
            self._log("blocked_budget", f"spent {self.spent:.2f}")
            return Decision(False, "budget cap reached")
        self.spent += est_cost
        self._log("tool_ok", name)
        return Decision(True, "tool allowed")
    def check_output(self, text):
        redacted = self.redact(text)
        if len(redacted) > self.max_output_chars:
            redacted = redacted[: self.max_output_chars]
            self._log("output_trimmed", "output over limit")
        self._log("output_ok", hashlib.sha256(redacted.encode()).hexdigest()[:10])
        return Decision(True, "output accepted", redacted)
    def report(self):
        return {"spent_usd": round(self.spent, 2), "audit_events": len(self.audit), "events": self.audit}

if __name__ == "__main__":
    print(json.dumps({"module": "guardrails", "ready": True}))
