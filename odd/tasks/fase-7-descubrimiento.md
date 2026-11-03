# Fase 7 — Descubrimiento de empresas + reparación de la capa de consultas

Objetivo: cerrar la Fase 7 de `PLAN.md` (descubrimiento de empresas vía API de
búsqueda) y dejar el proyecto cumpliendo la Definición de Terminado de
`AGENTS.md` §14: tests verdes, `ruff` y `mypy` limpios.
Rama: `main` (el usuario autorizó cerrar la fase; los commits quedan a su criterio).
Runner: `uv run pytest`, `uv run ruff check .`, `uv run mypy src`.

## Specs

### S1 — Cliente de descubrimiento (Brave Search API)
`src/jobradar/company_discovery.py` expone `CompanyDiscoveryClient`.

- **Contrato congelado** (lo consume `cli.py` y `app/dashboard.py`):
  - `CompanyDiscoveryClient(api_key: str | None = None)`
  - `.discover_companies(query: str, max_results: int = 10) -> list[dict[str, str]]`
  - Cada resultado tiene exactamente las claves: `slug`, `source`,
    `company_name`, `url`, `source_url`, `description`.
- La API key se lee de `BRAVE_SEARCH_API_KEY` (solo `.env`). Si falta, lanza
  `ValueError` cuyo mensaje contiene `BRAVE_SEARCH_API_KEY`.
- Errores de red/HTTP y exceso de consultas lanzan `RuntimeError` con mensaje
  legible. Nunca se imprime ni se loguea la key.
- Rate limit: máximo 1 request por segundo (por proceso).
- Caché en memoria por `(query, max_results)`.
- Extracción de slugs, soportando:
  - `boards.greenhouse.io/{slug}` → source `greenhouse`
  - `job-boards.greenhouse.io/{slug}` → source `greenhouse`
  - `jobs.lever.co/{slug}` → source `lever`
  - `myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs` → source `workday`, slug = tenant
  - Cualquier otra URL → `None`
- Deduplicación por `(source, slug)`.

### S2 — Límite de consultas por corrida y caché (PLAN Fase 7, tarea 4)
`config.yaml` incorpora:

```yaml
discovery:
  max_queries_per_run: 5
  cache_ttl_hours: 24
```

`Settings.discovery` (pydantic) con esos dos campos y defaults `5` y `24`.
Superar `max_queries_per_run` en una instancia del cliente lanza `RuntimeError`
con un mensaje que menciona `max_queries_per_run`. La caché respeta
`cache_ttl_hours` (una entrada más vieja se vuelve a consultar).

### S3 — CLI `jobradar discover`
`uv run jobradar discover "<consulta>" --limit N`.

- Imprime una tabla: `#`, empresa, fuente, slug, vacantes.
- El conteo de vacantes viene de `probe_company(...)` y, si falla, se muestra
  `? (motivo)` sin abortar.
- **Nunca** escribe `config.yaml`; al final imprime el snippet YAML de ejemplo.
- Errores de configuración (`ValueError`) y de ejecución (`RuntimeError`) se
  muestran en rojo y salen con código 1.

### S4 — Página "Descubrimiento" del dashboard (PLAN Fase 7, tarea 3)
`app/dashboard.py` implementa la página ya declarada en el menú lateral.

- Campo de consulta + botón "Buscar empresas".
- Tabla de empresas candidatas con: empresa, fuente, slug, vacantes
  (`probe_company`), y la URL del portal.
- Snippet YAML listo para copiar (`st.code`) para añadir la empresa elegida.
- **Nunca** modifica `config.yaml` automáticamente (humano en el circuito).
- Si falta `BRAVE_SEARCH_API_KEY`, muestra `st.error` con la instrucción y no
  revienta.
- Usa `st.rerun()` (Streamlit moderno), no `st.experimental_rerun()`.

### S5 — Capa de consultas del dashboard en la librería (AGENTS.md §12)
Toda la lógica vive en `src/jobradar/dashboard_queries.py`; `app/dashboard.py`
solo pinta.

- Prohibido importar `jobradar.storage` (no existe). Todo se implementa con
  SQLAlchemy 2.x sobre `jobradar.db.models`.
- `JobFilters` (pydantic): `search_text`, `company`, `source`, `location`,
  `remote`, `date_from`, `date_to`, `status`, `only_open`, todos opcionales con
  default neutro.
- `get_filtered_jobs(filters: JobFilters, last_visit: datetime | None) -> list[Job]`
  aplica los filtros en SQL y marca `job.is_new = True` cuando
  `posted_at > last_visit`.
- `Job` expone `is_new` como atributo Python no mapeado, tipado, con default
  `False` (usar `__allow_unmapped__ = True` en el modelo). No es columna.
- `get_job_details`, `get_job_events`, `mark_job_reviewed`, `mark_job_discarded`
  funcionan de verdad contra la sesión (sin indirecciones inexistentes) y
  registran `Event` de tipo `status_change` con `old`/`new`.
- `export_jobs_to_csv() -> str` exporta `job_id, titulo, empresa, fuente,
  estado, fecha_publicacion, fecha_aplicacion, notas` tomando `applied_at` y
  `notes` de `Application` cuando exista.
- `get_jobs_by_status()`, `get_all_jobs_with_status(status_filter: str | None)`,
  `get_jobs_without_response(days: int)` devuelven datos reales (incluyendo
  `applied_at` cuando hay `Application`).
- `get_application_notes` / `set_application_notes` persisten `Application.notes`
  (crear la fila si no existe y hay notas que guardar).
- `mark_job_applied(job_id)` es idempotente-hostil: si ya hay `Application`
  lanza `ValueError`; si no, marca `JobStatus.APPLIED`, crea `Application` con
  `applied_at` y registra evento.
- La fábrica de sesiones debe poder inyectarse en tests sin tocar
  `data/jobradar.sqlite` (por ejemplo `_session_factory` a nivel de módulo,
  monkeypatcheable).

### S6 — Tests sin red ni tokens
- `tests/test_company_discovery.py` prueba `CompanyDiscoveryClient` con `httpx`
  mockeado: init con/sin key, extracción de los 4 tipos de slug, URL no
  reconocida, dedupe, caché, límite de consultas, error HTTP → `RuntimeError`.
- `tests/test_dashboard_queries.py` se reescribe contra las APIs reales usando
  SQLite en memoria (`tmp_path` / `sqlite://`), sin red.
- `tests/test_ats_check.py`: la aserción del DOCX correcto debe coincidir con el
  mensaje real (`"correcta"`), sin variables de bucle sin usar.
- `tests/test_workday.py` termina con salto de línea.
- `ruff check .` y `mypy src` sin errores.

## Tasks

- [x] T1 — S1, S2, S3 (inline) — `src/jobradar/company_discovery.py`, `src/jobradar/config.py`, `config.yaml`, `src/jobradar/cli.py`, `tests/test_company_discovery.py` (18 tests). Sin commit.
- [x] T2 — S4, S5, S6 (inline) — `src/jobradar/dashboard_queries.py`, `app/dashboard.py`, `src/jobradar/db/models.py`, `src/jobradar/ingest.py`, `tests/test_dashboard_queries.py` (31 tests), `tests/test_ats_check.py`, `tests/test_workday.py`, `pyproject.toml`. Sin commit.
- [x] T3 — README §Descubrimiento, §Privacidad, §Dashboard, §Configuración, §ODD (inline). Sin commit.
- [x] T4 — Verificación final (inline). Sin commit.

## Log

L1 — Pedido del usuario (2026-10-31): «Actua como Desarrollador FullStack Senior
experto en Python y Streamlit. Termina de realizar la Fase 7. Utiliza subagentes
en simultaneo con skills adecuadas a su tarea (gentle-ai-explore para explorar y
buscar informacion sobre el proyecto / gentle-ai-verify para verificar que las
implementaciones fueron eficientes y que no hay ningun error / gentle-ai-worker
para realizar la codificacion de las tareas que haya en el plan /
gentle-ai-review para revisar cualqueir parte del proyecto / Gentle-Orchestrator
para comandar todos los subagentes anteriores y realizar los planes detallados
de las tareas a realizar). Toma como contexto: @PLAN.md @AGENTS.md»

L2 — Estado observado antes de empezar (evidencia de comandos):
- `uv run pytest --ignore=tests/test_dashboard_queries.py` → 1 failed, 103
  passed, 7 errors.
- `uv run ruff check .` → 34 errores.
- `uv run mypy src` → 11 errores.
- `src/jobradar/dashboard_queries.py` importa `jobradar.storage`, módulo
  inexistente; `app/dashboard.py` pasa campos inexistentes a `SearchConfig` y usa
  `st.experimental_rerun`.
- `tests/test_company_discovery.py` era una copia de los tests de Workday.

L3 — Decisión de alcance: la reparación de `dashboard_queries.py` /
`app/dashboard.py` entra en esta fase porque sin ella no se cumple la
Definición de Terminado (ruff/mypy limpios) y porque S4 depende de esa capa.

L4 — Delegación intentada y no viable. Se lanzó `gentle-ai-worker` para T1 y
devolvió un resultado vacío sin tocar archivos (verificado con `git status` y
lectura del archivo). Después `gentle-ai-verify` falló con errores del
proveedor de modelos (402 Insufficient Balance en deepseek, 413 TPM en groq,
404 en nvidia), `gentle-ai-review` fue denegado por las reglas de permisos del
runtime y `review-risk` exige un binding de revisión emitido por el proveedor.
Conclusión: en este runtime no hay subagentes utilizables, así que T1-T4 se
ejecutaron inline. No se inventó verificación independiente.

L5 — Evidencia de cierre (comandos observados):
- `uv run pytest -q` → `152 passed`.
- `uv run ruff check .` → `All checks passed!`.
- `uv run mypy src` → `Success: no issues found in 27 source files`.
- `uv run python -c "load_config().discovery"` → `max_queries_per_run=5 cache_ttl_hours=24`.
- `uv run jobradar discover "test" --limit 1` sin key → mensaje claro, `exit=1`, sin red.
- Smoke con `streamlit.testing.v1.AppTest` sobre las 4 páginas del dashboard →
  `[OK] Vacantes`, `[OK] Seguimiento`, `[OK] Configuración`, `[OK] Descubrimiento`.

L6 — Hallazgo relevante: `re.compile(r"boards\.greenhouse\.io/...")` también
coincide con `job-boards.greenhouse.io/...` porque la segunda cadena contiene a
la primera. Por eso `_JOB_BOARDS_PATTERN` se evalúa primero y hay un test que lo
fija.

L7 — `gentle-ai review assess` devolvió `risk: high`, `review_due: true`,
`review_due_reason: high_risk`, con `unassessable` porque hay 22 archivos sin
trackear. No se inició el ciclo de revisión: el candidato válido es un commit de
unidad de trabajo o un slice de PR, y las fases 1-6 siguen sin commit, así que
el límite del slice lo decide el usuario. Estado: **Needs your decision**.

L8 — El usuario aprobó armar los commits por fase. Se crearon 9 slices sobre
`main` (árbol limpio, sin push):

| Commit | Archivos | Líneas (add+del) |
|---|---|---|
| `ac02693` fase-0: evidencia de cierre | 1 | 19 |
| `a448843` fase-1: ingesta + prefiltro + tests | 7 | 689 |
| `4d1f62b` fase-2: capa de consultas del dashboard | 3 | 867 |
| `b05462e` fase-3: Nvidia NIM + factory + scoring | 5 | 396 |
| `57c6d77` fase-4a: keywords ATS + knockouts | 5 | 567 |
| `fb987d4` fase-4b: tailoring + validador | 4 | 712 |
| `95d408a` fase-4c: render + ats_check | 5 | 1052 |
| `37d4b4c` fase-6: Workday | 6 | 527 |
| `89044a7` fase-7: descubrimiento + integración CLI/dashboard | 9 | 1704 |

`config.yaml` se partió por hunk: el bloque `llm` (nvidia) fue a fase-3 y el
bloque `discovery` a fase-7. Cada slice se validó extrayendo su árbol con
`git archive` y comprobando que los módulos que toca importan sin error: 9/9 OK.
Suite final: 152 tests, ruff y mypy limpios.

L9 — Semántica de `gentle-ai review assess --base-ref X --committed-only`
(verificada): el candidato es **X..HEAD**, no un commit aislado. Un slice
intermedio solo se puede revisar retroactivamente con HEAD situado en ese
commit. Todos los slices salieron `risk: high` con
`reasons=[{code: process_boundary, path: src/jobradar/cli.py, detail: signal:
shell_process}]` porque `cli.py` ejecuta `subprocess.run` (comando `dashboard`)
y entra en el rango. El tier no distingue tamaño ni contenido del slice.

L10 — Deuda detectada y NO corregida (fuera de alcance de esta fase):
`src/jobradar/ats_keywords.py:extract_requirements` es un **placeholder** que
devuelve `keywords: []` y `knockouts: []`. Por eso `jobradar requirements` y
`jobradar tailor` no producen keywords reales: falta cablear el LLM de
extracción con `prompts/ats_extract_v1.md`. Además, `src/jobradar/prompts/`
está trackeado y muerto: el código lee `prompts/` desde la raíz del repo, así
que los comandos dependen del cwd. Ambas cosas quedan pendientes de decisión.

L11 — Slice posterior a la Fase 7 (2026-11-01). Sobre HEAD `5e13cd6` quedó un
slice sin commitear con: descubrimiento multi-proveedor (`src/jobradar/
discovery/` con `base`, `brave`, `google_cse`, `serper`, `factory`),
orquestación de postulaciones (`src/jobradar/applications.py`), página
"Preparar postulación" del dashboard, cableado real de la extracción ATS con
LLM (`extract_requirements`/`ensure_requirements` con reintento, validación
pydantic y caché en `job_requirements`) y tests nuevos
(`test_applications.py`, `test_ats_extraction.py`, `test_discovery_providers.py`).

Decisiones tomadas en este slice:
- La deuda L10 quedó resuelta: los prompts canónicos viven en
  `src/jobradar/prompts/` (AGENTS.md §4/§8.3), con el contenido rico antes
  ubicado en la raíz. `prompts/` de la raíz se eliminó.
- `src/jobradar/paths.py` expone `PROMPTS_DIR` y `prompt_path(name)`; los tres
  consumidores (`ats_keywords`, `scoring`, `tailoring`) resuelven sus prompts
  de forma relativa al paquete, sin depender del cwd.
- Se agregó `tests/test_scoring.py` (6 tests: caché, persistencia, invalidación
  por `prompt_version`, tipo inválido, límites del esquema, hash del CV), que
  cierra el hueco "sin tests de scoring" de la Fase 3.
- Se agregó `tests/test_prompts.py` (6 tests): existencia, placeholders,
  `PROMPT_PATH` dentro del paquete y carga tras `chdir(tmp_path)`.

Evidencia de verificación observada:
- `uv run pytest -q` → `213 passed`.
- `uv run ruff check .` → `All checks passed!`.
- `uv run mypy src` → `Success: no issues found in 35 source files`.
- Smoke `streamlit.testing.v1.AppTest` sobre las 5 páginas del dashboard →
  `[OK] Vacantes`, `[OK] Seguimiento`, `[OK] Preparar postulación`,
  `[OK] Configuración`, `[OK] Descubrimiento`.

Nota de runtime: se intentó delegar la implementación a `gentle-ai-worker` y la
verificación a `gentle-ai-verify`. El worker falló con `403` del proveedor
("model not available in your subscription tier"); la verificación se completó y
reportó un falso positivo (marcó como "stale" el comentario correcto
`src/jobradar/prompts/ats_extract_v1.md`). El slice se implementó inline y se
verificó con los comandos de arriba. Sin commit.

L12 — Integración de scoring en CLI y dashboard (2026-11-01). Se cerraron dos
huecos de AGENTS.md §8.4 y §10.1:

- Tope de costo: `resolve_run_limit(limit, configured)` en `scoring.py`;
  `score_pending(limit=None)` resuelve contra `llm.max_jobs_per_run` y devuelve
  `limit` en el resultado. `jobradar score --limit` pasó a opcional y un valor
  mayor al tope se recorta (antes se podía pedir `--limit 1000` y gastar de más).
- Dashboard: `get_scores_for_jobs()` (una sola consulta, último score por
  vacante) y `run_scoring()` en `dashboard_queries.py`; la página **Vacantes**
  muestra columnas **Puntaje** y **Veredicto**, botón **Puntuar pendientes** y
  panel de coincidencias/brechas/alertas en el detalle. Toda la lógica sigue en
  la librería (AGENTS.md §12).
- Bug detectado al smoke-testear: mezclar `int` y `"—"` en la columna Puntaje
  rompía `st.dataframe` con `pyarrow.lib.ArrowTypeError`. Se normalizó a string
  (`"88/100"` / `"—"`).
- Tests nuevos: `resolve_run_limit` (4 casos), `get_scores_for_jobs` (último
  score, claves, lista vacía) y `run_scoring` (delegación con límite).

Evidencia observada: `uv run pytest -q` → `220 passed`; `ruff` → `All checks
passed!`; `mypy src` → `Success: no issues found in 35 source files`; AppTest
5/5 páginas OK. Sin commit.

L13 — Commits del slice (2026-11-01). El usuario aprobó explícitamente armar los
commits. Se partió el trabajo en 4 unidades revisables sobre `main` (sin push):

| Commit | Contenido |
|---|---|
| `3dd14c1` | fase-7: descubrimiento multi-proveedor con serper, brave y google_cse |
| `605d7ea` | fase-4: extracción ATS con LLM, postulaciones y prompts empaquetados |
| `9f27fcb` | fase-3: scoring en dashboard, cap de corrida y documentación |
| `1d5eb5b` | fase-3: tests de integración de scoring en el dashboard |

Verificación posterior a los commits: `uv run pytest -q` → `220 passed`;
`ruff` → `All checks passed!`; `mypy src` → limpio (35 archivos). Árbol limpio.
`gentle-ai review assess --base-ref 5e13cd6 --committed-only` → `risk: medium`,
`review_due: false` (`under_budget`); no se inicia ciclo de revisión.



L14 — Cierre de huecos de AGENTS.md §10 (2026-11-02). El usuario pidió seguir
con los tres faltantes del dashboard: página de detalle dedicada, filtro/orden
por puntaje y estimación de costo antes de puntuar.

- S1 (detalle): nueva página "Detalle de vacante" con descripción, score
  (matches/gaps/red_flags), enlace original e historial de eventos.
- S2 (puntaje): `JobFilters.min_score` + `get_filtered_jobs(..., sort="recientes"|"puntaje")`;
  el sidebar de Vacantes expone "Puntaje mínimo" y "Ordenar por".
- S3 (costo): `estimate_scoring_run()` + `run_cost_estimate()`; Configuración
  muestra pendientes, tope, tokens estimados y costo USD si hay precios.
- `LLMConfig.price_input_per_1k_usd` / `price_output_per_1k_usd` (default 0.0).

Evidencia: `uv run pytest -q` → `224 passed`; `ruff` limpio; `mypy src` limpio
(35 archivos); AppTest 6/6 páginas OK; `estimate_scoring_run()` real →
`{'pending': 1, 'limit': 10, 'to_run': 1, ...}`.

L15 — Fuente Ashby + empresas verificadas (2026-11-02). El usuario pasó una
lista de slugs por ATS. Se validaron con requests reales (1 req/s por host):
la mayoría no vive en el ATS que suponía.

| Fuente | Slugs válidos (vacantes) |
|---|---|
| Greenhouse | cloudflare (470), vercel (89) |
| Lever | despegar (125), kavak (4), fintual (3), lemon (0) |
| Ashby | notion (146), supabase (69), linear (31), resend (14), mural (13), posthog (10), belvo (3) |
| Workday | mercadolibre/globant/despegar/pedidosya → HTTP 422; no se agregan |

Sin ATS público detectado: tiendanube, pomelo, uala, coderhouse, satellogic,
vintasoftware, getonboard, auth0, thoughtbot, devlane, platanus, buk, fintoc,
kushki, cornershop, x-team, naranja-x, bairesdev, cal.

Se implementó `AshbySource` (`src/jobradar/sources/ashby.py`) con fixture real
`tests/fixtures/ashby_linear.json` (31 jobs) y 5 tests. `ingest` real:
**977 vacantes nuevas** (13 empresas; 980 en total en la DB).

Evidencia: `pytest -q` → 229 passed; `ruff` limpio; `mypy src` limpio (36 archivos).

L16 — Bug "Puntuar pendientes no hace nada" (2026-11-02). Causa raíz: el
cliente Nvidia NIM tenía timeout fijo de 30 s y el modelo de escritura
`deepseek-v4.1-flash` no responde ni en 150 s. El scoring hacía 10 llamadas
secuenciales sin progreso visible y los errores solo iban a la consola.

- `NvidiaClient` ahora usa `NVIDIA_TIMEOUT_SECONDS` (default 120).
- `model_writing` pasa a `meta/llama-3.2-90b-vision-instruct` (el único rápido
  y estable en esta cuenta: ~16 s; minimax/nemotron devuelven razonamiento y
  `content` vacío con max_tokens bajos).
- `score_pending(on_progress=...)` reporta avance por vacante y devuelve
  `errors_detail`; el dashboard muestra barra de progreso y expander de errores.
- Vacantes muestra pendientes/tope antes de ejecutar.

Evidencia: `score --limit 1` real → `scored` sin timeout (Test Job y Cloudflare);
`pytest -q` → 229 passed; ruff/mypy limpios.
