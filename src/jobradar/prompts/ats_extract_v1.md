# Prompt ATS Extract v1

Extrae los requisitos técnicos y filtros eliminatorios de una vacante.

## Instrucciones
1. Extrae términos TAL COMO APARECEN en la vacante
2. Incluye siglas y forma completa
3. Separa required de preferred
4. Ignora relleno corporativo ("proactivo", "dinámico", "trabajo en equipo")
5. Captura el título exacto de la vacante
6. Devuelve JSON válido

## Salida JSON
{
  "job_title_exact": "string",
  "language": "es | en",
  "keywords": [
    {
      "term": "string",
      "type": "tool | hard_skill | certification | title | domain | methodology | soft_skill",
      "importance": "required | preferred | mentioned",
      "synonyms": ["string"],
      "frequency_in_posting": int
    }
  ],
  "knockouts": [
    {
      "type": "years_experience | education | language | location | certification | work_authorization | other",
      "requirement": "string",
      "value": int,
      "area": "string",
      "mandatory": bool
    }
  ]
}