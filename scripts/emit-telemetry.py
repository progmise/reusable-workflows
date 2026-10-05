#!/usr/bin/env python3
"""Emit CI telemetry to Grafana Cloud via OTLP/HTTP (stdlib only).

- one span per job (real start/end from the Jobs API) -> /v1/traces
- gauges: coverage %, trivy/semgrep findings, job durations -> /v1/metrics

Requires env: GITHUB_API_URL, GITHUB_REPOSITORY, GITHUB_RUN_ID,
GITHUB_RUN_ATTEMPT, GITHUB_SHA, GITHUB_REF_NAME, GITHUB_WORKFLOW,
GITHUB_ACTOR, GH_TOKEN. Optional artifacts live under ./dl.
Skips silently without GRAFANA_OTLP_ENDPOINT / GRAFANA_OTLP_AUTH.
"""

import csv
import hashlib
import json
import os
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

OTLP_ENDPOINT = os.environ.get("OTLP_ENDPOINT", "")
OTLP_AUTH = os.environ.get("OTLP_AUTH", "")


def post(path: str, payload: dict) -> None:
    req = urllib.request.Request(
        f"{OTLP_ENDPOINT}{path}",
        json.dumps(payload).encode(),
        headers={"Authorization": f"Basic {OTLP_AUTH}", "Content-Type": "application/json"},
    )

    urllib.request.urlopen(req).read()


def api_get(url: str) -> dict:
    req = urllib.request.Request(
        url, headers={"Authorization": f"Bearer {os.environ['GH_TOKEN']}",
                      "Accept": "application/vnd.github+json"})

    return json.loads(urllib.request.urlopen(req).read())


def nano(iso_ts: str) -> int:
    dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))

    return int(dt.timestamp() * 1e9)


def attr(key: str, value) -> dict:
    if isinstance(value, str):
        v = {"stringValue": value}
    else:
        v = {"doubleValue": float(value)}

    return {"key": key, "value": v}


def main() -> None:
    if not OTLP_ENDPOINT or not OTLP_AUTH:
        print("GRAFANA_OTLP_* not configured — skipping tracing")

        return

    jobs = api_get(
        f"{os.environ['GITHUB_API_URL']}/repos/{os.environ['GITHUB_REPOSITORY']}"
        f"/actions/runs/{os.environ['GITHUB_RUN_ID']}/jobs?per_page=100"
    )["jobs"]

    trace_id = hashlib.sha256(
        f"{os.environ['GITHUB_RUN_ID']}{os.environ['GITHUB_RUN_ATTEMPT']}{os.environ['GITHUB_SHA']}"
        .encode()).hexdigest()[:32]
    now = str(int(datetime.now(timezone.utc).timestamp() * 1e9))

    spans, dur_points = [], []

    for job in (j for j in jobs if j["name"] != "tracing" and j.get("completed_at")):
        name, concl = job["name"], job["conclusion"]
        start, end = nano(job["started_at"]), nano(job["completed_at"])
        dur = (end - start) // 1_000_000_000
        spans.append({
            "traceId": trace_id,
            "spanId": hashlib.md5(f"{os.environ['GITHUB_RUN_ID']}-{name}".encode()).hexdigest()[:16],
            "name": name, "kind": 1,
            "startTimeUnixNano": str(start), "endTimeUnixNano": str(end),
            "attributes": [attr("job.result", concl), attr("job.duration_seconds", dur)],
            "status": {"code": 2 if concl in ("failure", "cancelled") else 1},
        })
        dur_points.append({"asDouble": float(dur), "timeUnixNano": now,
                           "attributes": [attr("job", name)]})

    gauges = []

    def gauge(name: str, unit: str, value: float, extra_attrs=None) -> None:
        point = {"asDouble": float(value), "timeUnixNano": now}

        if extra_attrs:
            point["attributes"] = extra_attrs

        gauges.append({"name": name, "unit": unit, "gauge": {"dataPoints": [point]}})

    csv_path = next(Path("dl").rglob("jacocoTestReport.csv"), None)

    if csv_path:
        with open(csv_path) as f:
            rows = list(csv.DictReader(f))
            
        covered = sum(int(r["LINE_COVERED"]) for r in rows)
        missed = sum(int(r["LINE_MISSED"]) for r in rows)
        gauge("ci.coverage.percent", "%", covered / (covered + missed) * 100 if covered + missed else 0)

    trivy_path = next(Path("dl").rglob("trivy-results.json"), None)

    if trivy_path:
        results = json.loads(trivy_path.read_text()).get("Results") or []
        gauge("ci.trivy.findings", "1",
              sum(len(r.get("Vulnerabilities") or []) for r in results))

    semgrep_path = next(Path("dl").rglob("semgrep-results.json"), None)

    if semgrep_path:
        gauge("ci.semgrep.findings", "1",
              len(json.loads(semgrep_path.read_text()).get("results", [])))

    others = [j for j in jobs if j["name"] != "tracing"]
    gauge("ci.jobs.total", "1", len(others))
    gauge("ci.jobs.failed", "1",
          sum(1 for j in others if j["conclusion"] in ("failure", "cancelled")))
    gauges.append({"name": "ci.job.duration_seconds", "unit": "s",
                   "gauge": {"dataPoints": dur_points}})

    res = {"attributes": [
        attr("service.name", os.environ["GITHUB_REPOSITORY"]),
        attr("ci.workflow", os.environ["GITHUB_WORKFLOW"]),
        attr("ci.run_id", os.environ["GITHUB_RUN_ID"]),
        attr("vcs.ref", os.environ["GITHUB_SHA"]),
        attr("vcs.branch", os.environ["GITHUB_REF_NAME"]),
        attr("ci.actor", os.environ["GITHUB_ACTOR"])]}
    scope = {"scope": {"name": "github-actions"}}

    post("/v1/traces", {"resourceSpans": [
        {"resource": res, "scopeSpans": [dict(scope, spans=spans)]}]})
    post("/v1/metrics", {"resourceMetrics": [
        {"resource": res, "scopeMetrics": [dict(scope, metrics=gauges)]}]})

    print(f"Telemetry emitted for run {os.environ['GITHUB_RUN_ID']}")


if __name__ == "__main__":
    main()
