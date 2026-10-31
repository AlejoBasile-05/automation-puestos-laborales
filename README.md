# JobRadar

Radar local de vacantes + CV a la medida para ATS.

## Instalación

```bash
uv sync
```

## Uso básico

```bash
uv run jobradar --help
```

## Privacidad

- Los datos personales (CV, API keys) nunca salen de la máquina
- Solo el texto enviado al LLM configurado sale de la máquina
- `data/` y `.env` están en `.gitignore`