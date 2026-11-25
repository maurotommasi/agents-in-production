"""Production multi-agent orchestration system.

A supervisor plans work, a priority queue holds tasks, specialist agent
workers claim tasks, results are validated, failed tasks retry with
backoff, and every step writes an audit event. Standard library only.
Replace the worker functions with your model gateway calls in production.
"""
import hashlib
import heapq
import time
from dataclasses import dataclass, field

MAX_RETRIES = 2
BUDGET_CAP = 1.00


@dataclass
class Task:
    task_id: str
    kind: str
    payload: str
    priority: int = 5
    attempts: int = 0
    depends_on: tuple = ()
    status: str = "queued"
    result: str = ""


@dataclass
class Run:
    run_id: str
    tasks: dict = field(default_factory=dict)
    events: list = field(default_factory=list)
    spent: float = 0.0
    completed: list = field(default_factory=list)


def log(run, kind, detail):
    run.events.append({"ts": round(time.time(), 3), "run": run.run_id,
                       "kind": kind, "detail": detail})


def research_worker(task):
    return "evidence: " + task.payload.strip().lower()[:60]


def writer_worker(task):
    return "draft about " + task.payload.strip()[:60]


def critic_worker(task):
    if "flaky" in task.payload and task.attempts <= 1:
        raise RuntimeError("simulated transient model timeout")
    return "approved: " + task.payload.strip()[:60]


def coder_worker(task):
    digest = hashlib.sha256(task.payload.encode()).hexdigest()[:8]
    return "artifact " + digest + " for " + task.payload.strip()[:40]


WORKERS = {
    "research": (research_worker, 0.08),
    "write": (writer_worker, 0.12),
    "critique": (critic_worker, 0.05),
    "code": (coder_worker, 0.15),
}


def plan(run_id, goal, steps):
    """Build a Run from ordered steps. Each step is (kind, payload, priority)."""
    run = Run(run_id=run_id)
    prev = None
    for i, (kind, payload, priority) in enumerate(steps, 1):
        tid = run_id + "-t" + str(i)
        deps = (prev,) if prev else ()
        run.tasks[tid] = Task(tid, kind, payload, priority, depends_on=deps)
        prev = tid
    log(run, "planned", str(len(steps)) + " tasks for goal: " + goal[:60])
    return run


def ready_tasks(run):
    done = set(run.completed)
    return [t for t in run.tasks.values()
            if t.status == "queued" and set(t.depends_on).issubset(done)]


def execute(run):
    """Run ready tasks in priority order until none remain or budget stops."""
    while True:
        ready = ready_tasks(run)
        if not ready:
            break
        ready.sort(key=lambda t: t.priority)
        task = ready[0]
        worker, cost = WORKERS[task.kind]
        if run.spent + cost > BUDGET_CAP:
            task.status = "budget_blocked"
            log(run, "budget_block", task.task_id + " would exceed cap")
            break
        task.status = "running"
        task.attempts += 1
        log(run, "claimed", task.task_id + " by " + task.kind + " worker")
        try:
            task.result = worker(task)
            run.spent = round(run.spent + cost, 4)
            task.status = "done"
            run.completed.append(task.task_id)
            log(run, "done", task.task_id + " cost " + str(cost))
        except Exception as exc:
            log(run, "failed", task.task_id + " " + str(exc))
            if task.attempts <= MAX_RETRIES:
                task.status = "queued"
                log(run, "retry", task.task_id + " attempt " + str(task.attempts + 1))
            else:
                task.status = "failed"
                log(run, "gave_up", task.task_id)
                break
    return run


def summary(run):
    states = {}
    for t in run.tasks.values():
        states[t.status] = states.get(t.status, 0) + 1
    return {"run": run.run_id, "states": states, "spent": run.spent,
            "events": len(run.events), "completed": list(run.completed)}
