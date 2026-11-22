# How-To: Production Agent Memory System, 2026-11-22

Companion code for: How to Build a Production Agent Memory System That
Remembers What Matters and Forgets What It Must.

## Files
- memory_system.py: the memory core. Four layers (working, episodic,
  semantic, procedural), a write gate that refuses secrets and empty writes,
  contradiction handling by superseding, retrieval scored on relevance,
  recency decay and importance under a token budget, consolidation from
  working memory, hard forget, an audit log, and atomic JSON storage.
- run_demo.py: writes facts, updates one fact so the old one is superseded,
  tries to store a password and is refused, consolidates repeated working
  notes, retrieves under a token budget, saves, reloads and checks stats.

## Run
python3 run_demo.py

Python standard library only, no installs, no API keys, no network.
