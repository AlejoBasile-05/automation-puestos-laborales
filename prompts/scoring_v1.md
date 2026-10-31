# Prompt de scoring de compatibilidad (v1)

Evalúa la compatibilidad de una vacante contra el CV maestro del candidato.

**Reglas:**
1. Evalúa SOLO con evidencia presente en el CV maestro. No inventes experiencia.
2. Cita la evidencia específica del CV para cada coincidencia (match).
3. No supongas habilidades que no estén explícitamente en el CV.
4. Lista brechas (gaps) con honestidad — lo que la vacante pide y el CV no tiene.
5. Incluye red_flags para problemas como: salario no indicado, seniority muy distinto, idioma requerido no conocido, ubicación incompatible, etc.
6. El score es de 0 a 100.
7. verdict: "aplicar" (score alto, pocos gaps), "quizà" (score medio, algunos gaps), "descartar" (score bajo o gaps críticos).
8. language: "es" si la vacante está en español, "en" si está en inglés.

**Entrada:**
- CV maestro: {cv_master}
- Título de la vacante: {job_title}
- Descripción de la vacante: {job_description}

**Salida JSON:**
{
  "score": 0,
  "verdict": "aplicar | quizá | descartar",
  "matches": ["requisito cubierto y evidencia del CV"],
  "gaps": ["requisito no cubierto"],
  "red_flags": ["alerta relevante"],
  "language": "es | en"
}
