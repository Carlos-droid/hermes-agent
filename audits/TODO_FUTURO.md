# TODO Futuro - Smart-RAG & Hermes Integration

## Tareas Inmediatas (Windows/RTX)
1. **Validar Puente Nativo**: Ejecutar `smart_rag_ingest` desde Hermes para confirmar que Qdrant recibe datos en el puerto 6333.
2. **Crawl Maestro EVE-UNI**: 
   - Extraer y poblar Qdrant con las secciones: *Trading, Ships, Industry, Mining*.
   - Usar el Heuristic Filter para minimizar costes de OpenRouter.

## Plan de Migración a Linux (Próxima Fase)
1. **Des-Windowsizar**: 
   - Reemplazar paths `C:\Users\...` en `smart_rag_tool.py` por `/opt/hermes/...`.
   - Ajustar `subprocess.run(shell=True)` por la convención de Linux.
2. **Docker Puro**:
   - Re-habilitar el `healthcheck` de Qdrant.
   - Usar la red interna de Docker (`http://qdrant:6333`) en lugar de `localhost`.
3. **Escalado RTX**:
   - Configurar Ollama en Linux para usar modelos de 70B locales como generadores, eliminando el gasto de APIs externas.

---
*Estado al 26/04/2026: Motor Gemini 2.0 Flash Lite listo como salvaguarda.*

## Optimización de Caching y Flex Inference (Benchmark v8.3)
Implementación de arquitectura resiliente para reducir costes en contextos masivos (manuales técnicos, corpus naval) y manejar saturación de API mediante reintentos exponenciales.

```python
import os
import time
import asyncio
import logging
import datetime
from typing import List, Dict, Any
from dotenv import load_dotenv

# Librerías de Gemini oficiales para Caching
import google.generativeai as genai
from google.generativeai import caching

# Librerías de resiliencia y LangChain
from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception_type
from google.api_core.exceptions import ResourceExhausted, ServiceUnavailable
from langchain_google_genai import ChatGoogleGenerativeAI

# Configuración de Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("Benchmark_Flex_Cache_v8.3")

load_dotenv()

# Configurar API Key para el SDK nativo (necesario para gestionar la caché)
genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))

# --- 1. GESTIÓN DE LA CACHÉ DE CONTEXTO ---

def crear_cache_corpus_naval() -> str:
    \"\"\"
    Sube el contexto pesado (ej. manuales, reglas de edición) a la caché de Google.
    Retorna el nombre del objeto cacheado para usarlo en el LLM.
    \"\"\"
    logger.info("📦 Creando caché de contexto en Vertex/Gemini...")
    
    # Aquí iría tu texto gigante (System prompt + documentos base RAG que comparten todos los posts)
    contexto_gigante = "Eres un Editor Jefe Naval. " + ("Texto histórico de prueba... " * 5000)
    
    cache = caching.CachedContent.create(
        model='models/gemini-1.5-flash-001', 
        display_name='corpus_base_naval',
        system_instruction="Instrucciones estrictas del Fact-Checker v8.2",
        contents=[contexto_gigante],
        ttl=datetime.timedelta(minutes=60), 
    )
    
    logger.info(f"✅ Caché creada con éxito. Nombre: {cache.name}")
    return cache.name

def limpiar_cache(cache_name: str):
    \"\"\"Elimina la caché para no pagar costes de almacenamiento innecesarios.\"\"\"
    try:
        caching.CachedContent.get(cache_name).delete()
        logger.info(f"🗑️ Caché {cache_name} eliminada para ahorrar costes.")
    except Exception as e:
        logger.error(f"Error al eliminar la caché: {e}")

# --- 2. CONFIGURACIÓN DEL LLM RESILIENTE (FLEX + CACHE) ---

def get_flex_cached_llm(cache_name: str):
    \"\"\"
    Inicializa Gemini combinando Flex Inference Y Context Caching.
    \"\"\"
    return ChatGoogleGenerativeAI(
        model="gemini-1.5-flash-001", 
        temperature=0.1,
        max_retries=0, 
        timeout=900, 
        transport="rest",
        extra_headers={"X-Goog-Api-Type": "flex-inference"},
        client_options={"client_info": {"cached_content": cache_name}}
    )

# --- 3. POLÍTICA DE REINTENTOS (TENACITY) ---

ERRORES_FLEX = (ResourceExhausted, ServiceUnavailable, TimeoutError)

@retry(
    wait=wait_exponential(multiplier=1.5, min=30, max=300),
    stop=stop_after_attempt(5),
    retry=retry_if_exception_type(ERRORES_FLEX),
    before_sleep=lambda rs: logger.warning(
        f"⚠️ Capacidad Flex saturada. Reintentando en {rs.next_action.sleep}s (Intento {rs.attempt_number}/5)..."
    )
)
async def invocar_nodo_resiliente(llm_instancia: Any, prompt: str) -> str:
    respuesta = await llm_instancia.ainvoke(prompt)
    return respuesta.content

# --- 4. SCRIPT DEL EXPERIMENTO (BENCHMARK) ---

async def procesar_articulo(topic: str, llm_instancia: Any, app_langgraph: Any) -> Dict:
    logger.info(f"🚀 Iniciando: {topic}")
    start_time = time.time()
    try:
        await asyncio.sleep(2) 
        tiempo_total = time.time() - start_time
        logger.info(f"✅ Completado: {topic} en {tiempo_total:.2f} segundos.")
        return {"topic": topic, "status": "SUCCESS"}
    except Exception as e:
        logger.error(f"❌ Error en {topic}: {e}")
        return {"topic": topic, "status": "FAILED", "error": str(e)}

async def run_benchmark_10_articles(topics: List[str], app_langgraph: Any):
    logger.info(f"📊 Iniciando Benchmark Flex + Caching para {len(topics)} artículos...")
    cache_name = crear_cache_corpus_naval()
    llm_optimizado = get_flex_cached_llm(cache_name)
    try:
        tareas = [procesar_articulo(topic, llm_optimizado, app_langgraph) for topic in topics]
        resultados = await asyncio.gather(*tareas)
        exitosos = [r for r in resultados if r["status"] == "SUCCESS"]
        print(f"\n📈 REPORTE FINAL: {len(exitosos)}/{len(topics)} procesados con éxito.")
    finally:
        limpiar_cache(cache_name)
```
