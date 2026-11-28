# How-to: Production Prompt Registry and Safe Rollout (28 Nov 2026)

`prompt_registry.py` is the complete code for the guide: immutable
prompt versions with author and reason, deterministic hash bucketing
per user, a canary dial, a metric gate that promotes or rolls back, and
an append only audit trail.

Run it (standard library only):

    python3 prompt_registry.py

It simulates 200 users: the v2 canary serves 23 of them, fails the gate
on negative rate and latency, and rolls back; the fixed v3 passes and
is promoted. Self-checks assert the distribution, determinism, rollback
and promotion behaviour.
