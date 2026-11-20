# Deploy Orchestrator — análisis y diseño progmise

> Estado: **implementado** (2026-10-05) — `orch-ci`/`orch-release`/`orch-deploy`
> + `scripts/topo-deploy.py`, caller repos `<app>-app-model`.
> Referencias extraídas de `C:\Users\Leonel\Documents\temporal\e\orchester.zip`
> (capturas del portal de referencia + workflows + logs) y `flow.zip` (capturas de jobs).

## Qué es el sistema de referencia (portal empresarial + OAM + orquestador de deploys)

### Portal web (app propia del sistema de referencia) (app web propia)

- Jerarquía: **Compañía → Aplicaciones → Componentes**.
  Cada aplicación tiene código, alias, unidad de negocio, estado, responsables,
  enlaces a Jira/Confluence/GitHub. Cada **componente** mapea a un repo GitHub
  (el repo del componente), tiene plantilla asociada (ej. "Spring Boot
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

- Un repo por aplicación (ej. `<app>-applicationmodel`) que contiene
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
  2. `OAM Deployment Orchestration` — acción compuesta de orquestación:
     - `pipeline-frame` (header + correlation-id + métricas OpenSearch)
     - `release-validation`: valida release en la API del portal, resuelve
       environment en el "trail", resuelve task (estado PENDING, tipo
       `other_deployment`, operación DEPLOY), valida ventana de validez
     - `github-validation`: valida release/tag/draft en GitHub
     - `component-discovery`: consulta component-manager API → componentes
       de la app para esa release/env
     - `matrix-components`: **topological sort por `needs` → niveles**
       (los del mismo nivel despliegan en paralelo) + diagrama Mermaid
     - `deploy-orchestration`: despliega nivel por nivel con polling de estado
     - `pipeline-frame` (cierre + indexación OpenSearch)
  3. `Notify Deployment`.

## Diseño mínimo para progmise

GitHub ya cubre la mayor parte de la plataforma: **la UI es GitHub mismo**
(Actions = runs, Releases = estados de release). No hace falta front propio.

| Pieza enterprise | Equivalente progmise |
|---|---|
| Release wizard (RLSE/RTSK) | PR al repo manifiesto + GitHub Release |
| `oam-application-definition.yml` | repo `<app>-app-model` (uno por aplicación) |
| Validación de versión/release | `scripts/` + job Validate en `orch-ci.yml` |
| Topo-sort + deploy por niveles | `scripts/topo-deploy.py` + `orch-deploy.yml` |
| deploy-orchestration + polling | `gh workflow run app-deploy.yml` por repo + poll de conclusión |
| Notify Deployment | Step summary (+ webhook opcional a futuro) |
| Portal web | `ensemble-web` — SPA React/Vite + `ensemble-api` (Express: GitHub OAuth + allowlist + proxy), containers en Vercel |

### Repos `<app>-app-model` (uno por aplicación)

```yaml
# oam-application-definition.yml — una "release" desplegable
kind: Application
version: v2
metadata:
  name: loans
  version: 1.2.0
environments:              # targets declarados
  - name: pro
    type: production
    infrastructures:       # infra nested por ambiente (modelo OAM)
      - id: loans-api-pro  # equivalente al ci_id del sistema de referencia
        type: vercel       # vercel | artifact-store | ...
        properties:        # campos del provider (como OAM)
          project: loans-api
          credentialsId: VERCEL_TOKEN   # nombre del secret en el consumer
components:
  - name: loans-api-cm
    repo: progmise/loans-api-cm
    version: 0.1.0        # tag/imagen a desplegar (rollback_version opcional)
    type: configmap       # default: app — CM despacha con `project` y sin docker check
    needs: []
  - name: loans-api
    repo: progmise/loans-api
    version: 0.1.0
    rollback_version: 0.0.9
    needs: [loans-api-cm] # el config aterriza antes que el app
  - name: amortization-api
    repo: progmise/amortization-api
    version: 0.2.0
    needs: [loans-api]    # despliega después
# El binding componente -> ci_id vive en cada repo consumidor:
# .deploy/cd/{cert,pre,pro}/cd.yml  (lista de - ci_id: ...)
# components[].infra queda como override opcional de compatibilidad.
```

### Workflows nuevos en `reusable-workflows`

- `orch-ci.yml` (PR a main del manifiesto): yaml lint, semver, versión sin
  release previo, cada `repo:tag` existe (git ls-remote) e imagen existe en
  Docker Hub.
- `orch-release.yml` (merge a main): topo-sort + Mermaid en summary + crea
  GitHub Release del manifiesto con la versión.
- `orch-deploy.yml` (dispatch `{version, env, release_no}` — el RLSE del
  dashboard es requerido para `pro`): checkout manifest@version →
  `topo-deploy.py` produce niveles → por nivel, matrix despacha
  `app-deploy.yml` en cada repo (`gh workflow run` con PAT/token) → poll hasta
  conclusión → Summary con diagrama + resultados.
- Callers thin en `<app>-app-model/.github/workflows/`.
- ConfigMap components (`type: configmap`, repos `*-cm` generados desde
  `vercel-configmap-template`): `cm-ci`/`cm-release`/`cm-deploy` — el
  repositorios
  de env-vars por ambiente. Despliegan upserting env
  vars en el proyecto Vercel del app (`infra properties.project`), y el app
  los declara en `needs:` para que el config aterrice antes del deploy.
- Secrets components (`type: secrets`, repos `*-secrets` generados desde
  `vercel-secrets-template`): `sec-ci`/`sec-release`/`sec-deploy` — mismo
  shape que CM pero el repo solo **declara** nombres
  (`secrets/<env>/secrets-<env>.y*ml`); los valores viven en el credential
  store (claves `NAME__ENV`, cargados desde la vista Seguridad del
  dashboard con gate por rol) y el deploy los resuelve y upsert como
  `sensitive` env vars. Misma mecánica de binding/`needs`/`project`.

### Notas de implementación

- `needs` define orden, no paralelismo obligatorio: mismo nivel = matrix
  paralela (como el orquestador de referencia).
- El dispatch cross-repo requiere token con `actions:write` en los repos
  consumidores — PAT fine-grained como secret `ORCHESTRATOR_TOKEN` en
  el repo app-model (o GitHub App si crece).
- El "task/ventana de validez" del sistema de referencia se simplifica: el Release del
  manifiesto (draft→published) es el gate; `environment` es input del
  dispatch (`pro` por defecto, extensible a `cert`/`pre` igual que
  `DEPLOY_ENVIRONMENTS`).
- Reusar `app-deploy.yml` existente — ya valida tag + imagen en registry y
  despliega a Vercel por `version`.
- Front: `progmise/ensemble-web` — SPA React/Vite servida por un shell
  Express que proxea `/api/*` a `progmise/ensemble-api`
  (`API_UPSTREAM`). La API hace OAuth (client_secret server-side, token del
  usuario en cookie HttpOnly), enforcea `ALLOWED_USERS` y proxea
  `/api/gh/*` a la Actions API con ese token. Ambos deployan como container
  en Vercel (preset `Container`; buildea el `Dockerfile` raíz) vía el
  mismo pipeline `app-*`.

## Estado

Implementado: repos `<app>-app-model` (ensemble-app-model, loans-app-model),
`scripts/topo-deploy.py` (topo-sort + matriz JSON), workflows `orch-*` + callers
thin + tag `v1`. El binding a ci_ids lo declara cada consumidor en
`.deploy/cd/{env}/cd.yml`; los componentes sin binding en el ambiente
pedido se saltean en el deploy.
