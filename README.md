# JobRadar

Radar local de vacantes + CV a la medida para ATS.

## ¿Qué es?

JobRadar es una aplicación **local** (corre en tu computadora, datos en tu disco) que:

1. **Descubre vacantes** recientes publicadas en portales de reclutamiento de empresas (Greenhouse, Lever y, como extra, Workday) **antes** de que lleguen a LinkedIn.
2. Las **guarda en SQLite** y las muestra en un dashboard con filtros.
3. **Puntúa la compatibilidad** de cada vacante contra tu CV maestro usando un LLM.
4. Para las vacantes que te interesan, genera un **CV optimizado para ATS** (PDF/DOCX) y un **mensaje de postulación** específico para esa empresa.
5. Lleva el **seguimiento del estado** de cada postulación.

**Tú envías cada postulación manualmente.** La app prepara todo y te deja listo para copiar, pegar y subir.

## Instalación

```bash
# Clona el repositorio
git clone <url>
cd puestos-laborales

# Instala dependencias con uv
uv sync
```

## Uso básico

```bash
# Ver comandos disponibles
uv run jobradar --help

# Validar una empresa (probe)
uv run jobradar probe greenhouse <slug>
uv run jobradar probe lever <slug>

# Ingesta de vacantes
uv run jobradar ingest

# Scoring de compatibilidad
uv run jobradar score --limit 20

# Ver keywords y knockouts
uv run jobradar requirements --job-id 123

# Generar CV adaptado + mensaje
uv run jobradar tailor --job-id 123

# Verificar PDF/DOCX contra checklist ATS
uv run jobradar ats-check --job-id 123

# Descubrir nuevas empresas de reclutamiento (Brave Search API)
uv run jobradar discover 'site:boards.greenhouse.io "analista financiero" Monterrey' --limit 10

# Abrir dashboard Streamlit
uv run jobradar dashboard
```

## Descubrimiento de empresas (Fase 7)

Ayuda a ampliar `config.yaml` sin buscar portales a mano.

```bash
uv run jobradar discover "<consulta>" --limit 10
```

Qué hace:

1. Consulta la **Brave Search API** con la consulta que le pases (por ejemplo
   `site:boards.greenhouse.io "analista financiero" Monterrey`).
2. Extrae los slugs de los portales encontrados: `boards.greenhouse.io`,
   `job-boards.greenhouse.io`, `jobs.lever.co` y `myworkdayjobs.com`.
3. Valida cada candidata con `probe` y muestra cuántas vacantes tiene.
4. Imprime un bloque YAML de ejemplo. **Nunca** modifica `config.yaml`: tú
   decides qué añadir.

Límites y cortesía:

- Máximo 1 request por segundo.
- `discovery.max_queries_per_run` (por defecto `5`) corta la corrida si se
  supera; `discovery.cache_ttl_hours` (por defecto `24`) reutiliza resultados.
- Requiere `BRAVE_SEARCH_API_KEY` en `.env` (key gratuita en
  <https://search.brave.com/>). Sin la key el comando sale con código 1 y un
  mensaje claro, sin tocar la red.

La misma función está disponible en el dashboard, página **Descubrimiento**.

## Dashboard

El dashboard Streamlit proporciona una interfaz gráfica para:

1. **Vacantes**: tabla con filtros (texto, empresa, fuente, ubicación/remoto, rango de fechas, estado, solo abiertas), detalle completo e historial de eventos.
2. **Seguimiento**: conteo por estado, notas, fecha de postulación, recordatorios de postulaciones sin respuesta y exportación a CSV.
3. **Configuración**: empresas, filtros y proveedor LLM en solo lectura (se editan en `config.yaml`).
4. **Descubrimiento**: empresas candidatas vía Brave Search, validadas con `probe` y con el bloque YAML listo para copiar.

Para acceder al dashboard, ejecuta:

```bash
uv run jobradar dashboard
```

## Configuración

1. Copia `config.yaml` y ajusta tus filtros, empresas objetivo y modelo LLM.
2. Copia `.env.example` a `.env` y agrega tus claves:
   - `ANTHROPIC_API_KEY` (si usas provider: anthropic)
   - `NVIDIA_API_KEY` (si usas provider: nvidia — modelo gratuito, key en https://build.nvidia.com/)
   - `BRAVE_SEARCH_API_KEY` (opcional, para `jobradar discover` — key gratuita en https://search.brave.com/)
   - O configura Ollama localmente (provider: ollama)
3. Copia `examples/cv_master.example.yaml` a `data/cv_master.yaml` y completa con tus datos reales.

## Privacidad

- **Datos personales nunca salen de tu máquina**: `data/` (CV maestro, SQLite, cache) y `.env` (API keys) están en `.gitignore`.
- **Solo el texto enviado al LLM** que configures sale de la máquina (documentado en el README).
  - Con **Nvidia NIM**: el texto se envía a los servidores de Nvidia. Verifica sus términos de privacidad.
  - Con **Ollama local**: nada sale de tu máquina (100% privado).
- **Descubrimiento de empresas** (`jobradar discover`): lo único que sale es la
  consulta de búsqueda que escribes, enviada a la Brave Search API. No se envían
  tu CV, tus vacantes ni tus postulaciones.
- No hay telemetría, ni servicios en la nube propios, ni subida de datos a repositorios.
- Logging a `data/logs/` sin CV ni API keys.

## Metodología ODD

Este proyecto sigue la metodología **ODD (Opencode-Driven Development)**. Las tareas y su seguimiento están en `odd/tasks/`:

- `odd/tasks/fase-0-esqueleto.md` — Fase 0 completada (esqueleto del proyecto)
- `odd/tasks/fase-7-descubrimiento.md` — Fase 7 (descubrimiento de empresas + capa de consultas)
- Fases 1 a 6 implementadas según `PLAN.md`

## Stack tecnológico

Ver `AGENTS.md` sección 3 para la lista completa. Resumen:
- Python 3.11+, uv
- httpx, SQLAlchemy 2.x + alembic, pydantic v2
- Streamlit, Anthropic SDK, Ollama (opcional), Nvidia NIM (opcional, API gratuita con key)
- Jinja2 + WeasyPrint (PDF), python-docx (DOCX)
- pdfplumber (verificación ATS)
- pytest, ruff, mypy

## Calidad

```bash
uv run pytest && uv run ruff check . && uv run mypy src
```

## API Reference (campos reales documentados)

### Greenhouse (`boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true`)

**Respuesta:** `{ "jobs": [...] }` — 24 jobs para `medsien`

**Campos clave por job:**
| Campo | Tipo | Notas |
|-------|------|-------|
| `id` | integer | ID único de la vacante (ej: 5274077007) |
| `title` | string | Título del puesto |
| `location.name` | string | Ubicación (ej: "United States", "Istanbul, Turkey") |
| `first_published` | ISO 8601 | **Fecha de publicación original** (ej: "2024-11-04T07:05:50-05:00") |
| `updated_at` | ISO 8601 | **Fecha de última actualización** (ej: "2026-09-10T02:59:06-04:00") |
| `absolute_url` | string | URL pública para postularse |
| `content` | string | Descripción completa **HTML escapado** (contiene `<p>`, `<ul>`, `<li>`, `<strong>`, etc.) |
| `departments[]` | array | Deptos con `id`, `name` |
| `offices[]` | array | Oficinas con `id`, `name`, `location` |
| `requisition_id` | string | ID interno de requisición |
| `internal_job_id` | integer | ID interno alternativo |
| `education` | string | "education_required" / "education_optional" |
| `language` | string | "en" |
| `data_compliance` | array | GDPR info |

**Importante para ingesta:** Usar `first_published` como fecha de publicación (original) y `updated_at` para detectar actualizaciones. El `content` viene HTML-escaped → requiere unescape antes de usar.

---

### Lever (`api.lever.co/v0/postings/{slug}?mode=json`)

**Respuesta:** Array directo `[...]` — 18 jobs para `brafton`

**Campos clave por job:**
| Campo | Tipo | Notas |
|-------|------|-------|
| `id` | string (UUID) | ID único (ej: "72674198-21b5-47b9-8358-f240ea108971") |
| `text` | string | Título del puesto |
| `createdAt` | integer | **Epoch milliseconds** (ej: 1789498402141 → 2026-09-15) |
| `categories.location` | string | Ubicación (ej: "Toronto, Ontario", "Netherlands remote") |
| `categories.department` | string | Departamento |
| `categories.team` | string | Equipo |
| `categories.commitment` | string | "Full-Time", "Freelancer", etc. |
| `categories.allLocations` | array | Todas las ubicaciones |
| `hostedUrl` | string | URL pública para postularse |
| `applyUrl` | string | URL de aplicación directa |
| `descriptionPlain` | string | **Descripción en texto plano** (recomendado para LLM) |
| `description` | string | Descripción HTML |
| `descriptionBody` | string | Cuerpo HTML sin opening |
| `descriptionBodyPlain` | string | Cuerpo en texto plano |
| `openingPlain` | string | Intro en texto plano |
| `additionalPlain` | string | Beneficios/info extra en texto plano |
| `lists[]` | array | Secciones estructuradas (ESSENTIAL JOB FUNCTIONS, SKILLS & REQUIREMENTS) |
| `salaryRange` | object | `{min, max, currency, interval}` si disponible |
| `country` | string | Código país ISO (CA, NL, IT, etc.) |
| `workplaceType` | string | "remote", "onsite", "hybrid" |

**Importante para ingesta:** `createdAt` está en **epoch milliseconds** → convertir a datetime UTC. Preferir `descriptionPlain` / `descriptionBodyPlain` para texto limpio. `categories.location` puede ser "Netherlands remote" (string libre).

---

## Licencia

Uso personal. Ver `AGENTS.md` para principios no negociables.