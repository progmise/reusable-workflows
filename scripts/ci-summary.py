#!/usr/bin/env python3
"""Writes the CI run summary to GITHUB_STEP_SUMMARY: per-job results table,
failed tests, JaCoCo coverage, Trivy and Semgrep findings — all parsed from
the downloaded artifacts under ./dl. Stdout appends to the summary.

Env: JOB_RESULTS (JSON map {job: {result}}) — from toJSON(needs) in the
caller. Stdlib only."""

import csv
import json
import os
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

SCRIPTS_BASE = "https://raw.githubusercontent.com/progmise/reusable-workflows/v1/scripts"


def first(pattern: str) -> Path | None:
    return next(Path("dl").rglob(pattern), None)


def section_failed_tests() -> list[str]:
    try:
        urllib.request.urlretrieve(f"{SCRIPTS_BASE}/junit-summary.py", "junit-summary.py")
        import subprocess
        out = subprocess.run(["python3", "junit-summary.py"], capture_output=True,
                             text=True).stdout
        return out.splitlines()
    except Exception:
        return []


def section_coverage() -> list[str]:
    csv_path = first("jacocoTestReport.csv")
    if not csv_path:
        return []
    with open(csv_path) as f:
        rows = list(csv.DictReader(f))
    covered = sum(int(r["LINE_COVERED"]) for r in rows)
    missed = sum(int(r["LINE_MISSED"]) for r in rows)
    total = covered + missed
    return ["### Coverage",
            f"- Lines: **{covered / total * 100:.1f}%** ({covered}/{total})" if total else "- Lines: 0%"]


def section_trivy() -> list[str]:
    path = first("trivy-results.json")
    if not path:
        return []
    vulns = [v for r in (json.loads(path.read_text()).get("Results") or [])
             for v in (r.get("Vulnerabilities") or [])]
    lines = [f"### Trivy — {len(vulns)} finding(s) (CRITICAL/HIGH)"]
    if vulns:
        lines += ["| Severity | CVE | Package | Installed | Fixed |", "|---|---|---|---|---|"]
        for v in vulns[:20]:
            lines.append(f"| {v['Severity']} | {v['VulnerabilityID']} | {v['PkgName']} "
                         f"| {v.get('InstalledVersion', '?')} | {v.get('FixedVersion') or '—'} |")
        if len(vulns) > 20:
            lines.append(f"| … | and {len(vulns) - 20} more — see `trivy-report` artifact | | | |")
    return lines


def section_semgrep() -> list[str]:
    path = first("semgrep-results.json")
    if not path:
        return []
    results = json.loads(path.read_text()).get("results", [])
    lines = [f"### Semgrep — {len(results)} finding(s)"]
    if results:
        lines += ["| Severity | Rule | Location |", "|---|---|---|"]
        for r in results[:20]:
            lines.append(f"| {r['extra'].get('severity', '?')} | {r['check_id']} "
                         f"| {r['path']}:{r['start']['line']} |")
        if len(results) > 20:
            lines.append(f"| … | and {len(results) - 20} more — see `semgrep-report` artifact | |")
    return lines


def main() -> None:
    results = json.loads(os.environ.get("JOB_RESULTS", "{}"))
    labels = {"build": "Build + Test", "trivy": "Trivy (SCA + secrets)",
              "semgrep": "Semgrep (SAST)"}

    lines = ["### CI Checks results", "| Job | Result |", "|---|---|"]
    lines += [f"| {labels.get(job, job)} | {info['result']} |"
              for job, info in results.items()]
    lines += section_failed_tests() + section_coverage() + section_trivy() + section_semgrep()

    with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
