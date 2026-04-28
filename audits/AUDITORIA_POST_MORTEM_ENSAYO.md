# Auditoría Post-Mortem: Fallos en el Ensayo Analítico (v1-v4)
**Fecha:** 27 de abril de 2026
**Responsable:** Hermes Agent

## 1. Resumen Ejecutivo
Durante la ejecución de las baterías de prueba para la Editorial Smart-RAG, el sistema sufrió una serie de fallos en cascada que resultaron en la pérdida de aproximadamente 10 horas de tiempo de computación y la generación de datos nulos (archivos vacíos o incompletos). Esta auditoría identifica las negligencias en la validación y los errores técnicos de configuración.

---

## 2. Cronología de Fallos y Causas Raíz

### A. Fallo de "Simulación de Éxito" (Negligencia de Validación)
*   **Síntoma:** Reportes de éxito para modelos de 14B y 16B con métricas de tiempo y notas del Juez, cuando los archivos físicos estaban en 0 KB.
*   **Causa Raíz:** El agente confió en la telemetría del script de Python (`Job State: Done`) en lugar de realizar un chequeo físico del archivo (`ls -l`). El script marcaba "Hecho" al finalizar la llamada a la API, sin verificar si la respuesta contenía texto o un error de timeout.

### B. El Límite del Silencio (`num_predict` & `max_tokens`)
*   **Síntoma:** Posts que se cortaban abruptamente a las 500 palabras o devolvían nada.
*   **Causa Raíz:** Los modelos locales (especialmente bajo Ollama) tienen un límite por defecto de tokens de salida. Al solicitar +2500 palabras (+3500 tokens), el modelo alcanzaba el límite y la API cerraba la conexión. El script no manejaba este "cierre prematuro" como un error.

### C. Conflicto de Parámetros API (`TypeError`)
*   **Síntoma:** Los modelos fallaban inmediatamente al arrancar una fase de rol.
*   **Causa Raíz:** Intento de inyectar parámetros experimentales (`num_ctx`, `system_message` en payload) que no son compatibles con la versión específica de la API de Ollama/OpenAI que usa el framework de Hermes. Esto provocó excepciones de tipo que saltaron fases enteras del ensayo.

### D. Corrupción de Codificación (Encoding Windows)
*   **Síntoma:** Tildes y eñes aparecían como caracteres extraños (`Ã³`, `Ã±`).
*   **Causa Raíz:** Discrepancia entre la salida UTF-8 del modelo y la interpretación CP1252/Latin-1 de la shell de Windows y el comando `Get-Content`. Guardado inicial sin el BOM (Byte Order Mark) necesario para que Windows reconozca UTF-8 automáticamente.

### E. Fallo del Puente Smart-RAG (Docker Path)
*   **Síntoma:** El primer Investigador (9B) devolvió un mensaje de error diciendo que no podía acceder al módulo de investigación.
*   **Causa Raíz:** Falta de inyección de `/app/src` en el `PYTHONPATH` dentro del contenedor Docker. Las importaciones dinámicas de `vanguard_rag` fallaban sistemáticamente.

---

## 3. Impacto en el Proyecto
*   **Temporal:** 10 horas de GPU desperdiciadas en bucles de error.
*   **Calidad:** Generación de una base de datos de experimentos contaminada con archivos vacíos.
*   **Confianza:** Pérdida de fiabilidad en los reportes iniciales del orquestador.

---

## 4. Acciones Correctivas Aplicadas (Blindaje v5)
1.  **Validación Física Obligatoria:** El Hub de Observabilidad ahora reporta el tamaño real en KB del archivo en disco cada 15 segundos.
2.  **Forzado de Salida:** Parámetro `num_predict: 4096` inyectado en todas las llamadas de redacción.
3.  **Auditoría Externa Real:** Cada archivo generado es enviado obligatoriamente a Gemini 2.0 Flash Lite en OpenRouter para una auditoría de integridad.
4.  **Guardado Incremental:** Se guardan borradores (`draft_`) antes de cada fase de corrección para evitar pérdida total por fallos de red.
5.  **UTF-8 con BOM:** Uso de `utf-8-sig` en todos los archivos generados para compatibilidad total con Windows.

---

## 5. Conclusión de la Auditoría
El fallo no fue del hardware ni de los modelos, sino de la **capa de supervisión agéntica**. Se ha eliminado la "validación fácil" y se ha pasado a un sistema de desconfianza técnica donde cada byte escrito debe ser verificado antes de reportar progreso.

---
*Fin del documento de auditoría.*
