# Pipeline flows

Visual map of every reusable workflow — job names match what GitHub renders
in the Actions UI. Consumers only hold thin callers; all logic lives here.

## Who calls what (GitFlow)

```mermaid
flowchart LR
    subgraph API["API repos (loans-api, generated APIs)"]
        A_PR["PR → development/main<br/><code>ci.yml</code> caller"]
        A_PUSH["merge → development/main<br/><code>integration.yml</code> caller"]
        A_REL["dispatch<br/><code>release.yml</code> caller"]
        A_DEP["dispatch<br/><code>deploy.yml</code> caller"]
    end
    subgraph LIB["Lib repos (api-commons, generated libs)"]
        L_PR["PR → development/main<br/><code>ci.yml</code> caller"]
        L_PUSH["merge → development/main<br/><code>integration.yml</code> caller"]
        L_REL["dispatch<br/><code>release.yml</code> caller"]
    end
    subgraph RW["reusable-workflows @v1"]
        RW_ACI[api-ci.yml]
        RW_AIN[api-integration.yml]
        RW_ARE[api-release.yml]
        RW_ADE[api-deploy.yml]
        RW_CI[ci.yml]
        RW_IN[integration.yml]
        RW_RE[release.yml]
    end
    A_PR --> RW_ACI
    A_PUSH --> RW_AIN
    A_REL --> RW_ARE
    A_DEP --> RW_ADE
    L_PR --> RW_CI
    L_PUSH --> RW_IN
    L_REL --> RW_RE
    subgraph MAN["deploy-manifest repo"]
        M_PR["PR → main<br/><code>ci.yml</code> caller"]
        M_PUSH["merge → main<br/><code>release.yml</code> caller"]
        M_DEP["dispatch<br/><code>deploy.yml</code> caller"]
    end
    RW_OCI[orch-ci.yml]
    RW_ORE[orch-release.yml]
    RW_ODE[orch-deploy.yml]
    M_PR --> RW_OCI
    M_PUSH --> RW_ORE
    M_DEP --> RW_ODE
    RW_ODE -. "dispatches deploy.yml<br/>per component repo" .-> A_DEP
```

---

## API pipelines

### `api-ci.yml` — PR checks

```mermaid
flowchart TD
    S[Setup] --> B[Build artifact]
    B --> BI[Build image]
    BI --> SAST[SAST]
    BI --> SCA[SCA]
    BI --> CSA[CSA]
    SAST --> T[Tracing]
    SCA --> T
    CSA --> T
    T --> SUM[Summary]
```

| Job | Does |
|---|---|
| Setup | Prints environment (JDK, Maven/Gradle, event, ref) |
| Build artifact | `./mvnw verify` → uploads `app-jar` + `test-reports` |
| Build image | `docker build` (self-contained Dockerfile) → uploads `image-tarball` |
| SAST | Semgrep over source → `semgrep-report` |
| SCA | Trivy **jar** scan (deps in `BOOT-INF/lib`) + secret scan over source |
| CSA | Trivy scan of the image tarball |
| Tracing | OTLP spans → Grafana Cloud (skipped if not configured) |
| Summary | Job matrix + findings recap in the run summary |

Nested callers can pass `final-report: false` → Tracing/Summary are skipped
inside the call and run once at the outer workflow level.

### `api-integration.yml` — merge to `development`/`main`

```mermaid
flowchart TD
    subgraph CI["CI (api-ci, final-report: false)"]
        C1[Setup → Build artifact → Build image → SAST ‖ SCA ‖ CSA]
    end
    CI --> P[Publish Image]
    P --> DE[Deploy environments]
    DE --> D["Deploy (cert) / (pre) — matrix"]
    DE --> T[Tracing]
    D --> T
    CI --> T
    P --> T
    T --> SUM[Summary]
```

- **Publish Image** pushes to `docker.io/<DOCKER_USERNAME>/<repo>`:
  `:edge` + `:<sha>` on `development`, `:latest` + `:<sha>` on `main`.
- **Deploy environments** reads `vars.DEPLOY_ENVIRONMENTS` and emits the
  non-`pro` entries. **Deploy** is a matrix job over them — with the default
  `["pro"]` the matrix is empty and the job is skipped (prod never deploys
  on merge).
- Skipped when `VERCEL_PROJECT_ID` is not set.

### `api-release.yml` — manual dispatch

```mermaid
flowchart TD
    S[Setup] --> V[Validate]
    V --> CI["CI (api-ci, final-report: false)"]
    V --> P[Publish Image]
    CI --> P
    P --> R[Release]
    V --> R
    R --> T[Tracing]
    S --> T
    V --> T
    CI --> T
    P --> T
    T --> SUM[Summary]
```

- **Validate**: semver, no SNAPSHOT, tag/release doesn't exist yet, version >
  latest release (`validate-release.py --kind api` — no Maven Central check).
- **Publish Image** pushes `:<version>` + `:latest`.
- **Release** creates the git tag + GitHub Release.
- **Never deploys** — production goes through `api-deploy.yml` (or the
  orchestrator) so it stays an explicit, auditable action.

### `api-deploy.yml` — manual dispatch (deploy a released version)

```mermaid
flowchart TD
    S[Setup] --> V[Validate]
    V --> D["Deploy {environment}"]
    D --> T[Tracing]
    T --> SUM[Summary]
```

- Inputs: `version` (must match an existing tag + published image) and
  `environment` (`pro`/`cert`/`pre`, must be listed in
  `vars.DEPLOY_ENVIRONMENTS`).
- Deploys the already-published image to Vercel — `--prod` for `pro`,
  preview for the rest.

---

## Orchestrator pipelines (`deploy-manifest`)

### `orch-ci.yml` — PR on the manifest

```mermaid
flowchart LR
    V["Validate manifest<br/>schema · semver · tags exist<br/>images exist on Docker Hub"] --> P["Deploy plan<br/>(mermaid in summary)"]
```

### `orch-release.yml` — merge to main

```mermaid
flowchart LR
    V[Validate + plan] --> R["draft Release v&lt;version&gt;"]
```

Publishing the draft is the approval gate — `orch-deploy` refuses drafts.

### `orch-deploy.yml` — manual dispatch `{version, environment}`

```mermaid
flowchart TD
    S[Setup] --> D["Deployment Orchestration"]
    D --> T[Tracing]
    T --> SUM[Summary]
    subgraph D2[" "]
        direction LR
        L1["level 1:<br/>dispatch component deploys"] --> L2["level 2:<br/>wait, then dispatch"]
    end
```

`topo-deploy.py deploy` checks out `manifest.yml` at the release tag,
Kahn-sorts components into levels, runs `gh workflow run deploy.yml` on each
component repo (`ORCHESTRATOR_TOKEN`, needs `actions:write`) and polls each
run to conclusion before starting the next level.

## Lib pipelines

### `ci.yml` — PR checks

```mermaid
flowchart TD
    S[Setup] --> B[Build]
    B --> SCA[SCA]
    B --> AC[API Compat]
    B --> SAST[SAST]
    SCA --> T[Tracing]
    AC --> T
    SAST --> T
    T --> SUM[Summary]
```

Build (`verify` + coverage) → SCA (Trivy fs) ‖ API Compat (japicmp vs latest
Central artifact) ‖ SAST (Semgrep) → Tracing → Summary.

### `integration.yml` — merge to `development`

```mermaid
flowchart TD
    CI["CI (ci.yml)"] --> SN[Snapshot]
```

**Snapshot** publishes a `-SNAPSHOT` to Maven Central on every merge.

### `release.yml` — manual dispatch (from `main`)

```mermaid
flowchart TD
    S[Setup] --> V[Validate]
    V --> CI["CI (ci.yml)"]
    V --> CP[Compat]
    CI --> CP
    V --> P[Publish]
    CP --> P
    P --> R[Release]
    R --> T[Tracing]
    S --> T
    V --> T
    CI --> T
    CP --> T
    P --> T
    T --> SUM[Summary]
```

Validate (semver/tag exists/published check) → CI + Compat gate (japicmp
`--gate` fails on semver violations) → Publish to Maven Central (GPG-signed)
→ tag + GitHub Release → Tracing → Summary.

---

## Cross-cutting notes

- **Artifacts**: `app-jar`, `image-tarball`, `test-reports`, `semgrep-report`,
  `trivy-report`, `compat-report` — all uploaded per job, retained by GitHub
  defaults.
- **Tracing/Summary always run** (`if: always()`) so failures still emit
  spans and recap. Nested CI calls suppress their own via `final-report`.
- **Empty matrix = failure** on GitHub — that's why `api-integration`
  guards `deploy` with `envs != '[]'` and `api-deploy` takes a single env.
- Secrets never reach logs; `GRAFANA_OTLP_AUTH` only goes into the OTLP
  `Authorization` header.
