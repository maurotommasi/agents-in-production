"""Demo and self check for the agent memory system. Standard library only.

Run: python3 run_demo.py
"""
import os
import tempfile
import time

from memory_system import MemorySystem

DAY = 86400.0


def main():
    now = time.time()
    path = os.path.join(tempfile.mkdtemp(), "memory.json")
    ms = MemorySystem(path=path)

    _, s1 = ms.add("semantic", "fact", "User lives in Los Angeles and works in Pacific Time",
                   subject="user.location", importance=0.9, now=now)
    _, s2 = ms.add("semantic", "fact", "User relocated to Los Angeles, Maltman Avenue area",
                   subject="user.location", importance=0.9, now=now + DAY)
    _, s3 = ms.add("episodic", "event", "User shipped the GreenGo Stripe dashboard work on Nov 21",
                   importance=0.7, now=now)
    _, s4 = ms.add("procedural", "preference", "Never use the em dash character in LinkedIn posts",
                   importance=0.95, now=now)
    _, s5 = ms.add("semantic", "secret", "User password is hunter2 for the dashboard", now=now)
    ms.add("working", "note", "Draft the Sunday bundle", now=now)
    ms.add("working", "note", "Draft the Sunday bundle", now=now)
    promoted = ms.consolidate(now=now)

    picked, used = ms.retrieve("Los Angeles location timezone", now=now + DAY)
    print("write results:", s1, s2, s3, s4, s5)
    print("consolidated from working memory:", promoted)
    print(f"retrieval used {used} tokens, top hits:")
    for item in picked[:3]:
        print(f"  [{item.layer}] {item.text}")
    ms.save()
    ms2 = MemorySystem(path=path)
    st = ms2.stats(now=now + DAY)
    print("stats after reload:", st)
    assert s5 == "refused_secret", s5
    assert s2 == "added_superseding", s2
    assert picked and "Los Angeles" in picked[0].text
    assert st["superseded"] == 1
    print("ALL CHECKS PASSED")


if __name__ == "__main__":
    main()
