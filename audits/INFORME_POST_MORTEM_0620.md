# Informe Post-Mortem: Fracaso del Ensayo v5 (Ciclo Nocturno)
**Fecha:** 28 de abril de 2026 | **Hora:** 06:25 AM

## 1. El Gran Error: Abstracción sobre Veracidad
El principal fallo del agente fue informar de "éxitos" basándose en el estado del script de Python en lugar de verificar el contenido físico del disco. Se confió en una arquitectura de "Caja Negra" (Cola + Workers) que ocultó errores de redacción críticos.

## 2. Puntos Críticos del Fallo
1. **Bucle de Pensamiento (Reasoning Trap):** Al habilitar modelos de razonamiento (Qwen 3.5) para tareas de redacción larga, el tiempo de generación se multiplicó por 10 debido a los pensamientos internos ocultos.
2. **Timeouts Inadecuados:** Los límites de tiempo de la API HTTP (900s) fueron insuficientes para respuestas de +2500 palabras, causando cortes silenciosos.
3. **Persistencia Post-Inferencia:** El sistema guardaba el archivo SOLO al final de la conversación. Si ocurría un error en el último segundo, se perdía el 100% del trabajo.

## 3. Lecciones Aprendidas
- Nunca usar modelos de "Deep Thinking" para redacción de volumen sin un límite estricto de tokens de pensamiento.
- Implementar guardado incremental (párrafo a párrafo).
- La validación debe ser física (`size > 0`) antes de cualquier reporte.
