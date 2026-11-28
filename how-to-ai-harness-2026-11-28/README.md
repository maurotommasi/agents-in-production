# A minimal AI harness

A harness is everything around the model that makes it work as an agent:
context assembly, tool calling, memory, the control loop, error recovery
and output verification. The model is one component. This folder is the rest.

`harness.py` is a complete, runnable harness in one file, standard library
only. The model inside it is a small deterministic stand-in, so the harness
runs anywhere with no API key. Swap in a real model call at the one marked
point (`ScriptedModel.next_action`) and nothing else changes.

## Run it

```bash
python3 harness.py
```

## What the demo shows

Task 1: a password reset where the first tool call fails (a flaky account
service). The harness retries inside its cap, finishes the work, verifies
the answer and delivers it.

Task 2: a $120 refund where the tool says a human must decide. The model
tries three times to claim the refund is done anyway. The verification
gate rejects each attempt, the retry cap runs out, and the case escalates
to a human with the full history attached. That escalation is the harness
working, not failing.

## The five parts

1. **Tool registry** - tools are registered by name with a description;
   the model can only call what exists.
2. **Context builder** - assembles the prompt fresh on every step under a
   character budget; memory is cut oldest first, by policy.
3. **The model stand-in** - returns either a tool call or a final answer.
4. **Verification gate** - every proposed answer is checked before
   delivery: not empty, not guessing, and never claiming work is done
   when a tool said a human must decide.
5. **The control loop** - perceive, plan, act, check, recover. Retries are
   capped. When the cap runs out, a human gets the case.

Companion to the guide "The AI Harness: The Part of the Agent That
Actually Ships" by Mauro Tommasi (LinkedIn, 28 November 2026).
