# Plan de implementación: JobRadar

Plan por fases para construir el proyecto con opencode. Cada fase termina con algo que puedes ejecutar y comprobar, y no se pasa a la siguiente sin tu aprobación.

## Resumen

| Fase | Resultado | Depende de |
|---|---|---|
| 0 | Preparación (tú) y esqueleto del proyecto | — |
| 1 | Ingesta de Greenhouse y Lever a SQLite | 0 |
| 2 | Dashboard básico con filtros | 1 |
| 3 | Scoring de compatibilidad con LLM | 1, CV maestro |
| 4A | Requisitos de la vacante: keywords ATS y knockouts | 3 |
| 4B | CV adaptado a las keywords + mensaje, con validación | 4A |
| 4C | PDF/DOCX en formato ATS + verificación del archivo | 4B |
| 5 | Seguimiento de estados y pulido de flujo | 2, 4 |
| 6 | Workday (extra) | 1 |
| 7 | Descubrimiento de empresas (opcional) | 1 |

Orden recomendado: 0 → 1 → 3 → 4 → 2 → 5. Así compruebas pronto lo más valioso (que el CV adaptado sea bueno) y dejas el dashboard para cuando ya hay datos reales. Si prefieres ver una interfaz cuanto antes, sigue el orden numérico.

---

## Cómo trabajar con opencode

1. Crea la carpeta del proyecto, copia `AGENTS.md` y `PLAN.md` en la raíz y ejecuta `git init`.
2. Abre opencode dentro de esa carpeta. Lee `AGENTS.md` automáticamente.
3. Para cada fase, empieza en **modo Plan** (se alterna con Tab): pídele que proponga el desglose de tareas y revísalo. Luego pasa a **modo Build** para que implemente.
4. Pega el prompt de la fase (más abajo). Al terminar, ejecuta tú mismo los comandos de verificación.
5. Haz commit al cerrar cada fase. Si algo sale mal, puedes volver atrás.
6. Si opencode se desvía (cambia el stack, añade dependencias, automatiza envíos), recuérdale la sección correspondiente de `AGENTS.md`.

---

## Fase 0: Preparación y esqueleto

### Lo que haces tú antes de empezar
- [ ] Escribir tu **CV maestro** en `data/cv_master.yaml` siguiendo el esquema de `AGENTS.md` (sección 7). Esta es la pieza que más determina la calidad del resultado: incluye todos tus logros, con números reales, cada uno con su `id`.
- [ ] Completar en el CV maestro los campos que alimentan el ATS: `aliases` de cada habilidad (por ejemplo "PowerBI", "Microsoft Power BI"), `years` por habilidad, `target_titles` y el bloque `eligibility` (años de experiencia por área, autorización de trabajo, idiomas). Sin esto, el matching de keywords y los filtros eliminatorios fallan o dan falsos negativos.
- [ ] Armar una lista inicial de **10 a 20 empresas objetivo** y averiguar su portal. Pista: abre la página de empleo de la empresa y mira si la URL contiene `boards.greenhouse.io`, `job-boards.greenhouse.io`, `jobs.lever.co` o `myworkdayjobs.com`. El texto que sigue al dominio es el *slug*.
- [ ] Obtener una **API key** del proveedor de LLM (o instalar Ollama si prefieres modelo local).
- [ ] Instalar `uv` y Python 3.11+.

### Tareas para opencode
1. Inicializar el proyecto con `uv` y `pyproject.toml` con las dependencias del stack.
2. Crear la estructura de carpetas de `AGENTS.md` (sección 4), con archivos vacíos o *stubs*.
3. Crear `.gitignore` (debe excluir `.env`, `data/`, `output/`, `*.sqlite`, `__pycache__`, `.venv`).
4. Crear `.env.example`, `config.yaml` de ejemplo y `config.py` que los cargue y valide con pydantic.
5. Configurar `ruff`, `mypy` y `pytest` con una prueba trivial.
6. Redactar el `README.md` inicial (qué es, instalación, privacidad).

### Criterios de aceptación
- `uv sync` funciona en limpio.
- `uv run pytest && uv run ruff check . && uv run mypy src` pasan.
- `git status` no muestra `data/` ni `.env`.

### Prompt para opencode
```
Lee AGENTS.md y PLAN.md. Vamos a hacer la Fase 0. Primero, en modo plan,
resume qué vas a crear y en qué orden. No instales dependencias que no estén
en la sección 3 de AGENTS.md. Cuando termine, ejecuta pytest, ruff y mypy y
muéstrame el resultado. No avances a la Fase 1.
```

---

## Fase 1: Ingesta de vacantes

### Tareas
1. **Explorar las APIs con peticiones reales.** Para una empresa de cada fuente, hacer la petición, guardar el JSON en `tests/fixtures/` y documentar en el README los campos reales encontrados (sobre todo la fecha de publicación).
2. Implementar `sources/base.py` con `JobSource` y `NormalizedJob`.
3. Implementar `sources/greenhouse.py` (listado con `content=true`, limpieza de HTML a texto plano).
4. Implementar `sources/lever.py` (convertir `createdAt` de milisegundos a `datetime`).
5. Cliente HTTP compartido con límite de 1 req/s por host, timeout, reintentos con backoff y `User-Agent` propio.
6. Modelos SQLAlchemy y migración inicial con alembic (`companies`, `jobs`, `events`).
7. `ingest.py`: recorre las empresas de `config.yaml`, normaliza, hace upsert por `(source, external_id)`, actualiza `last_seen_at` y marca `is_open = 0` las que desaparecieron.
8. `filters.py`: prefiltro por palabras clave, ubicación/remoto y antigüedad.
9. CLI: `probe` e `ingest`, con resumen en consola (empresas leídas, vacantes nuevas, cerradas, errores).
10. Tests con fixtures: parsers, deduplicación, cierre de vacantes, manejo de errores de una fuente.

### Criterios de aceptación
- `jobradar probe greenhouse <slug>` y `jobradar probe lever <slug>` informan cuántas vacantes devuelve cada empresa.
- `jobradar ingest` con tu lista real guarda vacantes en SQLite; ejecutarlo dos veces seguidas no duplica nada.
- Si una empresa devuelve 404 o falla, el resto se procesa y el error queda en el resumen.
- Los tests pasan sin red.

### Prompt para opencode
```
Fase 1: ingesta de Greenhouse y Lever. Antes de escribir los conectores, haz
una petición real a una empresa de cada fuente (te doy los slugs: <slug_gh>,
<slug_lever>), guarda las respuestas en tests/fixtures/ y dime qué campos de
fecha existen realmente. Con eso, implementa lo que dice PLAN.md para esta
fase, respetando el límite de 1 req/s y los principios de la sección 2.
Los tests no pueden usar red. Al terminar, muéstrame la salida de
`jobradar ingest` y detente.
```

---

## Fase 2: Dashboard básico

### Tareas
1. `app/dashboard.py` con página **Vacantes**: tabla con filtros (texto, empresa, fuente, ubicación/remoto, fecha, estado, solo abiertas) y orden.
2. Página **Detalle de vacante** con descripción completa y enlace a la publicación original.
3. Acciones: marcar como *reviewed* o *discarded*, registrando el evento.
4. Botón **Sincronizar ahora** que ejecuta la ingesta y muestra el resumen.
5. Indicador de vacantes nuevas desde la última visita.
6. Lógica de consulta en funciones de la librería (no en el archivo de Streamlit) y pruebas de esas funciones.

### Criterios de aceptación
- `uv run streamlit run app/dashboard.py` abre y muestra las vacantes de la base.
- Los filtros combinados devuelven resultados correctos.
- Descartar una vacante la oculta por defecto y deja registro en `events`.

### Prompt para opencode
```
Fase 2: dashboard de Streamlit según la sección 10 de AGENTS.md, solo las
páginas Vacantes y Detalle por ahora. Pon toda la lógica de consulta en
src/jobradar (con tests) y deja dashboard.py solo para la interfaz.
```

---

## Fase 3: Scoring de compatibilidad

### Tareas
1. Capa `llm/base.py` con el protocolo `LLMClient` (`complete_json(system, user, schema)`), y `anthropic_client.py`. El nombre del modelo viene de `config.yaml`, no del código.
2. `ollama_client.py` (opcional, mismo protocolo).
3. Escribir `prompts/scoring_v1.md`. Instrucciones clave: evaluar solo con evidencia del CV, citar la evidencia, no suponer habilidades, listar brechas con honestidad.
4. `scoring.py`: construye la entrada, llama al LLM, valida el JSON con pydantic (un reintento si el JSON es inválido), guarda en `scores` con `cv_hash`, `prompt_version` y `model`.
5. Caché: no re-puntuar si `(job_id, cv_hash, prompt_version)` ya existe.
6. Tope `max_jobs_per_run` y estimación de costo antes de ejecutar.
7. CLI: `jobradar score --limit N`.
8. Integrar en el dashboard: columna de puntaje, botón *Puntuar seleccionadas*, panel con coincidencias/brechas/alertas.
9. Tests con un `FakeLLMClient` (sin red ni tokens) y pruebas de caché y de JSON inválido.

### Criterios de aceptación
- Puntuar 10 vacantes reales produce puntajes y justificaciones coherentes con tu criterio.
- Repetir el comando no vuelve a gastar tokens.
- Cambiar una línea del CV maestro invalida la caché (cambia `cv_hash`).

### Cómo validar la calidad (lo haces tú)
Toma 10 vacantes y puntúalas tú a mano antes de ver el resultado. Compara. Si el modelo se aleja mucho, ajusta `scoring_v1.md` y crea `scoring_v2.md` en lugar de editar el anterior.

### Prompt para opencode
```
Fase 3: scoring con LLM según la sección 8. Implementa la abstracción
LLMClient, el cliente de Anthropic y scoring.py con caché por
(job_id, cv_hash, prompt_version). Usa un FakeLLMClient en los tests. El
modelo viene de config.yaml. Antes de ejecutar contra la API real, muéstrame
la estimación de costo para 10 vacantes.
```

---

## Fase 4: Optimización ATS, CV adaptado, mensaje y documentos

La fase más delicada: aquí se juega tanto la honestidad del CV como que pase los filtros. Se divide en tres subfases, cada una con su propia aprobación. Referencia: sección 9 de `AGENTS.md`.

### Fase 4A: Requisitos de la vacante y matching de keywords

**Tareas**
1. Modelos pydantic para la salida de extracción (`keywords` con `type`, `importance`, `synonyms`; `knockouts`).
2. `prompts/ats_extract_v1.md`: extraer términos tal como aparecen, separar `required` de `preferred`, incluir siglas y forma completa, capturar el título exacto e ignorar relleno corporativo.
3. Tabla `job_requirements`, migración y caché por `(job_id, description_hash, prompt_version)`.
4. `ats_keywords.py`: normalización (minúsculas, acentos, plurales simples, siglas ↔ forma completa, `aliases` del maestro) y matching por límites de palabra. Cada keyword sale como `supported` (con ids de evidencia) o `gap`.
5. Tests del matching: "PowerBI" ↔ "Power BI", "FP&A" ↔ "planeación y análisis financiero", "Java" no debe coincidir con "JavaScript", acentos y mayúsculas, plural/singular.
6. `knockouts.py`: compara con `eligibility` y el maestro y devuelve `met | not_met | unknown` con evidencia. Años, idiomas y estudios de forma determinista; ante la duda, `unknown`.
7. Integrar los knockouts no cumplidos en el scoring (`red_flags`).
8. CLI `jobradar requirements --job-id N`.
9. Dashboard: en el detalle de la vacante, mostrar keywords (cubiertas y brechas) y knockouts.

**Criterios de aceptación**
- En 10 vacantes reales, las keywords `required` extraídas coinciden con lo que tú marcarías como importante.
- El matching separa correctamente `supported` de `gap` (revísalo a mano en al menos 5 vacantes).
- Un knockout no cumplido aparece como advertencia, nunca como cumplido.
- Los tests pasan sin red ni tokens.

**Prompt para opencode**
```
Fase 4A (PLAN.md): extracción de keywords ATS y matching determinista,
sección 9.1 y 9.6 de AGENTS.md. Empieza por los tests del matching
(PowerBI/Power BI, FP&A, Java vs JavaScript, acentos) y por ats_keywords.py;
el LLM solo se usa para extraer requisitos, nunca para decidir si algo está
respaldado en mi CV. Usa FakeLLMClient en los tests. Detente al terminar.
```

### Fase 4B: Generación del CV y del mensaje

**Tareas**
1. Modelos pydantic para `cv_master.yaml` y para la salida del LLM (con `keywords_used`).
2. **Validador determinista primero**, con las 7 reglas de la sección 7, y tests de casos que deben fallar: bullet inexistente, número inventado, herramienta nueva en un `rewrite`, resumen demasiado largo, habilidad ausente del maestro, keyword `gap` presente en el CV.
3. `prompts/tailoring_v1.md`: recibe solo keywords `supported` con su evidencia. Instrucciones: usar el término exacto de la vacante, siglas y forma completa una vez, ubicar las `required` en resumen, habilidades y al menos un bullet, 1–3 repeticiones por keyword, no tocar las `gap`.
4. `tailoring.py`: cálculo de `required_coverage` y `overall_coverage`; un único reintento si la cobertura queda bajo el umbral; si vuelve a fallar, se marca error con el motivo.
5. Mensaje de postulación: breve (máx. 150 palabras), específico de la empresa y del puesto, en el idioma de la vacante, que resalte lo transferible sin fingir brechas.
6. CLI `jobradar tailor --job-id N`.

**Criterios de aceptación**
- Para 3 vacantes distintas, todos los hechos del CV están en tu maestro y las keywords `required` y `supported` aparecen de forma natural.
- Los casos de invención son rechazados por el validador.
- La cobertura requerida es ≥ 90% o el sistema explica por qué no.
- Ninguna keyword supera 3 repeticiones.

**Prompt para opencode**
```
Fase 4B (PLAN.md): generación del CV y del mensaje. Implementa primero el
validador determinista con sus 7 reglas y sus tests de fallo (sección 7),
luego el cálculo de cobertura, y solo después el prompt y la llamada al LLM.
El LLM recibe únicamente keywords supported con su evidencia. No agregues
ninguna forma de enviar postulaciones. Detente al terminar.
```

### Fase 4C: Render en formato ATS y verificación del archivo

**Tareas**
1. Plantilla `cv_ats.html.j2` según 9.3: una columna, fuente estándar, contacto en el cuerpo, `font-variant-ligatures: none`, texto negro, sin imágenes ni tablas.
2. `render/pdf.py` (WeasyPrint) y `render/docx.py` (python-docx), con nombre de archivo limpio.
3. `ats_check.py` con los 10 chequeos de 9.4 y generación de `ats_report.json`.
4. Tests con archivos defectuosos de prueba que **deben fallar**: DOCX con tabla, DOCX con contacto en el encabezado, PDF de dos columnas, PDF como imagen, fechas en formatos mezclados. Y un par de archivos correctos que deben pasar.
5. Guardar todo en `output/{empresa}_{puesto}_{fecha}/` y registrar en `applications`.
6. CLI `jobradar ats-check --job-id N`.
7. Dashboard, página **Preparar postulación**: vista previa del CV, comparación con el maestro, panel ATS (checklist, keywords cubiertas vs. brechas, cobertura, knockouts), mensaje editable, regenerar, descargar PDF/DOCX, copiar mensaje, abrir el enlace.

**Criterios de aceptación**
- Los archivos defectuosos de prueba fallan el chequeo y los correctos lo pasan.
- Al copiar todo el texto del PDF y pegarlo en un editor de texto plano, se lee completo y en orden.
- El panel muestra con claridad qué keywords faltan porque tú no las tienes (brechas).
- Revisión manual obligatoria: lees cada CV antes de usarlo.

**Prompt para opencode**
```
Fase 4C (PLAN.md): render y verificación ATS, secciones 9.3 a 9.5 de
AGENTS.md. Primero ats_check.py con tests que usen archivos defectuosos
(tabla, columnas, contacto en el header, PDF imagen) y archivos correctos;
después la plantilla y los renderizadores. Si WeasyPrint falla al instalarse
en mi sistema, implementa DOCX primero y avísame. Detente al terminar.
```

---

## Fase 5: Seguimiento y pulido

### Tareas
1. Página **Seguimiento**: conteos por estado, lista y notas por vacante, fecha de postulación.
2. Transiciones de estado con historial en `events`.
3. Botón **Marcar como aplicada** que guarda la fecha y bloquea duplicar postulación a la misma vacante sin confirmar.
4. Recordatorios visuales: postulaciones sin respuesta tras X días (configurable).
5. Exportar el seguimiento a CSV.
6. Página **Configuración**: editar empresas y filtros desde la interfaz.
7. Revisión final: README completo, sección de privacidad y costos, limpieza de TODOs.

### Criterios de aceptación
- Puedes recorrer el flujo completo: sincronizar → puntuar → preparar → aplicar → seguimiento.
- El historial de cada vacante es consultable.

### Prompt para opencode
```
Fase 5: seguimiento de estados y pulido final según las secciones 6 y 10.
Al terminar, repasa AGENTS.md sección 14 y dime qué criterios cumple el
proyecto y cuáles no.
```

---

## Fase 6 (extra): Workday

### Tareas
1. Explorar con peticiones reales un tenant de Workday tuyo y guardar fixtures.
2. `sources/workday.py` con paginación por `offset`/`limit`.
3. Convertir `postedOn` ("Posted 3 Days Ago", "Posted Today") a una fecha aproximada y marcarla como tal.
4. Obtener el detalle de cada vacante solo para las que pasan el prefiltro (reduce peticiones).
5. Degradación con gracia: si el endpoint cambia, la fuente se desactiva con un aviso y el resto sigue.

### Criterios de aceptación
- Al menos 2 tenants de Workday se ingieren correctamente.
- Un fallo de Workday nunca detiene la ingesta de las otras fuentes.

---

## Fase 7 (opcional): Descubrimiento de empresas

Ayuda a ampliar `config.yaml` sin buscar a mano.

### Tareas
1. Integrar una API de búsqueda (Brave Search API o similar) con tu clave, usando consultas del estilo `site:boards.greenhouse.io "analista financiero" Monterrey`.
2. Extraer slugs de las URLs resultantes y validarlos con `probe`.
3. Mostrar en el dashboard una lista de **empresas candidatas** para que tú apruebes cuáles añadir a la lista. Nunca añadir automáticamente.
4. Límite de consultas por corrida y caché de resultados.

### Criterios de aceptación
- Aparecen empresas nuevas relevantes que no tenías, con el número de vacantes que tienen.
- Respeta los límites y términos de la API de búsqueda elegida.

---

## Riesgos y cómo se mitigan

| Riesgo | Mitigación |
|---|---|
| El LLM inventa o exagera logros | Validador determinista + revisión manual obligatoria + guardar `tailored.json` para auditoría |
| Costos de tokens descontrolados | Prefiltro sin LLM, caché por hash, `max_jobs_per_run`, estimación previa, modelo económico para scoring |
| Un endpoint cambia o cae | Una fuente fallida no detiene a las demás; fixtures para detectar cambios en tests |
| Bloqueos por exceso de peticiones | 1 req/s por host, backoff, caché, `User-Agent` identificable |
| Fecha de publicación imprecisa | Marcarla como aproximada cuando proviene de `updated_at` o de texto relativo |
| El ATS no parsea bien el CV | Plantilla de una columna, sin imágenes ni tablas, ligaduras desactivadas, checklist `ats_check` sobre el archivo real |
| Quedar fuera por un filtro eliminatorio sin saberlo | Extracción de knockouts y comparación con `eligibility` antes de preparar la postulación |
| Keyword stuffing o texto oculto | Máximo 3 repeticiones por keyword, validador que rechaza keywords `gap`, prohibición explícita en `AGENTS.md` |
| Falsos negativos en el matching (siglas, sinónimos) | `aliases` en el CV maestro, mapeo de siglas ↔ forma completa y tests con casos reales |
| Fuga de datos personales | `data/` y `.env` fuera de git; solo sale el texto enviado al LLM; documentarlo en el README |
| Que opencode "mejore" cosas fuera de alcance | `AGENTS.md` secciones 2 y 15; un solo prompt por fase; revisar el diff antes de cada commit |

## Rutina diaria una vez terminado

1. `uv run jobradar ingest` (o botón *Sincronizar ahora*).
2. Abrir el dashboard, ordenar por antigüedad y puntaje.
3. Puntuar las nuevas, revisar las mejores.
4. Preparar la postulación, revisar el **panel ATS** (knockouts, cobertura de keywords, checklist de formato), **leer el CV y el mensaje completos** y ajustar si hace falta.
5. Aplicar tú mismo en el portal de la empresa y marcar como aplicada.
