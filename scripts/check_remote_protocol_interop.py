"""Compare Java's conservative simulation subset against actual Python v1 models.
Usage: PYTHONPATH=src python this_script JAVA_TEST_CLASSPATH
No network, credentials, server, or device operations.
"""

import copy
import json
import subprocess
import sys

from swu_happyrun.core.models import AgentHello, JobEvent, JobView

command = ["java", "-cp", sys.argv[1], "org.happyrun.app.remote.protocol.ProtocolInteropMain"]
lines = subprocess.check_output(command + ["emit"], text=True).splitlines()
for model, line in zip((JobView, AgentHello, JobEvent), lines, strict=True):
    model.model_validate_json(line)
base = json.loads(lines[0])
cases = [base]
for key, value in [
    ("revision", True),
    ("revision", 1.5),
    ("revision", "1"),
    ("revision", -1),
    ("job_id", "../bad"),
    ("state", "unknown"),
    ("fence", 0),
]:
    item = copy.deepcopy(base)
    item[key] = value
    cases.append(item)
item = copy.deepcopy(base)
item["unexpected"] = None
cases.append(item)
item = copy.deepcopy(base)
del item["reason_code"]
cases.append(item)
for key, value in [
    ("protocol_version", True),
    ("protocol_version", "1"),
    ("not_before", "0000-01-01T00:00:00Z"),
    ("not_before", "2026-02-30T00:00:00Z"),
    ("deadline", "2026-10-18T00:00:00Z"),
    ("route_revision", "G" * 64),
]:
    item = copy.deepcopy(base)
    item["spec"][key] = value
    cases.append(item)
wire = [json.dumps(case) for case in cases]
expected = []
for line in wire:
    try:
        JobView.model_validate_json(line)
        expected.append("accept")
    except ValueError:
        expected.append("reject")
actual = subprocess.check_output(command, input="\n".join(wire) + "\n", text=True).splitlines()
assert actual == expected, list(zip(actual, expected, strict=False))
assert expected.count("accept") == 1
print(f"PASS: {len(cases)} bidirectional schema cases plus 3 Java-to-Python payloads")
