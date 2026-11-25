# How to Build a Production Multi-Agent Orchestration System, code, 2026-11-25

Complete runnable code, Python standard library only. Supervisor planner, priority queue with dependencies, specialist workers, budget cap checked before work, retry with a limit, and an audit event for every decision.

Run: python3 run_demo.py

Verified run: run-1 completes all 4 tasks (research, write, critique, code), spends $0.40 against the $1.00 cap, writes 9 audit events. Run-2 flaky critique step fails once, retries, succeeds on attempt 2, spends $0.13, writes 8 audit events.
