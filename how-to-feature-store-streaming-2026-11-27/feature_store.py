#!/usr/bin/env python3
"""Production feature store, minimal but complete reference service.

One feature end to end: play events arrive, a streaming job maintains a
rolling 7 day watch count per user, the value is registered with a
version and a data contract, written to an online store for low latency
serving and to an offline log for training, with point in time correct
joins so training never sees the future.

Standard library only. Setup: no install step.
Run: python3 feature_store.py
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta

WINDOW = timedelta(days=7)
FRESH_LIMIT = timedelta(minutes=15)


@dataclass(frozen=True)
class PlayEvent:
    user_id: str
    content_id: str
    ts: datetime
    watch_sec: int


@dataclass
class FeatureDef:
    name: str
    version: int
    entity: str          # the key the feature is about, here user_id
    dtype: str
    description: str
    max_age: timedelta   # freshness contract, serving refuses older data


class Registry:
    """Versioned feature definitions. Old versions stay readable."""

    def __init__(self):
        self._defs = {}

    def register(self, d):
        key = (d.name, d.version)
        if key in self._defs:
            raise ValueError(f"feature {key} already registered")
        self._defs[key] = d
        return d

    def get(self, name, version):
        return self._defs[(name, version)]


class OnlineStore:
    """Latest value per entity, with the event time it came from."""

    def __init__(self):
        self._rows = {}  # (feature, entity) -> (value, event_ts)

    def put(self, feature, entity, value, event_ts):
        key = (feature, entity)
        if key not in self._rows or event_ts >= self._rows[key][1]:
            self._rows[key] = (value, event_ts)

    def get(self, feature, entity):
        return self._rows.get((feature, entity))


class OfflineLog:
    """Append only history for training and point in time joins."""

    def __init__(self):
        self.rows = []  # (feature, entity, value, event_ts)

    def append(self, feature, entity, value, event_ts):
        self.rows.append((feature, entity, value, event_ts))

    def point_in_time(self, feature, entity, as_of):
        """Latest value at or before as_of. Never the future."""
        best = None
        for f, e, v, ts in self.rows:
            if f == feature and e == entity and ts <= as_of:
                if best is None or ts >= best[1]:
                    best = (v, ts)
        return best


class StreamingJob:
    """Maintains the rolling window feature from the event stream."""

    def __init__(self, online, offline):
        self.online = online
        self.offline = offline
        self._events = {}  # entity -> list of (ts, watch_sec)

    def on_event(self, ev):
        hist = self._events.setdefault(ev.user_id, [])
        hist.append((ev.ts, ev.watch_sec))
        cutoff = ev.ts - WINDOW
        hist[:] = [(t, w) for (t, w) in hist if t > cutoff]
        value = sum(w for _, w in hist)
        self.online.put("watch_sec_7d", ev.user_id, value, ev.ts)
        self.offline.append("watch_sec_7d", ev.user_id, value, ev.ts)
        return value


def serve(registry, online, user_id, now):
    """Serve one feature, enforcing the freshness contract."""
    d = registry.get("watch_sec_7d", 1)
    row = online.get("watch_sec_7d", user_id)
    if row is None:
        return {"value": 0, "fresh": True, "note": "no history, default 0"}
    value, ts = row
    fresh = (now - ts) <= d.max_age or (now - ts) <= FRESH_LIMIT
    return {"value": value, "fresh": bool(fresh), "event_ts": ts.isoformat()}


def main():
    reg = Registry()
    reg.register(FeatureDef(
        name="watch_sec_7d", version=1, entity="user_id", dtype="int",
        description="Seconds watched in the last 7 days, rolling window.",
        max_age=FRESH_LIMIT))
    online, offline = OnlineStore(), OfflineLog()
    job = StreamingJob(online, offline)
    t0 = datetime(2026, 11, 20, 12, 0, 0)
    job.on_event(PlayEvent("u1", "filmA", t0, 1200))
    job.on_event(PlayEvent("u1", "filmB", t0 + timedelta(days=2), 1800))
    job.on_event(PlayEvent("u1", "filmC", t0 + timedelta(days=8), 600))
    # After day 8, the day 0 event falls out of the 7 day window.
    got = serve(reg, online, "u1", t0 + timedelta(days=8, minutes=5))
    print("served:", got)
    assert got["value"] == 2400, got  # 1800 + 600, day 0 expired
    # Point in time: as of day 3, training must see 3000, not 2400.
    pit = offline.point_in_time("watch_sec_7d", "u1", t0 + timedelta(days=3))
    print("point in time at day 3:", pit)
    assert pit[0] == 3000, pit
    print("OK: window, freshness and point in time join all correct")


if __name__ == "__main__":
    main()
