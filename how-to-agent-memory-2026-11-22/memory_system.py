"""Production agent memory system core, Python standard library only.

Four memory layers, as built in the How-to guide:
1. Working memory: the current session, kept in full, dropped at session end.
2. Episodic memory: timestamped events, what happened, with decay.
3. Semantic memory: durable facts about the user and the world, versioned.
4. Procedural memory: learned preferences and rules, with confidence.

Retrieval scores every candidate on relevance (token overlap), recency
(exponential decay) and importance, then packs the top items into a token
budget. Writes go through a gate: secrets and one off noise are refused,
contradictions supersede old facts instead of piling up, and every change
is appended to an audit log. Storage is one JSON file, atomic on save.

Run the demo with: python3 run_demo.py
"""
import hashlib
import json
import math
import os
import re
import time
from dataclasses import asdict, dataclass, field

SECRET_PATTERNS = [
    re.compile(r"\b(password|passwd|api[_ ]?key|secret|token)\b", re.I),
    re.compile(r"\bsk-[A-Za-z0-9]{10,}\b"),
    re.compile(r"\b\d{4}[- ]\d{4}[- ]\d{4}[- ]\d{4}\b"),
]


@dataclass
class MemoryItem:
    id: str
    layer: str
    kind: str
    text: str
    subject: str = ""
    importance: float = 0.5
    confidence: float = 1.0
    created_at: float = 0.0
    last_accessed: float = 0.0
    access_count: int = 0
    superseded_by: str = ""
    ttl_days: float = 0.0

    def active(self, now):
        if self.superseded_by:
            return False
        if self.ttl_days and now > self.created_at + self.ttl_days * 86400:
            return False
        return True


def make_id(layer, text, now):
    raw = f"{layer}|{text}|{now}".encode()
    return hashlib.sha256(raw).hexdigest()[:12]


def looks_secret(text):
    return any(p.search(text) for p in SECRET_PATTERNS)


def tokens(text):
    return set(re.findall(r"[a-z0-9]+", text.lower()))


class MemorySystem:
    def __init__(self, path=None, half_life_days=30.0):
        self.path = path
        self.half_life_days = half_life_days
        self.items = {}
        self.working = []
        self.audit = []
        if path and os.path.exists(path):
            self.load()

    def _log(self, action, item_id, detail=""):
        self.audit.append({"ts": time.time(), "action": action,
                           "item": item_id, "detail": detail})

    def add(self, layer, kind, text, subject="", importance=0.5,
            confidence=1.0, ttl_days=0.0, now=None):
        now = time.time() if now is None else now
        text = text.strip()
        if not text:
            return None, "refused_empty"
        if looks_secret(text):
            self._log("refused_secret", "", text[:40])
            return None, "refused_secret"
        if layer == "working":
            self.working.append({"kind": kind, "text": text, "ts": now})
            return None, "working_only"
        if layer == "semantic" and subject:
            for old in self.items.values():
                if (old.layer == "semantic" and old.subject == subject
                        and old.active(now) and old.text != text):
                    new_id = make_id(layer, text, now)
                    old.superseded_by = new_id
                    self._log("superseded", old.id, f"by {new_id}")
                    item = MemoryItem(new_id, layer, kind, text, subject,
                                      importance, confidence, now, now, 0, "", ttl_days)
                    self.items[new_id] = item
                    self._log("added", new_id, "semantic update")
                    return item, "added_superseding"
        for old in self.items.values():
            if old.active(now) and old.text == text and old.layer == layer:
                old.access_count += 1
                old.last_accessed = now
                return old, "duplicate_reinforced"
        item = MemoryItem(make_id(layer, text, now), layer, kind, text, subject,
                          importance, confidence, now, now, 0, "", ttl_days)
        self.items[item.id] = item
        self._log("added", item.id, layer)
        return item, "added"

    def score(self, item, query_tokens, now):
        overlap = tokens(item.text) | tokens(item.subject)
        rel = (len(query_tokens & overlap) / len(query_tokens)) if query_tokens else 0.0
        age_days = max(0.0, (now - item.created_at) / 86400.0)
        recency = math.pow(0.5, age_days / self.half_life_days)
        return 0.55 * rel + 0.25 * recency + 0.20 * item.importance

    def retrieve(self, query, token_budget=400, now=None, layers=None):
        now = time.time() if now is None else now
        q = tokens(query)
        cands = [i for i in self.items.values() if i.active(now)
                 and (layers is None or i.layer in layers)]
        cands.sort(key=lambda i: self.score(i, q, now), reverse=True)
        picked, used = [], 0
        for item in cands:
            cost = max(8, len(item.text.split()) + 4)
            if used + cost > token_budget:
                continue
            item.access_count += 1
            item.last_accessed = now
            picked.append(item)
            used += cost
        return picked, used

    def consolidate(self, now=None, min_importance=0.7):
        """Promote repeated or important working notes into episodic memory."""
        now = time.time() if now is None else now
        promoted = 0
        counts = {}
        for note in self.working:
            counts[note["text"]] = counts.get(note["text"], 0) + 1
        for text, n in counts.items():
            if n >= 2:
                _, status = self.add("episodic", "consolidated", text,
                                     importance=min_importance, now=now)
                if status.startswith("added"):
                    promoted += 1
        self.working = []
        self._log("consolidated", "", f"{promoted} promoted")
        return promoted

    def forget(self, item_id, reason="user_request"):
        item = self.items.get(item_id)
        if not item:
            return False
        del self.items[item_id]
        self._log("forgotten", item_id, reason)
        return True

    def save(self):
        if not self.path:
            return
        data = {"items": [asdict(i) for i in self.items.values()],
                "audit": self.audit}
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=1)
        os.replace(tmp, self.path)

    def load(self):
        with open(self.path, encoding="utf-8") as fh:
            data = json.load(fh)
        self.items = {d["id"]: MemoryItem(**d) for d in data["items"]}
        self.audit = data.get("audit", [])

    def stats(self, now=None):
        now = time.time() if now is None else now
        out = {"working": len(self.working), "audit_events": len(self.audit)}
        for layer in ("episodic", "semantic", "procedural"):
            out[layer] = sum(1 for i in self.items.values()
                             if i.layer == layer and i.active(now))
        out["superseded"] = sum(1 for i in self.items.values() if i.superseded_by)
        return out
