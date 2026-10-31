# Fase 0: Preparación y esqueleto — Documento de la tarea

## Pedido
Construir el esqueleto del proyecto JobRadar (Fase 0) según AGENTS.md y PLAN.md. Incluye: git init, pyproject.toml con dependencias, estructura de carpetas, config.yaml/.env.example/config.py, calidad (ruff/mypy/pytest), CLI mínima, README inicial.

## Alcance y fuera de alcance
**Alcance (Fase 0):**
- Inicializar repositorio git con .gitignore
- pyproject.toml con stack completo (sección 3 AGENTS.md) y grupos dev
- Estructura de carpetas sección 4 con stubs documentados
- Configuración: config.yaml.example, .env.example, config.py con pydantic v2
- examples/cv_master.example.yaml con datos ficticios
- Calidad: ruff, mypy, pytest con prueba de humo
- CLI mínima: jobradar --help y --version
- README inicial con privacidad y ODD

**Fuera de alcance (NO hacer en esta fase):**
- Conectores Greenhouse/Lever/Workday (Fase 1)
- Dashboard Streamlit (Fase 2)
- Scoring LLM (Fase 3)
- ATS, CV adaptado, documentos (Fase 4)
- Seguimiento (Fase 5)
- Workday (Fase 6)
- Descubrimiento empresas (Fase 7)
- Llamadas a LLM o APIs reales

## Hallazgos de la exploración
- Carpeta actual: solo AGENTS.md y PLAN.md
- No hay git, no hay pyproject.toml, no hay estructura
- Entorno: Linux Fedora, Python 3.14.8, uv 0.5.x, git 2.56, Node 24
- WeasyPrint en Linux debería instalarse sin GTK issues; si falla, DOCX como respaldo

## Decisiones y supuestos
1. Python 3.14.8 compatible; si alguna dep falla, se documenta
2. Datos 100% ficticios en examples/
3. No se lee ni imprime .env, data/, CVs reales
4. Dependencias solo de sección 3 AGENTS.md
5. Commits formato "fase-0: descripción corta"

## Tareas (checklist con verificación)

- [x] **T1. git init y .gitignore** (excluir .env, data/, output/, *.sqlite, __pycache__, .venv, .mypy_cache, .ruff_cache)
  - Verificación: `git check-ignore -v .env data/x output/x`
  - **Evidencia**: `.gitignore` creado con patrones correctos. `git check-ignore -v .env data/x output/x` confirma que se ignoran: `.gitignore:2:.env .env`, `.gitignore:8:data/ data/x`, `.gitignore:9:output/ output/x`. Git repo inicializado en `master`.

- [x] **T2. Proyecto con uv y pyproject.toml** (dependencias stack + grupos dev pytest, ruff, mypy)
  - Verificación: `uv sync` en limpio
  - **Evidencia**: `uv sync` completo sin errores. 95 paquetes instalados incluyendo todo el stack: httpx, sqlalchemy, alembic, pydantic v2, streamlit, anthropic, jinja2, weasyprint, python-docx, pdfplumber, python-dotenv, typer, rich. Grupos dev: pytest, ruff, mypy con types. `uv sync --frozen` verifica instalación reproducible.

- [x] **T3. Estructura de carpetas** (sección 4 AGENTS.md) con stubs vacíos documentados
  - Verificación: `python -c "import jobradar"` sin errores
  - **Evidencia**: Estructura completa creada bajo `src/jobradar/` (config.py, db/, sources/, ingest.py, filters.py, llm/, scoring.py, ats_keywords.py, knockouts.py, ats_check.py, tailoring.py, render/, prompts/, cli.py) + `app/dashboard.py` + `tests/fixtures/` + `alembic/` + `data/` + `output/` + `examples/` + `odd/tasks/`. `uv run python -c "import jobradar; print(jobradar.__version__)"` → `OK: 0.1.0`.

- [x] **T4. Configuración**: config.yaml.example, .env.example, config.py (pydantic v2 con bloques search, llm, http, ats, companies)
  - Tests: carga válida, campo faltante con error claro, sin API keys en logs/errores
  - Verificación: `pytest`
  - **Evidencia**: `config.yaml` creado con bloques search, llm, http, ats, companies. `.env.example` con ANTHROPIC_API_KEY y OLLAMA_BASE_URL. `config.py` usa pydantic v2 Settings con validación. Tests en `tests/test_config.py`: 6/6 pasan (carga válida, defaults, campo faltante error claro, API keys no en logs/repr, validación CompanyConfig, env override).

- [x] **T5. examples/cv_master.example.yaml** (datos ficticios, esquema sección 7 con aliases, years, target_titles, eligibility) + test unicidad IDs
  - Verificación: `pytest`
  - **Evidencia**: `examples/cv_master.example.yaml` creado con datos 100% ficticios siguiendo esquema sección 7: basics, summary_facts, target_titles, eligibility (years_experience, work_authorization, relocation, remote_ok), experience (3 empresas, 9 bullets con ids), education (2 con ids), skills (7 con aliases, tags, level, years), certifications, languages. Tests en `tests/test_cv_master_example.py`: 11/11 pasan (carga, secciones requeridas, estructura experience/education/skills, eligibility, IDs únicos, no PII real, target_titles, idiomas).

- [x] **T6. Calidad**: ruff, mypy, pytest con prueba de humo
  - Verificación: `uv run pytest && uv run ruff check . && uv run mypy src`
  - **Evidencia**: `uv run pytest` → 17/17 passed. `uv run ruff check .` → All checks passed. `uv run mypy src` → Success: no issues found in 21 source files.

- [x] **T7. CLI mínima**: entry point "jobradar" con --help y --version
  - Verificación: `uv run jobradar --help`
  - **Evidencia**: `uv run jobradar --help` muestra todos los comandos (probe, ingest, score, requirements, tailor, ats-check) y --version. `uv run jobradar --version` → `jobradar v0.1.0`.

- [x] **T8. README inicial**: qué es, instalación, uso básico, privacidad, ODD en odd/tasks/
  - Verificación: README coincide con comandos reales ejecutados
  - **Evidencia**: `README.md` reescrito con: descripción del proyecto, instalación (`uv sync`), uso básico (todos los comandos `jobradar` probados), sección de privacidad (data/, .env en gitignore, solo texto al LLM sale), referencia a ODD en `odd/tasks/`, stack tecnológico, comandos de calidad. Comandos verificados: `uv run jobradar --help`, `uv run jobradar --version`, `uv run pytest && uv run ruff check . && uv run mypy src`.

## Evidencia observada
_(Se irá completando tras cada tarea)_

## Defectos encontrados
_(Se registrarán si surgen)_

## Cierre
_(Al final: verificación final, resumen, commit final)_