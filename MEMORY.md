# MEMORIA DEL AGENTE HERMES - ORQUESTACIÓN SMART-RAG

## Perfil de Orquestador
Hermes ha sido configurado como el agente superior para coordinar el ecosistema de herramientas editoriales.

## Componentes Integrados (Estado 27/04/2026)
1. **Smart-RAG (v8.6 Swarm)**: 
   - Ruta: `C:\Users\carlo\Documents\Proyectos_Phyton\smart-RAG\autoresearch-RAG`
   - Función: Generación paralela de secciones técnica (+2500 palabras).
   - Herramientas: `tournament_v8_6_swarm.py`, `vigilante.py`.

2. **Smart-RAG (v7.1 Database)**:
   - Ruta: `C:\Users\carlo\Documents\Proyectos_Phyton\smart-RAG\Smart-RAG-v7-main`
   - Función: Base de conocimiento y Qdrant (`smart_rag_unified`).
   - MCP: Servidor RAE alojado en `rae-mpc`.

3. **Bridge de Conexión**:
   - Herramienta: `smart_rag_query` (localizada en `tools/smart_rag_tool.py`).
   - Lógica: `docker exec autoresearch_pipeline python ... vanguard_rag.get_premium_context`.

## Benchmark Actual: Battle of the Titans
Se está ejecutando una prueba analítica para determinar el mejor modelo local (Gemma 4, Qwen 2.5/3.5, DeepSeek V2, Mistral-Nemo) frente al Juez Gigante (DeepSeek R1).
- **Parámetros**: 3 Estaciones (Orquestador 0.1, Redactor 0.85/16k ctx, Juez 0.0).
- **Métricas**: TPS, vRAM, E-E-A-T Score.

## Notas Técnicas
- El límite de contexto mínimo en Hermes se ha bajado a **32,000** tokens para permitir el uso de modelos cuantizados de 14B.
- Se ha inyectado el servidor MCP de la RAE para asegurar calidad léxica.

## Evolución a v8.5 "Oracle Flex" (28/04/2026)
1. **Arquitectura Swarm Handoffs (LangGraph)**:
   - Se migró de una cadena lineal a un grafo de estado cíclico en `run_editorial_v85_master.py`.
   - El sistema opera como una cadena de montaje pasando un `EditorialState` inmutable (Investigador -> Redactor -> Auditor -> Corrector -> Traductor).
   - Hermes actúa como el "Frontier Node", tomando decisiones de enrutamiento y mitigando errores de los subagentes (`AgentFixer / Fail-Fast`).
2. **Sistema Híbrido (Cost-Optimization)**:
   - **Modelos Locales (Costo 0)**: `phi4` (Investigador), `qwen2.5:14b` (Redactor), `gemma4` (Corrector), `translategemma:12b` (Traductor multilingüe a EN/RU/ZH/AR).
   - **Modelos Nube (Eficiencia)**: `Gemini 1.5 Flash` se usa en el nodo de Auditoría para Fact-Checking masivo usando **Context Caching** (para subir pesados manuales de estilo) y **Flex Inference** (para colas de baja prioridad).
3. **Visualización Gráfica del Grafo**:
   - El orquestador exporta automáticamente un mapa visual (código Mermaid) del enjambre a `output_v85/mapa_enjambre_v85.md` cada vez que se ejecuta. Puede ser renderizado en Mermaid Live o GitHub.
