"""Demo for the AI code review pipeline. Run: python3 run_demo.py"""
from reviewer import review_pr

CLEAN = """--- a/app.py
+++ b/app.py
@@ -1,2 +1,3 @@
 def total(items):
     return sum(items)
+    # returns the sum of all items
"""

SECRET = """--- a/config.py
+++ b/config.py
@@ -1,1 +1,2 @@
 DEBUG = False
+api_key = "sk-live-1234567890"
"""

AUTH = """--- a/auth/login.py
+++ b/auth/login.py
@@ -1,1 +1,2 @@
 def login(user):
     return check(user)
+    # new session handling
"""

RISKY = """--- a/jobs.py
+++ b/jobs.py
@@ -1,1 +1,3 @@
 import subprocess
+result = eval(user_input)
+out = subprocess.run(cmd, shell=True)
"""

for pr_id, diff in [("pr-101", CLEAN), ("pr-102", SECRET), ("pr-103", AUTH), ("pr-104", RISKY)]:
    r = review_pr(pr_id, diff)
    print(pr_id, "decision:", r.decision, "| findings:", len(r.findings))
    for f in r.findings:
        print("  ", f.severity, f.rule, f.file, "line", f.line, f.detail)
    print("   audit events:", len(r.audit))
