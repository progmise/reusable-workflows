#!/usr/bin/env bash
# Emits CI telemetry to Grafana Cloud via OTLP/HTTP:
#   - one span per job (real start/end from the Jobs API) -> /v1/traces
#   - gauges: coverage %, trivy/semgrep findings, job durations -> /v1/metrics
# Requires: GH_TOKEN (actions:read), jq, curl. Optional artifacts in ./dl
# (downloaded by the caller). Skips silently without GRAFANA_OTLP_* config.
set -u

if [ -z "${OTLP_ENDPOINT:-}" ] || [ -z "${OTLP_AUTH:-}" ]; then
  echo "GRAFANA_OTLP_* not configured — skipping tracing"
  exit 0
fi

curl -sf -H "Authorization: Bearer $GH_TOKEN" -H "Accept: application/vnd.github+json" \
  "$GITHUB_API_URL/repos/$GITHUB_REPOSITORY/actions/runs/$GITHUB_RUN_ID/jobs?per_page=100" -o jobs.json

nano() { date -d "$1" +%s%N; }

TRACE_ID=$(echo "$GITHUB_RUN_ID$GITHUB_RUN_ATTEMPT$GITHUB_SHA" | sha256sum | cut -c1-32)
NOW=$(date +%s%N)
SPANS="[]"
DUR_POINTS="[]"

while IFS= read -r job; do
  name=$(jq -r .name <<<"$job")
  concl=$(jq -r .conclusion <<<"$job")
  start=$(nano "$(jq -r .started_at <<<"$job")")
  end=$(nano "$(jq -r .completed_at <<<"$job")")
  dur=$(( (end - start) / 1000000000 ))
  status=2
  { [ "$concl" = "success" ] || [ "$concl" = "skipped" ]; } && status=1
  SPANS=$(jq --arg n "$name" --arg t "$TRACE_ID" \
    --arg s "$(echo "$GITHUB_RUN_ID-$name" | md5sum | cut -c1-16)" \
    --arg st "$start" --arg en "$end" --arg r "$concl" --argjson c "$status" --argjson d "$dur" \
    '. + [{traceId:$t,spanId:$s,name:$n,kind:1,startTimeUnixNano:$st,endTimeUnixNano:$en,
          attributes:[{key:"job.result",value:{stringValue:$r}},
                      {key:"job.duration_seconds",value:{doubleValue:$d}}],
          status:{code:$c}}]' <<<"$SPANS")
  DUR_POINTS=$(jq --arg n "$name" --argjson d "$dur" --arg t "$NOW" \
    '. + [{asDouble:$d,timeUnixNano:$t,attributes:[{key:"job",value:{stringValue:$n}}]}]' <<<"$DUR_POINTS")
done < <(jq -c '.jobs[] | select(.name != "tracing" and .completed_at != null)' jobs.json)

# --- gauges from downloaded artifacts (dl/) + job stats ---
GAUGES="[]"
add_gauge() {
  GAUGES=$(jq --arg n "$1" --arg u "$2" --argjson v "$3" --arg t "$NOW" \
    '. + [{name:$n,unit:$u,gauge:{dataPoints:[{asDouble:$v,timeUnixNano:$t}]}}]' <<<"$GAUGES")
}

CSV=$(find dl -name 'jacocoTestReport.csv' 2>/dev/null | head -1)
if [ -n "$CSV" ]; then
  add_gauge "ci.coverage.percent" "%" \
    "$(awk -F',' 'NR>1 {lm+=$8; lc+=$9} END {printf "%.1f", (lc+lm)? lc/(lc+lm)*100 : 0}' "$CSV")"
fi
TRIVY_JSON=$(find dl -name 'trivy-results.json' 2>/dev/null | head -1)
if [ -n "$TRIVY_JSON" ]; then
  add_gauge "ci.trivy.findings" "1" "$(jq '[.Results[]?.Vulnerabilities[]?] | length' "$TRIVY_JSON")"
fi
SEMGREP_JSON=$(find dl -name 'semgrep-results.json' 2>/dev/null | head -1)
if [ -n "$SEMGREP_JSON" ]; then
  add_gauge "ci.semgrep.findings" "1" "$(jq '.results | length' "$SEMGREP_JSON")"
fi
add_gauge "ci.jobs.total" "1" "$(jq '[.jobs[] | select(.name != "tracing")] | length' jobs.json)"
add_gauge "ci.jobs.failed" "1" "$(jq '[.jobs[] | select(.name != "tracing" and (.conclusion == "failure" or .conclusion == "cancelled"))] | length' jobs.json)"
GAUGES=$(jq --arg t "$NOW" --argjson pts "$DUR_POINTS" \
  '. + [{name:"ci.job.duration_seconds",unit:"s",gauge:{dataPoints:$pts}}]' <<<"$GAUGES")

RES=$(jq -n --arg repo "$GITHUB_REPOSITORY" --arg wf "$GITHUB_WORKFLOW" \
  --arg sha "$GITHUB_SHA" --arg ref "$GITHUB_REF_NAME" \
  --arg run "$GITHUB_RUN_ID" --arg actor "$GITHUB_ACTOR" \
  '{attributes:[
    {key:"service.name",value:{stringValue:$repo}},
    {key:"ci.workflow",value:{stringValue:$wf}},
    {key:"ci.run_id",value:{stringValue:$run}},
    {key:"vcs.ref",value:{stringValue:$sha}},
    {key:"vcs.branch",value:{stringValue:$ref}},
    {key:"ci.actor",value:{stringValue:$actor}}]}')

jq -n --argjson res "$RES" --argjson spans "$SPANS" \
  '{resourceSpans:[{resource:$res,scopeSpans:[{scope:{name:"github-actions"},spans:$spans}]}]}' \
  | curl -sf -X POST "$OTLP_ENDPOINT/v1/traces" \
      -H "Authorization: Basic $OTLP_AUTH" -H "Content-Type: application/json" -d @-

jq -n --argjson res "$RES" --argjson metrics "$GAUGES" \
  '{resourceMetrics:[{resource:$res,scopeMetrics:[{scope:{name:"github-actions"},metrics:$metrics}]}]}' \
  | curl -sf -X POST "$OTLP_ENDPOINT/v1/metrics" \
      -H "Authorization: Basic $OTLP_AUTH" -H "Content-Type: application/json" -d @-

echo "Telemetry emitted for run $GITHUB_RUN_ID"
