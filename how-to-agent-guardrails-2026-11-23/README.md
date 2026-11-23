# How to Build a Production AI Agent Guardrails System, 2026-11-23

Full code for the guide: policy checks on input, tools and output, sensitive data redaction, budget caps and an audit log.

## Run
python3 run_demo.py

Files: guardrails.py (full system), run_demo.py (worked example).
Standard library only, no install step.
Setup in production: load the allowlist and budget from your config service, send audit events to your log store, and alert on blocked_tool and blocked_input events.
