#!/usr/bin/env python3
"""Prints a markdown "### Tests" summary section from JUnit XML reports
found under ./dl (downloaded run artifacts). Stdout is appended to
GITHUB_STEP_SUMMARY by the caller. Stdlib only."""

import glob
import xml.etree.ElementTree as ET

total = failed = 0
rows = []
for path in glob.glob("dl/**/TEST-*.xml", recursive=True):
    suite = ET.parse(path).getroot()
    total += int(suite.get("tests", 0))
    failed += int(suite.get("failures", 0)) + int(suite.get("errors", 0))
    for case in suite.iter("testcase"):
        for elem in case:
            if elem.tag in ("failure", "error"):
                msg = (elem.get("message") or "").replace("\n", " ")[:100]
                rows.append((suite.get("name", "?"), case.get("name", "?"), msg))

if total:
    print(f"### Tests — {total} run, **{failed} failed**")
    if failed:
        print("| Suite | Test | Error |")
        print("|---|---|---|")
        for r in rows[:20]:
            print("| " + " | ".join(r) + " |")
        if len(rows) > 20:
            print(f"| … | and {len(rows) - 20} more — see `test-reports` artifact | |")
