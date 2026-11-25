"""Demo for the multi-agent orchestrator. Run: python3 run_demo.py"""
from orchestrator import plan, execute, summary

# Workflow 1: a four step content pipeline, research, write, critique, code.
run = plan("run-1", "Produce a launch brief with a sample artifact", [
    ("research", "Market evidence for agent orchestration", 1),
    ("write", "Launch brief from the research evidence", 2),
    ("critique", "Check the brief for unsupported claims", 3),
    ("code", "Sample artifact that shows the workflow output", 4),
])
execute(run)
print("run-1 summary:", summary(run))
for tid in run.completed:
    print(" ", tid, run.tasks[tid].result)
for e in run.events:
    print(" event", e["kind"], e["detail"])

# Workflow 2: a flaky critique step retries once and then succeeds.
run2 = plan("run-2", "Review a flaky supplier note", [
    ("research", "Supplier note evidence, flaky source", 1),
    ("critique", "flaky review of the supplier note", 2),
])
execute(run2)
print("run-2 summary:", summary(run2))
print(" run-2 critique attempts:", run2.tasks["run-2-t2"].attempts,
      "status:", run2.tasks["run-2-t2"].status)
