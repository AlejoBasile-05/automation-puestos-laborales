# JobRadar: radar local de vacantes + CV a la medida

> Este archivo es la fuente de verdad del proyecto. Léelo completo al iniciar cada sesión.
> El plan por fases está en `PLAN.md`. Trabaja **una fase a la vez** y no avances a la siguiente sin que yo lo apruebe.

## 1. Objetivo

Aplicación **local** (corre en mi computadora, datos en mi disco) que:

1. Descubre vacantes recientes publicadas en portales de reclutamiento de empresas (Greenhouse, Lever y, como extra, Workday) **antes** de que lleguen a LinkedIn.
2. Las guarda en SQLite y las muestra en un dashboard con filtros.
3. Puntúa la compatibilidad de cada vacante contra mi CV maestro usando un LLM.
4. Para las vacantes que me interesan, genera un **CV optimizado para ATS** (PDF/DOCX) y un **mensaje de postulación** específico para esa empresa. Optimizado significa: formato que los sistemas de filtrado leen sin errores, las palabras clave de la vacante que **sí cumplo** escritas de forma literal y natural, y revisión previa de los filtros eliminatorios (años de experiencia, idioma, estudios, etc.).
5. Lleva el seguimiento del estado de cada postulación.

**Yo envío cada postulación manualmente.** La app prepara todo y me deja listo para copiar, pegar y subir.

## 2. Principios no negociables

1. **Nunca inventar experiencia.** El CV generado solo puede usar hechos presentes en `data/cv_master.yaml`. Se valida por código (ver sección 7), no solo con el prompt.
2. **Humano en el circuito.** Prohibido automatizar el envío de formularios, el llenado de portales o la interacción con CAPTCHAs.
3. **Fuentes legítimas.** Solo APIs públicas de vacantes. **No** hacer scraping de Google, LinkedIn ni de ninguna página que lo prohíba. Nota: para el descubrimiento de empresas (Fase 7) se usa una **API comercial de búsqueda** (Serper, Brave o Google CSE) con key propia; eso no es scraping propio, pero cada proveedor tiene sus términos y hay que respetarlos.
4. **Cortesía con los servidores.** Máximo 1 request/segundo por host, `User-Agent` identificable, reintentos con backoff exponencial, respetar `Retry-After`. Cachear respuestas para no repetir peticiones.
5. **Local-first y privacidad.** Nada de telemetría, ni servicios en la nube propios, ni subir datos a repositorios. Lo único que sale de la máquina es el texto enviado a la API del LLM que yo configure y la consulta de búsqueda enviada al proveedor de descubrimiento (ambas documentadas en el README).
6. **Secretos fuera del código.** API keys solo en `.env` (ignorado por git). Nunca en logs.
7. **Reproducible y testeable.** Cada módulo con tests usando *fixtures* de respuestas reales guardadas; los tests no deben hacer llamadas de red ni consumir tokens.
8. **ATS sin trampas.** Se optimiza la legibilidad del archivo, la coincidencia literal de los términos que realmente cumplo y los filtros eliminatorios. Está prohibido: texto oculto, blanco o diminuto; relleno de palabras clave; copiar requisitos de la vacante que no estén respaldados en el CV maestro.

## 3. Stack (no cambiar sin preguntarme)

| Capa | Tecnología |
|---|---|
| Lenguaje | Python 3.11+ |
| Gestor de entorno | `uv` (alternativa: `venv` + `pip`) |
| HTTP | `httpx` (con timeouts explícitos) |
| Base de datos | SQLite con `SQLAlchemy 2.x` + `alembic` para migraciones |
| Validación / esquemas | `pydantic` v2 |
| Dashboard | `Streamlit` |
| LLM | Capa de abstracción propia; proveedores: Anthropic (por defecto) y Ollama (local, opcional) |
| Generación de CV | `Jinja2` (plantilla HTML) + `WeasyPrint` para PDF; `python-docx` para DOCX |
| Verificación ATS | `pdfplumber` (extraer texto del PDF) y `python-docx` (inspeccionar el DOCX) |
| Config | `config.yaml` + `.env` (`python-dotenv`) |
| Calidad | `pytest`, `ruff`, `mypy` (modo razonable, no estricto al 100%) |

Notas:
- No usar FastAPI: Streamlit llama directamente a la librería `jobradar`.
- WeasyPrint en Windows requiere dependencias de GTK. Si falla la instalación, implementar el respaldo DOCX primero y avisarme; no pierdas tiempo peleando con el instalador.

## 4. Estructura de carpetas

```
jobradar/
├── AGENTS.md
├── PLAN.md
├── README.md
├── pyproject.toml
├── .env.example
├── .gitignore               # debe ignorar: .env, data/, output/, *.sqlite, __pycache__
├── config.yaml              # filtros, empresas, modelo LLM (versionable, sin secretos)
├── alembic/
├── src/jobradar/
│   ├── config.py            # carga y valida config.yaml + .env
│   ├── db/
│   │   ├── models.py
│   │   └── session.py
│   ├── sources/
│   │   ├── base.py          # interfaz JobSource + dataclass NormalizedJob
│   │   ├── greenhouse.py
│   │   ├── lever.py
│   │   ├── ashby.py
│   │   └── workday.py       # fase extra
│   ├── ingest.py            # orquesta fuentes, normaliza, deduplica, upsert
│   ├── filters.py           # prefiltro por keywords, ubicación, antigüedad
│   ├── llm/
│   │   ├── base.py          # protocolo LLMClient
│   │   ├── anthropic_client.py
│   │   └── ollama_client.py
│   ├── scoring.py
│   ├── ats_keywords.py      # extracción de requisitos + matching determinista de keywords
│   ├── knockouts.py         # filtros eliminatorios: años, idioma, estudios, ubicación...
│   ├── ats_check.py         # verificación del PDF/DOCX generado (parseo, orden, formato)
│   ├── tailoring.py         # generación + validación del CV adaptado
│   ├── render/
│   │   ├── templates/cv_ats.html.j2
│   │   ├── pdf.py
│   │   └── docx.py
│   ├── prompts/             # prompts versionados en archivos .md/.txt, no hardcodeados
│   └── cli.py               # comandos: ingest, score, tailor, probe
├── app/
│   └── dashboard.py         # Streamlit
├── tests/
│   ├── fixtures/            # JSON reales de Greenhouse, Lever, Workday
│   └── ...
├── data/                    # NO versionar
│   ├── cv_master.yaml
│   ├── jobradar.sqlite
│   └── cache/
└── output/                  # NO versionar: PDFs/DOCX y mensajes generados
    └── {empresa}_{puesto}_{fecha}/
```

## 5. Fuentes de datos

Toda fuente implementa la interfaz `JobSource` y devuelve objetos `NormalizedJob`:

```python
@dataclass
class NormalizedJob:
    source: str            # "greenhouse" | "lever" | "ashby" | "workday"
    external_id: str
    company: str           # slug de la empresa
    company_name: str
    title: str
    location: str | None
    workplace_type: str | None   # "remote" | "hybrid" | "onsite" | None
    department: str | None
    description_text: str  # texto plano, sin HTML
    url: str               # enlace para aplicar
    posted_at: datetime | None
    raw: dict              # respuesta original para depurar
```

**Antes de escribir cada conector, haz una petición real de prueba y guarda la respuesta en `tests/fixtures/`. Verifica los campos reales; no los asumas de esta especificación.**

### Greenhouse
- Listado con contenido: `GET https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true`
- Campos esperados (verificar): `id`, `title`, `location.name`, `updated_at`, `absolute_url`, `content` (HTML escapado), `departments`. Algunos tableros incluyen `first_published`; si existe, úsalo como `posted_at`; si no, `updated_at` y márcalo como aproximado.

### Lever
- `GET https://api.lever.co/v0/postings/{company}?mode=json`
- Campos esperados (verificar): `id`, `text` (título), `createdAt` (epoch en milisegundos), `categories.location`, `categories.team`, `categories.commitment`, `hostedUrl`, `descriptionPlain`, `lists`, `workplaceType`.

### Ashby
- Job board público: `GET https://api.ashbyhq.com/posting-api/job-board/{slug}`
- Respuesta `{"jobs": [...], "apiVersion": ...}`. Campos verificados: `id` (UUID), `title`, `location`, `secondaryLocations`, `department`, `team`, `employmentType`, `publishedAt` (ISO 8601 con offset), `isListed`, `isRemote`, `workplaceType` ("Remote" | "Hybrid" | "Onsite"), `jobUrl`, `applyUrl`, `descriptionPlain`, `descriptionHtml`.
- Filtrar `isListed == false` y preferir `descriptionPlain`.

### Workday (fase extra, inestable por naturaleza)
- Cada empresa tiene su `tenant`, `wd{N}` y `site`. Listado: `POST https://{tenant}.wd{N}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs` con cuerpo `{"appliedFacets":{},"limit":20,"offset":0,"searchText":""}`.
- El listado trae `title`, `externalPath`, `locationsText`, `postedOn` (texto relativo como "Posted 3 Days Ago"). El detalle sale de `GET .../wday/cxs/{tenant}/{site}/job/{externalPath}`.
- Es un endpoint interno sin garantías: si falla, el conector debe degradar con gracia (log + continuar con las demás fuentes), nunca tumbar la ingesta.

### Lista de empresas
Se define en `config.yaml`:

```yaml
companies:
  - name: "Empresa Ejemplo"
    source: greenhouse
    slug: empresaejemplo
  - name: "Otra Empresa"
    source: lever
    slug: otraempresa
  - name: "Una Más"
    source: workday
    tenant: unamas
    wd: 5
    site: External
```

El comando `jobradar probe <source> <slug>` debe validar si un slug existe y cuántas vacantes devuelve, para que yo pueda ampliar la lista con confianza.

## 6. Modelo de datos (SQLite)

- **companies**: `id`, `name`, `source`, `slug`, `config_json`, `last_synced_at`.
- **jobs**: `id`, `company_id`, `source`, `external_id`, `title`, `location`, `workplace_type`, `department`, `description_text`, `url`, `posted_at`, `first_seen_at`, `last_seen_at`, `is_open`, `status`, `raw_json`. Restricción única: `(source, external_id)`.
- **scores**: `id`, `job_id`, `cv_hash`, `prompt_version`, `model`, `score` (0–100), `verdict`, `matches_json`, `gaps_json`, `red_flags_json`, `created_at`. Se cachea por `(job_id, cv_hash, prompt_version)`.
- **job_requirements**: `id`, `job_id`, `description_hash`, `prompt_version`, `model`, `keywords_json`, `knockouts_json`, `created_at`. Se cachea por `(job_id, description_hash, prompt_version)`.
- **applications**: `id`, `job_id`, `tailored_cv_json`, `pdf_path`, `docx_path`, `message_text`, `language`, `required_coverage`, `ats_report_json`, `created_at`, `applied_at`, `notes`.
- **events**: `id`, `job_id`, `type`, `payload_json`, `created_at` (historial de cambios de estado).

Estados de `jobs.status`: `new` → `reviewed` → `prepared` → `applied` → `interview` → `offer`, y los terminales `rejected` y `discarded`.

Reglas de ingesta:
- Upsert por `(source, external_id)`; actualizar `last_seen_at`.
- Si una vacante ya no aparece en la API, marcar `is_open = 0` (no borrarla).
- No volver a puntuar una vacante cuya descripción y CV no cambiaron (usa hash).

## 7. CV maestro y reglas anti-invención

`data/cv_master.yaml` es la **única** fuente de hechos. Cada logro y cada elemento tiene un `id` estable.

```yaml
basics:
  name: "Nombre Apellido"
  email: "correo@ejemplo.com"
  phone: "+00 000 000 0000"
  location: "Ciudad, País"
  links:
    - { label: "LinkedIn", url: "https://..." }
summary_facts:                # hechos base para el resumen profesional
  - "N años de experiencia en ..."
target_titles:              # cargos que puedo usar legítimamente como titular
  - "Analista Financiero"
  - "Financial Analyst"
eligibility:                 # insumo para los filtros eliminatorios (sección 9.6)
  years_experience: { total: 5, by_area: { "FP&A": 3, "reporting": 4 } }
  work_authorization: ["México"]
  relocation: false
  remote_ok: true
experience:
  - id: exp_empresa_a
    company: "Empresa A"
    title: "Analista Financiero"
    start: "2021-03"
    end: "2024-06"            # o "present"
    location: "Ciudad"
    bullets:
      - id: exp_empresa_a_b1
        text: "Reduje el tiempo de cierre mensual de 8 a 5 días automatizando conciliaciones en Excel/VBA."
        tags: [finanzas, automatización, excel]
education:
  - id: edu_1
    institution: "Universidad X"
    degree: "Licenciatura en ..."
    year: "2020"
skills:
  - { name: "Excel avanzado", aliases: ["Microsoft Excel", "MS Excel"], tags: [excel], level: "avanzado", years: 6 }
  - { name: "Power BI", aliases: ["PowerBI", "Microsoft Power BI"], tags: [bi], years: 3 }
certifications: []
languages:
  - { name: "Español", level: "nativo" }
  - { name: "Inglés", level: "B2" }
```

### Salida del LLM para el CV adaptado (JSON validado con pydantic)

```json
{
  "headline": "string corto",
  "summary": "máx. 60 palabras, solo con hechos de summary_facts y bullets",
  "experience": [
    {
      "experience_id": "exp_empresa_a",
      "bullet_ids": ["exp_empresa_a_b1", "exp_empresa_a_b3"],
      "rewrites": { "exp_empresa_a_b1": "versión reordenada o con vocabulario de la vacante" }
    }
  ],
  "skills": ["Excel avanzado", "Power BI"],
  "education_ids": ["edu_1"],
  "keywords_used": ["Power BI", "FP&A"],
  "cover_message": "mensaje breve de postulación"
}
```

### Validador determinista (obligatorio, en `tailoring.py`)

El CV generado se **rechaza** (y se reintenta una vez, luego se marca error) si:

1. Algún `experience_id`, `bullet_id` o `education_id` no existe en el CV maestro.
2. Alguna habilidad en `skills` no está en `cv_master.skills` (se aceptan sus `aliases`) ni corresponde a una keyword marcada `supported` por el matching ATS (sección 9.1).
3. Un `rewrite` contiene números, porcentajes o cifras que no aparecen en el bullet original (conjunto de números del rewrite ⊆ conjunto del original).
4. Un `rewrite` o el `summary` menciona nombres de empresas, herramientas o certificaciones que no están en el CV maestro.
5. El `summary` supera 60 palabras o el `cover_message` supera 150 palabras.
6. Aparecen empresas, cargos o fechas distintos a los del maestro.
7. `keywords_used` o el texto del CV incluye una keyword marcada como `gap` (que el maestro no respalda).

Una `rewrite` puede cambiar el orden y el vocabulario para alinearse con la vacante, pero **no** añadir hechos, resultados, tecnologías ni responsabilidades.

Si la vacante pide algo que no tengo, el mensaje **no** debe fingirlo. Debe resaltar lo transferible y, si es relevante, reconocerlo con honestidad.

## 8. Scoring de compatibilidad

1. **Prefiltro barato (sin LLM)** en `filters.py`: palabras clave a incluir/excluir en el título, ubicaciones permitidas, aceptar remoto, antigüedad máxima (por defecto 7 días). Solo las vacantes que pasan el prefiltro llegan al LLM.
2. **Puntuación con LLM** en `scoring.py`. Entrada: CV maestro (serializado) + título y descripción de la vacante. Salida JSON validada:

```json
{
  "score": 0,
  "verdict": "aplicar | quizá | descartar",
  "matches": ["requisito cubierto y evidencia del CV"],
  "gaps": ["requisito no cubierto"],
  "red_flags": ["salario no indicado, seniority muy distinto, idioma, etc."],
  "language": "es | en"
}
```

3. Prompts en `src/jobradar/prompts/` con versión (`scoring_v1.md`); la versión se guarda en la tabla `scores`.
4. Procesar en lotes pequeños con límite de concurrencia y un tope configurable de vacantes por corrida (`max_jobs_per_run`) para controlar costos.
5. Los filtros eliminatorios no cumplidos (sección 9.6) se reflejan en `red_flags` y bajan el puntaje de forma explícita.

## 9. Optimización ATS y generación de documentos

El CV se construye pensando en cómo lo procesan los ATS (Workday, Greenhouse, Lever y similares). Lo que se optimiza, y solo esto:

- **(a) Parseo:** que el archivo se lea completo y en orden.
- **(b) Coincidencia de términos:** que aparezcan, **de forma literal y natural**, los términos que la vacante pide y que yo realmente cumplo (los reclutadores buscan y filtran por palabras clave).
- **(c) Filtros eliminatorios (knockouts):** saber de antemano si cumplo los requisitos duros (años de experiencia, idioma, estudios, ubicación, certificaciones).

Nota de alcance: muchos ATS no calculan un "puntaje" automático; los resultados de `ats_check` son una aproximación razonable, no una garantía. No se optimiza con trucos.

### 9.1 Flujo (en este orden)

1. **Extracción de requisitos de la vacante** (LLM, `src/jobradar/prompts/ats_extract_v1.md`). Salida JSON validada con pydantic:

```json
{
  "job_title_exact": "Financial Planning & Analysis Analyst",
  "language": "es | en",
  "keywords": [
    {
      "term": "Power BI",
      "type": "tool | hard_skill | certification | title | domain | methodology | soft_skill",
      "importance": "required | preferred | mentioned",
      "synonyms": ["PowerBI"],
      "frequency_in_posting": 3
    }
  ],
  "knockouts": [
    {
      "type": "years_experience | education | language | location | certification | work_authorization | other",
      "requirement": "3+ años en FP&A",
      "value": 3,
      "area": "FP&A",
      "mandatory": true
    }
  ]
}
```

   - Extraer los términos **tal como aparecen** en la vacante, incluyendo siglas y su forma completa.
   - `required` ante señales como "requisito", "indispensable", "must have", "se requiere"; `preferred` ante "deseable", "plus", "nice to have".
   - Ignorar relleno corporativo ("proactivo", "dinámico", "trabajo en equipo") salvo que sea una competencia concreta y medible.

2. **Matching determinista** (`ats_keywords.py`, **sin LLM**). Normaliza (minúsculas, sin acentos, plural simple, siglas ↔ forma completa, `aliases` del maestro) y busca cada keyword con límites de palabra en skills, aliases, tags, bullets y certificaciones del CV maestro. Resultado por keyword: `supported` (con los `id` de evidencia) o `gap`. Debe distinguir casos como "Java" vs "JavaScript".
3. **Generación** (LLM, `src/jobradar/prompts/tailoring_v1.md`). Recibe **solo** las keywords `supported` con su evidencia. Nunca ve las `gap` como algo que deba incorporar.
4. **Validación determinista** del contenido (sección 7) y **cálculo de cobertura** (9.2).
5. **Render** a PDF y DOCX (9.3).
6. **Verificación del archivo** con `ats_check.py` (9.4).
7. **Informe** `ats_report.json` y panel en el dashboard.

### 9.2 Reglas de contenido

- Usar el **término exacto de la vacante** cuando el maestro lo respalda. Siglas y forma completa una vez cada una: "Planeación y análisis financiero (FP&A)".
- Ubicar las keywords `required` y `supported` en tres lugares: el resumen, la sección de Habilidades y, al menos, un bullet de experiencia con contexto real (no solo una lista).
- Frecuencia: cada keyword entre 1 y 3 veces en total. Más de 3 se considera relleno.
- Titular (`headline`): puede reutilizar `job_title_exact` solo si coincide con algún `target_titles` o con un cargo real del maestro; si no, usar el más cercano del maestro.
- Las keywords `gap` **nunca** se agregan. Se listan en el informe y, si son `required`, se me avisa para que yo decida si aplico.
- **Cobertura requerida:** `required_coverage` = keywords `required` y `supported` presentes en el CV / total de `required` y `supported`. Debe ser ≥ `ats.min_required_coverage` (por defecto 0.90). Si no se alcanza, un único reintento indicándole al LLM cuáles faltan.
- También se reporta `overall_coverage`, que incluye las `gap` en el denominador, para que yo vea qué tan lejos estoy de lo que pide la vacante.
- Orden de secciones: Contacto, Resumen, Habilidades, Experiencia (cronología inversa), Educación, Certificaciones, Idiomas.
- Idioma del CV y del mensaje: el de la vacante (es/en). Traducir vocabulario, nunca hechos.

### 9.3 Reglas de formato (plantilla `cv_ats.html.j2` y DOCX)

- Una sola columna. Sin tablas, cuadros de texto, columnas, imágenes, iconos, gráficos ni barras de nivel de habilidades.
- Nombre y datos de contacto **en el cuerpo** del documento, nunca en encabezado o pie de página.
- Encabezados estándar y sin adornos: "Experiencia profesional / Professional Experience", "Educación / Education", "Habilidades / Skills", "Certificaciones / Certifications", "Idiomas / Languages".
- Fuente estándar (`ats.font`, por defecto Arial), tamaño 10–12 pt, color de texto negro, sin texto en blanco.
- Viñetas estándar (•). Sin símbolos exóticos, emojis ni caracteres especiales de decoración.
- Cada puesto con la estructura: cargo, empresa, ciudad, fechas, en líneas claras. Fechas en un único formato consistente (`ats.date_format`, por defecto "MMM YYYY – MMM YYYY").
- Máximo `ats.max_pages` páginas (por defecto 2).
- PDF con **texto seleccionable** (nunca imagen), fuentes embebidas y `font-variant-ligatures: none` para evitar que "fi", "fl" se extraigan mal.
- Nombre de archivo limpio: `Nombre_Apellido_CV.pdf` / `.docx` (sin espacios, acentos ni caracteres especiales).
- Se generan **ambos** formatos (PDF y DOCX); el dashboard indica cuál usar si el portal indica una preferencia.

### 9.4 Verificación del archivo (`ats_check.py`)

Se ejecuta sobre el PDF y el DOCX **ya generados** y produce un checklist con aprobado/fallido y el motivo:

1. El texto del PDF es extraíble (`pdfplumber`) y no está vacío ni es una imagen.
2. Orden de lectura correcto: los encabezados estándar aparecen en el orden esperado y los bullets de cada puesto quedan bajo su puesto.
3. Nombre, correo y teléfono detectados en las primeras líneas del texto extraído.
4. Encabezados estándar presentes.
5. Todas las fechas son parseables y siguen un único formato.
6. DOCX sin tablas, cuadros de texto, imágenes, columnas ni contenido en encabezado/pie.
7. Sin caracteres de reemplazo (�) ni ligaduras rotas en el texto extraído.
8. Número de páginas ≤ `ats.max_pages`.
9. `required_coverage` ≥ umbral y ninguna keyword repetida más de `ats.max_keyword_repetitions`.
10. Ida y vuelta: el texto extraído contiene cada bullet de `tailored.json` completo y sin duplicados.

### 9.5 Salida

`output/{empresa}_{puesto}_{YYYYMMDD}/` con: `Nombre_Apellido_CV.pdf`, `Nombre_Apellido_CV.docx`, `mensaje.txt`, `tailored.json` (auditoría) y `ats_report.json` (cobertura, brechas, checklist y knockouts).

### 9.6 Filtros eliminatorios (knockouts)

`knockouts.py` compara cada knockout extraído con el maestro (`eligibility`, experiencia, educación, idiomas, certificaciones) y devuelve `met | not_met | unknown` con la evidencia.

- Años, idiomas y estudios se evalúan de forma determinista.
- Lo demás puede apoyarse en el LLM, pero ante cualquier duda se devuelve `unknown`; nunca se asume que se cumple.
- Se muestran **antes** de preparar la postulación. Un knockout obligatorio `not_met` genera una advertencia visible; no bloquea, la decisión de aplicar es mía.
- Nunca se modifica el CV para "cumplir" un knockout que no se cumple.

## 10. Dashboard (Streamlit)

Páginas:

1. **Vacantes**: tabla con filtros (texto, empresa, fuente, ubicación/remoto, rango de fechas, puntaje mínimo, estado, solo abiertas) y orden por fecha o puntaje. Botones: *Puntuar seleccionadas*, *Descartar*, *Preparar postulación*.
2. **Detalle de vacante**: descripción completa, puntaje con coincidencias/brechas/alertas, enlace original, historial de eventos.
3. **Preparar postulación**: vista previa del CV (lado a lado con el maestro, resaltando qué cambió), **panel ATS** (checklist de 9.4, keywords cubiertas vs. brechas, cobertura requerida y knockouts), mensaje editable, botones *Regenerar*, *Descargar PDF/DOCX*, *Copiar mensaje*, *Abrir enlace de la vacante*, *Marcar como aplicada*.
4. **Seguimiento**: tablero por estado (conteos y lista), notas, fechas.
5. **Configuración**: ver/editar empresas, filtros y proveedor LLM; botón *Sincronizar ahora*; estimación de costo de la corrida antes de ejecutar.

Requisitos: nada se envía solo; toda llamada al LLM se dispara por acción explícita (o por el comando de CLI que yo ejecute).

## 11. Configuración (`config.yaml`)

```yaml
search:
  keywords_include: ["analista financiero", "financial analyst"]
  keywords_exclude: ["senior director", "practicante"]
  locations: ["Monterrey", "Nuevo León", "México", "Remote"]
  accept_remote: true
  max_age_days: 7
llm:
  provider: anthropic        # anthropic | ollama
  model_scoring: "<modelo económico>"   # configurable, NO hardcodear en el código
  model_writing: "<modelo de mayor calidad>"
  max_jobs_per_run: 50
http:
  requests_per_second: 1
  timeout_seconds: 20
ats:
  min_required_coverage: 0.90
  max_keyword_repetitions: 3
  max_pages: 2
  font: "Arial"
  font_size_pt: 11
  date_format: "MMM YYYY"
discovery:                    # Fase 7 — proveedor de búsqueda de portales
  provider: serper            # serper | brave | google_cse
  max_queries_per_run: 5
  cache_ttl_hours: 24
companies: []                # ver sección 5
```

## 12. Convenciones de código

- Type hints en todo; `ruff` y `mypy` deben pasar antes de cerrar una fase.
- Funciones pequeñas, módulos con una sola responsabilidad. Nada de lógica de negocio dentro de `dashboard.py`.
- Errores de red o de una fuente: capturar, registrar y continuar con las demás. Nunca dejar que una empresa caída detenga la ingesta.
- Logging con `logging` estándar a archivo en `data/logs/`; nunca registrar el CV ni las API keys.
- Mensajes de commit en formato `fase-N: descripción corta`. Un commit por tarea lógica.
- No añadir dependencias nuevas sin justificarlas en el README.

## 13. Comandos esperados

```bash
uv sync                                   # instalar dependencias
uv run jobradar probe greenhouse <slug>   # validar una empresa
uv run jobradar ingest                    # descargar y guardar vacantes
uv run jobradar score --limit 20          # puntuar vacantes pendientes
uv run jobradar requirements --job-id 123 # ver keywords (supported/gap) y knockouts
uv run jobradar tailor --job-id 123       # generar CV + mensaje
uv run jobradar ats-check --job-id 123    # verificar el PDF/DOCX generado
uv run streamlit run app/dashboard.py     # abrir el dashboard
uv run pytest && uv run ruff check . && uv run mypy src
```

## 14. Definición de "terminado" para cada fase

1. Los tests de la fase pasan sin red ni consumo de tokens.
2. `ruff` y `mypy` sin errores.
3. El README documenta lo que se agregó (instalación, uso, costos y qué datos salen de la máquina).
4. Me muestras una demostración breve (comando o captura) y **esperas mi aprobación** antes de continuar.

## 15. Fuera de alcance

- Envío automático de postulaciones o llenado de formularios.
- Scraping de Google, LinkedIn, Indeed u otros portales sin API pública.
- Autenticación de usuarios, multiusuario o despliegue en la nube.
- Cualquier cosa que invente o exagere mi experiencia.
- Trucos para engañar a un ATS: texto oculto o blanco, relleno de keywords, copiar la vacante dentro del CV.
