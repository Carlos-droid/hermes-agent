import asyncio
import time
import json
import os
import sys
import subprocess
from pathlib import Path
from openai import OpenAI

# Añadir el directorio raíz al path para poder importar AIAgent
sys.path.append(str(Path(__file__).parent.parent))

from run_agent import AIAgent
from scripts.monitor_metrics import HermesMonitor, save_report
# Importamos la lógica del juez (simplificada para integración)
from scripts.evaluate_results import evaluate_post, generate_final_report

MODELS_TO_TEST = [
    {"name": "qwen3.5:9b", "provider": "ollama", "base_url": "http://localhost:11434/v1"},
    {"name": "qwen2.5:14b", "provider": "ollama", "base_url": "http://localhost:11434/v1"},
    {"name": "deepseek-v2:16b", "provider": "ollama", "base_url": "http://localhost:11434/v1"},
    {"name": "mistral-nemo:latest", "provider": "ollama", "base_url": "http://localhost:11434/v1"},
    {"name": "gemma4:latest", "provider": "ollama", "base_url": "http://localhost:11434/v1"},
]

# CONFIGURACIÓN DE PARÁMETROS (LIMPIA PARA EVITAR TYPEERRORS)
INVESTIGATOR_PARAMS = {"temperature": 0.0, "top_p": 0.1}
WRITER_PARAMS = {"temperature": 0.85, "top_p": 0.9} # Eliminado num_ctx y penalties conflictivos
CORRECTOR_PARAMS = {"temperature": 0.1, "top_p": 0.1}

# PROMPTS DE SISTEMA
INVESTIGATOR_SYS = "Eres un Investigador Naval experto. Tu única tarea es extraer datos precisos y técnicos usando Smart-RAG."
WRITER_SYS = "Eres un Redactor Editorial de élite. Crea prosa épica y técnica de +2500 palabras. Manten la coherencia y profundidad."
CORRECTOR_SYS = "Eres un Académico de la RAE. Corrige el estilo, la gramática y el léxico técnico del texto."

def clean_environment(model_name):
    print(f"--- Limpiando entorno para {model_name} ---")
    try: subprocess.run(["ollama", "stop", model_name], check=False)
    except: pass
    db_path = Path.home() / ".hermes" / "sessions.db"
    if db_path.exists():
        try: os.remove(db_path)
        except: pass

async def run_full_cycle(model_info):
    model_name = model_info["name"]
    model_id_safe = model_name.replace("/", "_").replace(":", "_")
    print(f"\n>>>> INICIANDO ENSAYO DE 4 ROLES: {model_name} <<<<")
    
    try:
        # --- ROL 1: Investigador ---
        print(f"[{model_name}] Rol 1: Investigador...")
        agent_inv = AIAgent(model=model_name, base_url=model_info["base_url"], api_key="ollama", provider=model_info["provider"], 
                            request_overrides=INVESTIGATOR_PARAMS, enabled_toolsets=["smart-rag"])
        research_prompt = "Utiliza 'smart_rag_query' para investigar la armada castellana (1248) y El Glorioso (1747). Devuelve un resumen técnico de hechos."
        res_inv = agent_inv.run_conversation(research_prompt, system_message=INVESTIGATOR_SYS)
        facts = res_inv.get("final_response", "Error al extraer hechos.")
        
        with open(f"facts_{model_id_safe}.md", "w", encoding="utf-8") as f:
            f.write(facts)
        
        # --- ROL 2: Redactor ---
        print(f"[{model_name}] Rol 2: Redactor...")
        agent_writer = AIAgent(model=model_name, base_url=model_info["base_url"], api_key="ollama", provider=model_info["provider"], 
                               request_overrides=WRITER_PARAMS, enabled_toolsets=["web"])
        writer_prompt = f"Basado en estos hechos:\n{facts}\n\nEscribe un post PROFESIONAL de más de 2500 palabras sobre la armada castellana y El Glorioso. Sé extenso y técnico."
        
        monitor = HermesMonitor(interval=1.0)
        monitor.start()
        start_time = time.time()
        res_writer = agent_writer.run_conversation(writer_prompt, system_message=WRITER_SYS)
        draft = res_writer.get("final_response", "Error en redacción.")
        end_time = time.time()
        metrics_log = monitor.stop()

        with open(f"draft_{model_id_safe}.md", "w", encoding="utf-8") as f:
            f.write(draft)
        
        # --- ROL 3: Corrector ---
        print(f"[{model_name}] Rol 3: Corrector...")
        agent_corr = AIAgent(model=model_name, base_url=model_info["base_url"], api_key="ollama", provider=model_info["provider"], 
                             request_overrides=CORRECTOR_PARAMS, enabled_toolsets=["rae", "file"])
        
        rae_db_path = "C:/Users/carlo/Documents/Proyectos_Phyton/smart-RAG/Smart-RAG-v7-main/smart_rag/data/processed/rae/manual_de_estilo_2018.md"
        corrector_prompt = f"Corrige el estilo y gramática de este borrador:\n\n{draft}"
        res_corr = agent_corr.run_conversation(corrector_prompt, system_message=CORRECTOR_SYS)
        final_post = res_corr.get("final_response", draft) # Fallback al borrador si falla

        with open(f"post_{model_id_safe}.md", "w", encoding="utf-8") as f:
            f.write(final_post)
        
        # --- ROL 4: Juez ---
        print(f"[{model_name}] Rol 4: Juez...")
        total_tokens = len(final_post.split()) * 1.3
        metrics_report = save_report(model_id_safe, metrics_log, start_time, end_time, total_tokens, final_post)
        
        evaluation = evaluate_post(final_post)
        if evaluation:
            evaluation["metrics"] = metrics_report
            generate_final_report(model_id_safe, evaluation, final_post)
            print(f"¡Ensayo completado!")
        
    except Exception as e:
        print(f"ERROR: {e}")
    finally:
        clean_environment(model_name)

async def main():
    for model in MODELS_TO_TEST:
        await run_full_cycle(model)
        await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(main())
