# Tailoring Prompt v1

## Instrucciones para el LLM:

1. **Uso de términos exactos**:
   - Usar el término exacto de la vacante cuando el CV maestro lo respalde.
   - Siglas y forma completa una vez cada una: "Planeación y análisis financiero (FP&A)".

2. **Ubicación de keywords**:
   - Ubicar keywords `required` en resumen, habilidades y al menos un bullet.
   - 1-3 repeticiones por keyword.

3. **Restricciones**:
   - No tocar keywords `gap`.
   - Solo hechos del CV maestro, nunca inventar.

4. **Longitud**:
   - Máximo 60 palabras para el resumen.
   - Máximo 150 palabras para el mensaje de cobertura.

## Entrada:

Keywords soportados con evidencia:
```
{{keywords_supported}}
```

## Salida esperada:

```json
{
    "headline": "",
    "summary": "",
    "experience": [
        {
            "experience_id": "",
            "bullet_ids": [],
            "rewrites": {}
        }
    ],
    "skills": [],
    "education_ids": [],
    "keywords_used": [],
    "cover_message": ""
}
```
