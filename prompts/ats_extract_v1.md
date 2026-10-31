# Prompt de extracción de requisitos ATS (v1)

Extrae los requisitos de una vacante de empleo para análisis ATS.

**Reglas:**
1. Extrae los términos TAL COMO APARECEN en la vacante, incluyendo siglas y su forma completa.
2. Separa keywords en `required` (indispensable, must have, se requiere, requisito) de `preferred` (deseable, plus, nice to have).
3. Captura el `job_title_exact` — el título exacto de la vacante tal como aparece.
4. Ignora relleno corporativo genérico ("proactivo", "dinámico", "trabajo en equipo", "buena comunicación") salvo que sea una competencia concreta y medible.
5. Extrae knockouts (filtros eliminatorios): años de experiencia, educación, idioma, ubicación, certificación, autorización de trabajo, otros.

**Entrada:**
- Descripción de la vacante: {job_description}

**Salida JSON:**
{
  "job_title_exact": "título exacto de la vacante",
  "language": "es | en",
  "keywords": [
    {
      "term": "término tal como aparece",
      "type": "tool | hard_skill | certification | title | domain | methodology | soft_skill",
      "importance": "required | preferred | mentioned",
      "synonyms": ["sigla", "forma completa"],
      "frequency_in_posting": 3
    }
  ],
  "knockouts": [
    {
      "type": "years_experience | education | language | location | certification | work_authorization | other",
      "requirement": "descripción del requisito",
      "value": 3,
      "area": "área relevante o null",
      "mandatory": true
    }
  ]
}
