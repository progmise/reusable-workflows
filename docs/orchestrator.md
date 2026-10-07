# Deploy Orchestrator — análisis y diseño progmise

> Estado: **implementado** (2026-10-05) — `orch-ci`/`orch-release`/`orch-deploy`
> + `scripts/topo-deploy.py`, caller repo `progmise/deploy-manifest`.
> Referencias extraídas de `C:\Users\Leonel\Documents\temporal\e\orchester.zip`
> (capturas UI Gluon + workflows + logs) y `flow.zip` (capturas de jobs).

## Qué es el sistema de referencia (Santander / Gluon + OAM + Thunder)

### Gluon — portal web (app web propia)

- Jerarquía: **Compañía → Aplicaciones → Componentes**.
  Cada aplicación tiene código, alias, unidad de negocio, estado, responsables,
  enlaces a Jira/Confluence/GitHub. Cada **componente** mapea a un repo GitHub
  (`sar-apiacc-*`), tiene plantilla asociada (ej. "Santander Spring Boot
  Microservice 2.2.0"), herramientas (GitHub/Sonar/Fortify/Catalog) y
  garantías (SCA, SAST, JavaMicros).
- **Equipo**: miembros con roles (product-owner, technical-lead, developer).
- **Releases**: wizard de 5 pasos — seleccionar componente → info release
  (versión `1.0.93`, producto `7875`, razón New Version/Evolutive, prioridad,
  riesgo, descripción) → info adicional → más info → confirmación con fechas
  planificadas y plataforma (OHE/OpenShift). Genera número `RLSExxxxxxx` y por
  ambiente una task `RTSKxxxxxxx`.
- Lista de releases con estados (implemented / cancelled).

### Repositorio OAM ("Orchestrated Application Manifest")

- Un repo por aplicación (ej. `sar-apiacc-applicationmodel`) que contiene
  `oam-application-definition.yml` con la versión de release y la lista de
  componentes a desplegar: `{name, version, scmUrl, needs[], state}`.

### Workflows del OAM (de los logs)

- **PR → main** (`oam-pr-main-*`): Setup env vars → Validate (linter,
  `version-release-validation` sobre `oam-application-definition.yml` — semver
  y que no exista ya un GitHub Release con ese tag) → OAM version release
  (Get version + Check release) → Validate Threat Modeling.
- **Merge → main** (`merge-main-*`): `OAM Release reusable workflow` →
  Setup env vars → Check Release → **Create Draft release**: lee el OAM file,
  hace topological sort de componentes (`needs`) → genera diagrama Mermaid
  `graph BT` en el step summary → crea el GitHub Release **draft** `1.0.88`.
- **Deploy** (`oam-deploy-pre/pro-*`, workflow `oam-cd.yml@v1`, dispatch con
  `release-version` + `release-number` + `task-number` + `environment`):
  1. `Setup environment variables` — tokens de org/proyecto, properties
     files → JSON de env vars.
  2. `OAM Deployment Orchestration` — acción compuesta "Thunder":
     - `pipeline-frame` (header + correlation-id + métricas OpenSearch)
     - `gluon-release-validation`: valida release en Gluon API, resuelve
       environment en el "trail", resuelve task (estado PENDING, tipo
       `other_deployment`, operación DEPLOY), valida ventana de validez
     - `github-validation`: valida release/tag/draft en GitHub
     - `component-discovery`: consulta component-manager API → componentes
       de la app para esa release/env
     - `matrix-components`: **topological sort por `needs` → niveles**
       (los del mismo nivel despliegan en paralelo) + diagrama Mermaid
     - `deploy-orchestrator`: despliega nivel por nivel con polling de estado
     - `pipeline-frame` (cierre + indexación OpenSearch)
  3. `Notify Deployment`.

## Diseño mínimo para progmise

GitHub ya cubre la mayor parte de la plataforma: **la UI es GitHub mismo**
(Actions = runs, Releases = estados de release). No hace falta front propio.

| Pieza enterprise | Equivalente progmise |
|---|---|
| Release wizard (RLSE/RTSK) | PR al repo manifiesto + GitHub Release |
| `oam-application-definition.yml` | repo `deploy-manifest` con `manifest.yml` |
| Validación de versión/release | `scripts/` + job Validate en `orch-ci.yml` |
| Topo-sort + deploy por niveles | `scripts/topo-deploy.py` + `orch-deploy.yml` |
| deploy-orchestrator + polling | `gh workflow run app-deploy.yml` por repo + poll de conclusión |
| Notify Deployment | Step summary (+ webhook opcional a futuro) |
| Gluon front | `deploy-orchestrator` — SPA React/Vite (UI Gluon-style) + `deploy-orchestrator-api` (Express: GitHub OAuth + allowlist + proxy), containers en Vercel |

### `deploy-manifest` repo (nuevo)

```yaml
# manifest.yml — una "release" desplegable
version: 1.0.0
components:
  - name: loans-api
    repo: progmise/loans-api
    tag: 0.1.0            # tag/imagen a desplegar
    needs: []
  - name: amortization-api
    repo: progmise/amortization-api
    tag: 0.2.0
    needs: [loans-api]    # despliega después
```

### Workflows nuevos en `reusable-workflows`

- `orch-ci.yml` (PR a main del manifiesto): yaml lint, semver, versión sin
  release previo, cada `repo:tag` existe (git ls-remote) e imagen existe en
  Docker Hub.
- `orch-release.yml` (merge a main): topo-sort + Mermaid en summary + crea
  GitHub Release del manifiesto con la versión.
- `orch-deploy.yml` (dispatch `{version, env}`): checkout manifest@version →
  `topo-deploy.py` produce niveles → por nivel, matrix despacha
  `app-deploy.yml` en cada repo (`gh workflow run` con PAT/token) → poll hasta
  conclusión → Summary con diagrama + resultados.
- Callers thin en `deploy-manifest/.github/workflows/`.

### Notas de implementación

- `needs` define orden, no paralelismo obligatorio: mismo nivel = matrix
  paralela (como Thunder).
- El dispatch cross-repo requiere token con `actions:write` en los repos
  consumidores — PAT fine-grained como secret `ORCHESTRATOR_TOKEN` en
  `deploy-manifest` (o GitHub App si crece).
- El "task/ventana de validez" de Gluon se simplifica: el Release del
  manifiesto (draft→published) es el gate; `environment` es input del
  dispatch (`pro` por defecto, extensible a `cert`/`pre` igual que
  `DEPLOY_ENVIRONMENTS`).
- Reusar `app-deploy.yml` existente — ya valida tag + imagen en registry y
  despliega a Vercel por `version`.
- Front: `progmise/deploy-orchestrator` — SPA React/Vite servida por un shell
  Express que proxea `/api/*` a `progmise/deploy-orchestrator-api`
  (`API_UPSTREAM`). La API hace OAuth (client_secret server-side, token del
  usuario en cookie HttpOnly), enforcea `ALLOWED_USERS` y proxea
  `/api/gh/*` a la Actions API con ese token. Ambos deployan como container
  en Vercel (preset `Container`; buildea el `Dockerfile` raíz) vía el
  mismo pipeline `app-*`.

## Pendiente al retomar

1. Crear repo `progmise/deploy-manifest` + `manifest.yml` inicial con
   `loans-api` (y `amortization-api` si migra a workflows `api-*`).
2. `scripts/topo-deploy.py` (topo-sort + emisión de matriz JSON para
   `strategy.matrix`).
3. Los 3 workflows + callers + `v1`.
4. Decidir si `amortization-api` migra de sus workflows actuales a los
   callers `app-*` (requiere variante Gradle en `app-ci`/`build`).
