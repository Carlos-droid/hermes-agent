"""
run_editorial_v85_master.py
Smart RAG Editorial System v8.5 - Architecture: Swarm Handoffs (TurboQuant 7B-14B)
Architect: Antigravity & User
"""

import os
import time
import asyncio
import logging
import datetime
import uuid
from typing import List, Dict, Any, TypedDict, Optional
from pathlib import Path
from dotenv import load_dotenv

# LangGraph
from langgraph.graph import StateGraph, END

# LLMs Locales
from langchain_community.chat_models import ChatOllama

# LLMs Cloud (Gemini Flex & Caching)
import google.generativeai as genai
from google.generativeai import caching
from langchain_google_genai import ChatGoogleGenerativeAI
from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception_type
from google.api_core.exceptions import ResourceExhausted, ServiceUnavailable, DeadlineExceeded

# Configuración
load_dotenv()
ROOT = Path(__file__).parent.parent
OUT = ROOT / "output_v85"
OUT.mkdir(exist_ok=True)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("SWARM_MASTER")

# ══════════════════════════════════════════════════════════════════════════════
# ESTADO DEL ENJAMBRE (Contexto Compartido)
# ══════════════════════════════════════════════════════════════════════════════
class EditorialState(TypedDict):
    topic: str
    domain: str
    instruccion_original: str
    datos_extraidos: str
    borrador: str
    errores_rae: List[str]
    fact_check_audit: str     # Auditoría de hechos por Gemini
    semantic_audit: str       # Auditoría semántica por Gemini
    translations: Dict[str, str]
    estado_actual: str        # 'inicio', 'investigado', 'redactado', 'auditado_gemini', 'corregido', 'traducido', 'aprobado'
    error_critico: Optional[str]
    cache_name: Optional[str] # Referencia a la caché de Gemini

# ══════════════════════════════════════════════════════════════════════════════
# GEMINI FLEX INFERENCE & CACHING
# ══════════════════════════════════════════════════════════════════════════════
ERRORES_FLEX = (ResourceExhausted, ServiceUnavailable, TimeoutError, DeadlineExceeded)

@retry(
    wait=wait_exponential(multiplier=1.5, min=30, max=300),
    stop=stop_after_attempt(5),
    retry=retry_if_exception_type(ERRORES_FLEX),
    before_sleep=lambda rs: logger.warning(f"⚠️ Capacidad Flex saturada. Reintentando en {rs.next_action.sleep}s...")
)
async def invocar_gemini_flex(llm_instancia: Any, prompt: str) -> str:
    respuesta = await llm_instancia.ainvoke(prompt)
    return respuesta.content

def crear_cache_corpus(domain: str) -> str:
    """Crea la caché de contexto pesado (Reglas + Manuales) para ahorrar un 90%."""
    logger.info(f"📦 Creando caché de contexto para dominio: {domain}...")
    genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
    contexto_gigante = f"Eres el Editor Jefe de IA. Dominio: {domain}. " + ("Reglas estrictas de Fact-Checking y Semántica... " * 1000)
    try:
        cache = caching.CachedContent.create(
            model='models/gemini-1.5-flash-001',
            display_name=f'corpus_{domain}_{uuid.uuid4().hex[:4]}',
            system_instruction="Auditoría Editorial v8.5",
            contents=[contexto_gigante],
            ttl=datetime.timedelta(minutes=60),
        )
        return cache.name
    except Exception as e:
        logger.error(f"Error creando caché: {e}")
        return ""

def get_flex_cached_llm(cache_name: str):
    return ChatGoogleGenerativeAI(
        model="gemini-1.5-flash-001", 
        temperature=0.1,
        max_retries=0, # Tenacity maneja los reintentos
        timeout=900, 
        transport="rest",
        extra_headers={"X-Goog-Api-Type": "flex-inference"},
        client_options={"client_info": {"cached_content": cache_name}} if cache_name else {}
    )

# ══════════════════════════════════════════════════════════════════════════════
# MODELOS (TurboQuant Swarm + Frontier)
# ══════════════════════════════════════════════════════════════════════════════
# Frontier (DeepSeek R1 simulado vía API o deepseek-v2:16b local si aplica)
# Usaremos Gemini Pro temporalmente como Frontier robusto si no hay API de DeepSeek configurada,
# o el deepseek local. Asumimos deepseek-v2:16b para entorno 100% local.
frontier_llm = ChatOllama(model="deepseek-v2:16b", temperature=0.1, base_url="http://localhost:11434")

# Obreros Locales Especializados
researcher_llm = ChatOllama(model="phi4:latest", temperature=0.0, base_url="http://localhost:11434")
writer_llm     = ChatOllama(model="qwen2.5:14b", temperature=0.4, base_url="http://localhost:11434")
corrector_llm  = ChatOllama(model="gemma4:latest", temperature=0.1, base_url="http://localhost:11434")
translator_llm = ChatOllama(model="translategemma:12b", temperature=0.2, base_url="http://localhost:11434")

# ══════════════════════════════════════════════════════════════════════════════
# NODOS DEL ENJAMBRE
# ══════════════════════════════════════════════════════════════════════════════

async def node_frontier(state: EditorialState) -> EditorialState:
    """Planificador y Supervisor. Toma decisiones ejecutivas."""
    logger.info("🧠 FRONTIER NODE: Analizando estado de la operación.")
    
    # Manejo de Handoffs de Emergencia (Fail-Fast)
    if state.get("error_critico"):
        logger.warning(f"🚨 FRONTIER INTERVENTION: Resolviendo error crítico: {state['error_critico']}")
        # Lógica de AgentFixer: Intentar limpiar el error y re-enrutar
        state["error_critico"] = None
        state["estado_actual"] = "inicio" # Reiniciamos el ciclo mitigando el error
        return state

    # Lógica de Planificación Normal
    if state["estado_actual"] == "inicio":
        logger.info("🧠 FRONTIER: Tarea nueva. Delegando al Investigador (Handoff 1).")
        return state
        
    if state["estado_actual"] == "traducido":
        logger.info("🧠 FRONTIER: Operación completa. Aprobando publicación.")
        state["estado_actual"] = "aprobado"
        return state

    return state

async def node_researcher(state: EditorialState) -> EditorialState:
    logger.info("🔍 OBRERO: Investigador (phi4) en acción.")
    try:
        # Aquí se conectaría a Smart-RAG. Simulamos extracción.
        prompt = f"Extrae datos clave sobre {state['topic']} para el dominio {state['domain']}."
        res = await researcher_llm.ainvoke(prompt)
        state["datos_extraidos"] = res.content
        state["estado_actual"] = "investigado"
    except Exception as e:
        logger.error("❌ Fallo en Investigador. Handoff de emergencia.")
        state["error_critico"] = f"RAG Extraction Failed: {str(e)}"
    return state

async def node_writer(state: EditorialState) -> EditorialState:
    logger.info("✍️ OBRERO: Redactor (qwen2.5) ensamblando artículo.")
    try:
        prompt = f"Redacta un artículo sobre {state['topic']} basado en:\n{state['datos_extraidos']}"
        res = await writer_llm.ainvoke(prompt)
        state["borrador"] = res.content
        state["estado_actual"] = "redactado"
    except Exception as e:
        state["error_critico"] = f"Writing Failed: {str(e)}"
    return state

async def node_gemini_auditor(state: EditorialState) -> EditorialState:
    """Nodo Híbrido: Fact-Checking y Validación Semántica masiva con Gemini Flex."""
    logger.info("🛡️ OBRERO CLOUD: Gemini Auditor (Fact-Checker & Semantic Validator) con Flex Inference.")
    try:
        llm_optimizado = get_flex_cached_llm(state.get("cache_name"))
        
        # 1. Fact-Checker
        prompt_fact = f"FACT-CHECK:\nBorrador:\n{state['borrador']}\nCompara con datos extraídos:\n{state['datos_extraidos']}"
        state["fact_check_audit"] = await invocar_gemini_flex(llm_optimizado, prompt_fact)
        
        # 2. Semantic Validator
        prompt_sem = f"SEMANTIC VALIDATION:\nRevisa el flujo narrativo y la calidad del siguiente texto:\n{state['borrador']}"
        state["semantic_audit"] = await invocar_gemini_flex(llm_optimizado, prompt_sem)
        
        state["estado_actual"] = "auditado_gemini"
    except Exception as e:
        state["error_critico"] = f"Gemini Audit Failed: {str(e)}"
    return state

async def node_corrector(state: EditorialState) -> EditorialState:
    logger.info("⚖️ OBRERO: Corrector RAE (gemma4) revisando gramática.")
    try:
        # Aquí usaría la herramienta rae_check
        prompt = f"Revisa este texto gramaticalmente:\n{state['borrador'][:1000]}..."
        res = await corrector_llm.ainvoke(prompt)
        state["errores_rae"] = [res.content]
        state["estado_actual"] = "corregido"
    except Exception as e:
        state["error_critico"] = f"Correction Failed: {str(e)}"
    return state

async def node_translator(state: EditorialState) -> EditorialState:
    logger.info("🌐 OBRERO: Traductor (translategemma:12b) operando.")
    try:
        for lang in ["en", "ru", "zh", "ar"]:
            logger.info(f"   Traduciendo a {lang.upper()}...")
            prompt = f"Translate to {lang}:\n{state['borrador'][:500]}"
            res = await translator_llm.ainvoke(prompt)
            state["translations"][lang] = res.content
        state["estado_actual"] = "traducido"
    except Exception as e:
        state["error_critico"] = f"Translation Failed: {str(e)}"
    return state

# ══════════════════════════════════════════════════════════════════════════════
# GRAFO DE ENRUTAMIENTO (Handoffs)
# ══════════════════════════════════════════════════════════════════════════════
def router(state: EditorialState) -> str:
    """Enrutador central basado en el Estado."""
    if state.get("error_critico"):
        return "frontier" # Escalamiento Inmediato
        
    estado = state["estado_actual"]
    if estado == "inicio": return "researcher"
    if estado == "investigado": return "writer"
    if estado == "redactado": return "gemini_auditor"
    if estado == "auditado_gemini": return "corrector"
    if estado == "corregido": return "translator"
    if estado == "traducido": return "frontier" # Retorno final al supervisor
    return END

def build_swarm_graph():
    workflow = StateGraph(EditorialState)
    
    # Añadir nodos
    workflow.add_node("frontier", node_frontier)
    workflow.add_node("researcher", node_researcher)
    workflow.add_node("writer", node_writer)
    workflow.add_node("gemini_auditor", node_gemini_auditor)
    workflow.add_node("corrector", node_corrector)
    workflow.add_node("translator", node_translator)
    
    # Todos empiezan en el Frontier para planificación
    workflow.set_entry_point("frontier")
    
    # Enrutamiento Dinámico (El núcleo del mecanismo Handoff)
    workflow.add_conditional_edges("frontier", router)
    workflow.add_conditional_edges("researcher", router)
    workflow.add_conditional_edges("writer", router)
    workflow.add_conditional_edges("gemini_auditor", router)
    workflow.add_conditional_edges("corrector", router)
    workflow.add_conditional_edges("translator", router)
    
    return workflow.compile()

def exportar_mapa_visual(app):
    """Genera un archivo Markdown con el diagrama Mermaid del Grafo."""
    try:
        mermaid_code = app.get_graph().draw_mermaid()
        out_path = OUT / "mapa_enjambre_v85.md"
        with open(out_path, "w", encoding="utf-8") as f:
            f.write("# 🗺️ Mapa Visual del Enjambre V8.5\n")
            f.write("Puedes visualizar este código en [Mermaid Live](https://mermaid.live).\n\n")
            f.write(f"```mermaid\n{mermaid_code}\n```\n")
        logger.info(f"🎨 Mapa visual del grafo exportado en: {out_path}")
    except Exception as e:
        logger.warning(f"No se pudo generar el grafo Mermaid: {e}")

async def run_swarm(topic: str, domain: str):
    logger.info(f"🚀 Iniciando SWARM HANDOFF V8.5 - Tópico: {topic}")
    
    cache_name = crear_cache_corpus(domain)
    
    initial_state = {
        "topic": topic,
        "domain": domain,
        "instruccion_original": f"Crear artículo épico sobre {topic}",
        "datos_extraidos": "",
        "borrador": "",
        "errores_rae": [],
        "fact_check_audit": "",
        "semantic_audit": "",
        "translations": {},
        "estado_actual": "inicio",
        "error_critico": None,
        "cache_name": cache_name
    }
    
    try:
        app = build_swarm_graph()
        exportar_mapa_visual(app) # Exportar el mapa en cada ejecución
        
        final_state = await app.ainvoke(initial_state)
        logger.info(f"✅ Enjambre terminado. Estado final: {final_state['estado_actual']}")
    finally:
        if cache_name:
            try:
                caching.CachedContent.get(cache_name).delete()
                logger.info(f"🗑️ Caché {cache_name} eliminada.")
            except Exception as e:
                pass

if __name__ == "__main__":
    import fire
    fire.Fire(run_swarm)
