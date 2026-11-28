"""
harness.py - a minimal AI harness in one file.

A harness is everything around the model that makes it work as an agent:
context assembly, tool calling, memory, the control loop, error recovery
and output verification. The model is one component. This file is the rest.

The model here is a small deterministic stand-in, so the harness runs
anywhere with no API key. Swap in a real model call at the one marked
point (ScriptedModel.next_action) and nothing else changes.

Run it:  python3 harness.py
"""

from __future__ import annotations

import json
import textwrap
from dataclasses import dataclass, field


# --------------------------------------------------------------------------
# 1. Tool layer: a registry the model can ask for by name.
# --------------------------------------------------------------------------

class ToolError(Exception):
    """A tool failed in a way the harness may retry."""


class ToolRegistry:
    def __init__(self) -> None:
        self._tools = {}

    def register(self, name: str, func, description: str) -> None:
        self._tools[name] = (func, description)

    def describe(self) -> str:
        lines = []
        for name, (_, desc) in sorted(self._tools.items()):
            lines.append(f"- {name}: {desc}")
        return "\n".join(lines)

    def call(self, name: str, args: dict):
        if name not in self._tools:
            raise ToolError(f"unknown tool: {name}")
        func, _ = self._tools[name]
        return func(**args)


# --------------------------------------------------------------------------
# 2. Context assembly: build the prompt, and cut on a rule when it grows.
# --------------------------------------------------------------------------

class ContextBuilder:
    """Assembles what the model sees on each step.

    Budget rule: the system prompt and the current task are never cut.
    Memory notes are cut oldest first. Tool results from earlier steps
    are summarised to one line each. The cut is a policy, not an accident.
    """

    def __init__(self, system: str, budget_chars: int = 4000) -> None:
        self.system = system
        self.budget = budget_chars
        self.memory: list[str] = []
        self.history: list[str] = []

    def remember(self, note: str) -> None:
        self.memory.append(note)

    def build(self, task: str, tools: ToolRegistry) -> str:
        parts = [self.system, f"\nTools available:\n{tools.describe()}"]
        parts.append(f"\nTask: {task}")
        if self.history:
            parts.append("\nSo far:\n" + "\n".join(self.history[-6:]))
        context = "\n".join(parts)
        notes = list(self.memory)
        while notes and len(context) + sum(len(n) for n in notes) > self.budget:
            dropped = notes.pop(0)  # oldest memory goes first
            self.history.append(f"(context cut: dropped oldest memory: {dropped[:40]}...)")
        if notes:
            context += "\n\nMemory:\n" + "\n".join(f"- {n}" for n in notes)
        return context


# --------------------------------------------------------------------------
# 3. The model stand-in. Replace next_action with a real model call.
# --------------------------------------------------------------------------

class ScriptedModel:
    """Deterministic stand-in for an LLM.

    It reads a tiny plan from the task text so the demo is repeatable.
    A real model would produce the same shape: either a tool call or
    a final answer. The harness does not care which one produced it.
    """

    def __init__(self, plan: list[dict]) -> None:
        self._plan = list(plan)

    def next_action(self, context: str) -> dict:
        # >>> This is the one place a real model call would go. <<<
        if self._plan:
            return self._plan.pop(0)
        return {"type": "final", "answer": "No plan left. Escalating is safer than guessing."}


# --------------------------------------------------------------------------
# 4. Verification: the gate every answer passes before delivery.
# --------------------------------------------------------------------------

def verify_answer(answer: str, history: str) -> tuple[bool, str]:
    """Cheap, blunt checks. A real harness layers these: schema checks,
    policy rules, a second model, human sampling. The point is the gate
    exists and the loop respects it."""
    if not answer or len(answer.strip()) < 20:
        return False, "answer is empty or too short to help anyone"
    if "i guess" in answer.lower() or "probably fine" in answer.lower():
        return False, "the answer is guessing, and guessing is what the gate is for"
    if "requires human approval" in history.lower():
        claims_done = any(p in answer.lower() for p in
                          ("approved", "issued", "on its way", "has been sent"))
        if claims_done:
            return False, ("a tool said a human must decide this, but the "
                           "answer claims it is already done")
    return True, "passed"


# --------------------------------------------------------------------------
# 5. The control loop: perceive, plan, act, check, recover.
# --------------------------------------------------------------------------

@dataclass
class RunResult:
    status: str                 # "delivered" or "escalated_to_human"
    answer: str = ""
    steps: int = 0
    retries: int = 0
    log: list[str] = field(default_factory=list)


class Harness:
    def __init__(self, tools: ToolRegistry, context: ContextBuilder,
                 max_steps: int = 8, max_retries: int = 2) -> None:
        self.tools = tools
        self.context = context
        self.max_steps = max_steps
        self.max_retries = max_retries

    def run(self, task: str, model: ScriptedModel) -> RunResult:
        result = RunResult(status="escalated_to_human")
        failures = 0
        for step in range(1, self.max_steps + 1):
            result.steps = step
            prompt = self.context.build(task, self.tools)
            action = model.next_action(prompt)

            if action["type"] == "tool":
                name, args = action["name"], action.get("args", {})
                try:
                    out = self.tools.call(name, args)
                except ToolError as err:
                    failures += 1
                    result.retries += 1
                    result.log.append(f"step {step}: tool {name} failed ({err}); "
                                      f"failure {failures} of {self.max_retries + 1}")
                    if failures > self.max_retries:
                        result.log.append("retries exhausted: escalating to a human "
                                          "with the full history attached")
                        return result
                    continue
                failures = 0
                short = str(out)[:80]
                self.context.history.append(f"step {step}: {name} -> {short}")
                result.log.append(f"step {step}: called {name}, got: {short}")
                continue

            # Final answer proposed: it must pass the gate before delivery.
            ok, why = verify_answer(action["answer"],
                                    "\n".join(self.context.history))
            if ok:
                result.status = "delivered"
                result.answer = action["answer"]
                result.log.append(f"step {step}: answer passed verification ({why}); delivered")
                return result
            failures += 1
            result.retries += 1
            result.log.append(f"step {step}: answer rejected by the gate ({why})")
            if failures > self.max_retries:
                result.log.append("gate kept rejecting: escalating to a human "
                                  "instead of shipping a bad answer")
                return result
        result.log.append("step budget exhausted: escalating to a human")
        return result


# --------------------------------------------------------------------------
# Demo tools: a tiny support desk. One tool is flaky on purpose.
# --------------------------------------------------------------------------

_flaky = {"calls": 0}


def lookup_account(customer: str) -> dict:
    _flaky["calls"] += 1
    if _flaky["calls"] == 1:
        raise ToolError("account service timed out")
    return {"customer": customer, "plan": "team", "status": "active",
            "open_tickets": 1}


def reset_password(customer: str) -> dict:
    return {"customer": customer, "reset_link_sent": True,
            "expires_in_minutes": 30}


def issue_refund(customer: str, amount: float) -> dict:
    if amount > 50:
        return {"customer": customer,
                "result": "requires human approval over the $50 limit"}
    return {"customer": customer, "result": "refund issued"}


def build_demo_harness() -> Harness:
    tools = ToolRegistry()
    tools.register("lookup_account", lookup_account,
                   "Look up a customer account by name.")
    tools.register("reset_password", reset_password,
                   "Send a password reset link to the customer.")
    tools.register("issue_refund", issue_refund,
                   "Issue a refund. Amounts over $50 need a human.")
    context = ContextBuilder(
        system=("You are a support agent. Be brief, be accurate, and never "
                "guess. If a tool says a human must decide, say so plainly."))
    return Harness(tools, context)


def show(title: str, result: RunResult) -> None:
    print(f"\n=== {title} ===")
    for line in result.log:
        print(textwrap.fill(line, width=88, subsequent_indent="    "))
    print(f"--> status: {result.status} | steps: {result.steps} | retries: {result.retries}")
    if result.answer:
        print(textwrap.fill(f"answer: {result.answer}", width=88,
                            subsequent_indent="    "))


def main() -> None:
    harness = build_demo_harness()

    # Task 1: a flaky tool fails once, the harness retries, the answer ships.
    plan1 = [
        {"type": "tool", "name": "lookup_account", "args": {"customer": "Ana"}},
        {"type": "tool", "name": "lookup_account", "args": {"customer": "Ana"}},
        {"type": "tool", "name": "reset_password", "args": {"customer": "Ana"}},
        {"type": "final", "answer": "Hi Ana, your account is active on the team "
                                    "plan, and a fresh password reset link is on "
                                    "its way. It expires in 30 minutes."},
    ]
    show("Task 1: password reset, with a flaky first tool call",
         harness.run("Ana cannot log in and needs a password reset.",
                     ScriptedModel(plan1)))

    # Task 2: the tool says a human must decide. The model tries to bluff
    # past the gate three times; the gate refuses; a human gets the case.
    bluff = "Good news, Bruno: your $120 refund is approved and on its way."
    plan2 = [
        {"type": "tool", "name": "issue_refund",
         "args": {"customer": "Bruno", "amount": 120}},
        {"type": "final", "answer": bluff},
        {"type": "final", "answer": bluff},
        {"type": "final", "answer": bluff},
    ]
    show("Task 2: a refund the agent must not approve alone",
         harness.run("Bruno asks for a $120 refund.",
                     ScriptedModel(plan2)))


if __name__ == "__main__":
    main()
