"""Plant one-line bugs and check that each module's tests catch them.

Each mutant is applied to a fresh copy of the repo, then only that module's
test file is run. A mutant is "killed" when at least one test fails.

    .venv/bin/python scripts/mutants.py
"""

import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

MUTANTS = [
    # id, file, original, mutated, test file
    ("M1.1", "policy.py", "if got < floor:", "if got <= floor:", "test_policy.py"),
    ("M1.2", "policy.py", "if amount > ceiling:", "if amount >= ceiling:", "test_policy.py"),
    ("M1.3", "policy.py", "if projected > ceiling:", "if projected >= ceiling:", "test_policy.py"),
    ("M1.4", "policy.py", "    if matter not in ctx[\"matters\"]:\n        return _check(rule, True",
     "    if False:\n        return _check(rule, True", "test_policy.py"),
    ("M1.5", "policy.py", "if _key(vendor) not in panel:", "if vendor not in panel.values():",
     "test_policy.py"),
    ("M1.6", "policy.py", "if entry[\"code\"].lower() in haystack.lower():",
     "if entry[\"code\"] in haystack:", "test_policy.py"),
    ("M1.7", "policy.py", "\"EXCEPTION\" if reasons else \"APPROVE\"",
     "\"EXCEPTION\" if len(reasons) > 1 else \"APPROVE\"", "test_policy.py"),
    ("M1.8", "policy.py", "if not rule.get(\"enabled\", True):", "if False:", "test_policy.py"),
    ("M1.9", "policy.py", "spent = ctx[\"spend\"].get(matter, 0)", "spent = 0", "test_policy.py"),

    ("M2.1", "bedrock_sim.py", "for line in lines[:3]:", "for line in lines[:4]:", "test_extract.py"),
    ("M2.2", "bedrock_sim.py", "len(line) > 60", "len(line) >= 60", "test_extract.py"),
    ("M2.3", "bedrock_sim.py", "candidates = preferred or total_lines", "candidates = total_lines",
     "test_extract.py"),
    ("M2.4", "bedrock_sim.py", "confidence -= 0.30", "confidence -= 0.25", "test_extract.py"),
    ("M2.5", "bedrock_sim.py", "    if len(total_lines) > 1:\n        confidence",
     "    if len(total_lines) > 2:\n        confidence", "test_extract.py"),
    ("M2.6", "bedrock_sim.py", "max(confidence, 0.05)", "max(confidence, 0.0)", "test_extract.py"),
    ("M2.7", "bedrock_sim.py", "if TOTAL_LABEL.search(line) or not line.strip():",
     "if not line.strip():", "test_extract.py"),
    ("M2.8", "bedrock_sim.py", "if \"--- INVOICE ---\" in text:", "if False:", "test_extract.py"),
    ("M2.9", "bedrock_sim.py", "head = head[len(code):].strip()", "head = head", "test_extract.py"),

    ("M3.4", "store.py", "entry.get(\"ts\") or time.time()", "time.time()", "test_store.py"),
    ("M3.5", "store.py", "self.client.lrem(EXCEPTION_QUEUE, 1, raw)", "pass", "test_store.py"),
    ("M3.6", "store.py", "return list(reversed(out))", "return out", "test_store.py"),

    ("M4.1", "verify.py", "TOLERANCE = 0.01", "TOLERANCE = 0.02", "test_verify.py"),
    ("M4.2", "verify.py", "min(reported, CAP) if problems else reported", "reported", "test_verify.py"),
    ("M4.3", "verify.py", "if amount is not None and round(amount, 2) not in amounts_in(document):",
     "if False:", "test_verify.py"),
    ("M4.4", "verify.py", "re.findall(MONEY, document)", "re.findall(r\"[0-9][0-9,]*[.][0-9]{2}\", document)",
     "test_verify.py"),
    ("M4.5", "verify.py", "min(max(float(reported), 0.0), 1.0)", "float(reported)", "test_verify.py"),
    ("M4.6", "verify.py", "elif items and amount is not None:", "elif amount is not None:", "test_verify.py"),
    ("M4.7", "verify.py", "if any(not _number(i.get(\"amount\")) for i in items):", "if False:",
     "test_verify.py"),

    ("M5.1", "gemini.py", "for p in parts if not p.get(\"thought\")", "for p in parts", "test_gemini.py"),
    ("M5.2", "gemini.py", "meta.get(\"totalTokenCount\", 0) - in_tok", "meta.get(\"totalTokenCount\", 0)",
     "test_gemini.py"),
    ("M5.3", "chain.py", "except gemini.GeminiError as exc:", "except ValueError as exc:", "test_gemini.py"),
    ("M5.4", "chain.py", "    finally:\n        _local.offline = False", "    finally:\n        pass",
     "test_gemini.py"),
    ("M5.5", "chain.py", "result[\"fields\"] = verify.verify(result[\"fields\"], document)", "pass",
     "test_gemini.py"),
    ("M5.6", "gemini.py", "if not parts:", "if parts is None:", "test_gemini.py"),
]


def run(mutant):
    mid, filename, old, new, tests = mutant
    work = tempfile.mkdtemp(prefix="soren-mut-")
    try:
        shutil.copytree(ROOT, work, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns(".venv", ".git", "__pycache__"))
        path = os.path.join(work, filename)
        source = open(path).read()
        assert source.count(old) == 1, "%s: pattern must match exactly once" % mid
        open(path, "w").write(source.replace(old, new))
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider",
             os.path.join("tests", tests)],
            cwd=work, capture_output=True, text=True)
        return result.returncode != 0
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main():
    killed = 0
    for mutant in MUTANTS:
        dead = run(mutant)
        killed += dead
        print("%-5s %-15s %s" % (mutant[0], mutant[1], "killed" if dead else "SURVIVED"))
    print("%d/%d killed" % (killed, len(MUTANTS)))
    return 0 if killed == len(MUTANTS) else 1


if __name__ == "__main__":
    sys.exit(main())
