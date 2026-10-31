# Prompt Tailoring v1

Genera un CV adaptado a una vacante usando SOLO keywords supported con evidencia.

## Instrucciones
1. Usa el término EXACTO de la vacante cuando el maestro lo respalda
2. Siglas y forma completa una vez cada una
3. Ubica keywords required/supported en: resumen, habilidades, al menos 1 bullet
4. Frecuencia: 1-3 veces por keyword (máx 3)
5. NO toques keywords gap
6. Headline: usa job_title_exact solo si coincide con target_titles o cargo real
7. Idioma: el de la vacante (es/en)
8. Devuelve JSON válido

## Entrada
- Keywords supported con evidencia (ids del CV maestro)
- CV maestro completo
- Título exacto de la vacante

## Salida JSON
{
  "headline": "string corto",
  "summary": "máx 60 palabras, solo hechos de summary_facts y bullets",
  "experience": [
    {
      "experience_id": "string",
      "bullet_ids": ["string"],
      "rewrites": { "bullet_id": "versión reordenada" }
    }
  ],
  "skills": ["string"],
  "education_ids": ["string"],
  "keywords_used": ["string"],
  "cover_message": "máx 150 palabras, específico empresa/puesto"
}