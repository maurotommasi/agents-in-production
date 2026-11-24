"""Production AI code review pipeline.

Parses a unified diff, runs deterministic checks, scores findings with a
model stub, applies the team approval policy, and writes an audit record
for every decision. Standard library only. Replace model_review() with
your model gateway call in production.
"""
import hashlib
import re
import time
from dataclasses import dataclass, field

SECRET_PATTERNS = [
    (re.compile(r"(api_key|secret|password)\s*=\s*['\"][^'\"]+['\"]"), "hardcoded secret"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "AWS access key in code"),
]
RISK_PATTERNS = [
    (re.compile(r"eval\(|exec\("), "dynamic code execution"),
    (re.compile(r"shell=True"), "shell call with string input"),
    (re.compile(r"pickle\.loads"), "unsafe deserialisation"),
]


@dataclass
class Finding:
    file: str
    line: int
    severity: str
    rule: str
    detail: str


@dataclass
class Policy:
    block_on: tuple = ("critical", "high")
    max_findings_to_approve: int = 3
    require_human_for: tuple = ("auth", "payments", "migrations")


@dataclass
class Review:
    pr_id: str
    decision: str = "pending"
    findings: list = field(default_factory=list)
    audit: list = field(default_factory=list)


def parse_diff(diff_text):
    """Return a list of (file, line_number, added_line) from a unified diff."""
    added = []
    current_file = ""
    new_line = 0
    for raw in diff_text.splitlines():
        if raw.startswith("+++ b/"):
            current_file = raw[6:]
        elif raw.startswith("@@"):
            m = re.search(r"\+(\d+)", raw)
            new_line = int(m.group(1)) if m else 0
        elif raw.startswith("+") and not raw.startswith("+++"):
            added.append((current_file, new_line, raw[1:]))
            new_line += 1
        elif not raw.startswith("-"):
            new_line += 1
    return added


def static_checks(added):
    findings = []
    for fname, lineno, line in added:
        for pattern, label in SECRET_PATTERNS:
            if pattern.search(line):
                findings.append(Finding(fname, lineno, "critical", "secret", label))
        for pattern, label in RISK_PATTERNS:
            if pattern.search(line):
                findings.append(Finding(fname, lineno, "high", "risk", label))
        if "TODO" in line or "FIXME" in line:
            findings.append(Finding(fname, lineno, "low", "todo", "unfinished marker left in code"))
    return findings


def model_review(added):
    """Model stub. In production this calls your model gateway with the
    diff hunks and returns structured findings in the same shape."""
    findings = []
    for fname, lineno, line in added:
        if "except:" in line or "except Exception: pass" in line:
            findings.append(Finding(fname, lineno, "medium", "model",
                                    "broad exception handler may hide failures"))
        if len(line) > 140:
            findings.append(Finding(fname, lineno, "low", "model",
                                    "very long line hurts review readability"))
    return findings


def review_pr(pr_id, diff_text, policy=None, author="dev"):
    policy = policy or Policy()
    review = Review(pr_id=pr_id)
    added = parse_diff(diff_text)
    review.findings = static_checks(added) + model_review(added)
    digest = hashlib.sha256(diff_text.encode()).hexdigest()[:12]
    review.audit.append({"ts": time.time(), "kind": "reviewed", "pr": pr_id,
                         "diff_hash": digest, "findings": len(review.findings)})
    severities = {f.severity for f in review.findings}
    touched = " ".join(f.file for f in review.findings) + " " + " ".join(a[0] for a in added)
    if severities.intersection(policy.block_on):
        review.decision = "blocked"
        review.audit.append({"ts": time.time(), "kind": "blocked",
                             "reason": "critical finding present"})
    elif any(word in touched for word in policy.require_human_for):
        review.decision = "needs_human"
        review.audit.append({"ts": time.time(), "kind": "needs_human",
                             "reason": "sensitive area touched"})
    elif len(review.findings) <= policy.max_findings_to_approve:
        review.decision = "approved"
        review.audit.append({"ts": time.time(), "kind": "approved",
                             "reason": "findings within policy limit"})
    else:
        review.decision = "changes_requested"
        review.audit.append({"ts": time.time(), "kind": "changes_requested",
                             "reason": "too many findings"})
    return review
