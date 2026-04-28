"""
run_ensemble_v6_elite.py — EVALUACIÓN DE FORTALEZA PURA (Compatibilidad Total).
Usa el endpoint de OpenAI para hablar con Ollama y evitar bloqueos de clave.
"""

import asyncio
import os
import subprocess
import sys
import time
import uuid
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

ROOT_DIR = Path(__file__).parent.parent
OUTPUT_DIR = ROOT_DIR / "night_bench_v6_elite"
RESULTS_DIR = OUTPUT_DIR / "posts"
LOG_DIR = OUTPUT_DIR / "logs"

for d in (OUTPUT_DIR, RESULTS_DIR, LOG_DIR):
    d.mkdir(parents=True, exist_ok=True)

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger("EliteOrchestrator")

@dataclass
class Job:
    model: str
    state: str = "pending"
    word_count: int = 0
    phases_ok: list = field(default_factory=list)

async def run_full_cycle(job: Job):
    from run_agent import AIAgent
    model_name = job.model
    model_id_safe = model_name.replace(":", "_").replace("/", "_")
    
    try:
        # Usamos el provider 'openai' pero con la URL de Ollama. 
        # Esto engaña a la validación de Hermes y permite pasar una clave cualquiera.
        agent = AIAgent(
            model=model_name,
            api_key="ollama", # Clave ficticia aceptada por el driver OpenAI
            base_url="http://localhost:11434/v1",
            provider="openai", # Driver genérico más robusto
            quiet_mode=True
        )

        # 1. INVESTIGADOR
        logger.info(f"[{model_name}] Rol 1: Investigador...")
        res = agent.run_conversation("Investiga la armada castellana (1248) y El Glorioso (1747). Devuelve hechos técnicos.", 
                                      system_message="Eres un Investigador Naval.")
        facts = res.get("final_response", "")
        if facts: job.phases_ok.append("investigator")

        # 2. REDACTOR
        logger.info(f"[{model_name}] Rol 2: Redactor...")
        res = agent.run_conversation(f"Basado en: {facts}\n\nRedacta un post de +2500 palabras.", 
                                      system_message="Eres un Redactor Editorial.")
        draft = res.get("final_response", "")
        if draft: job.phases_ok.append("writer")

        # 3. CORRECTOR
        logger.info(f"[{model_name}] Rol 3: Corrector...")
        res = agent.run_conversation(f"Corrige el estilo RAE de: {draft}", 
                                      system_message="Eres un Académico de la RAE.")
        final_post = res.get("final_response", draft)
        if final_post: job.phases_ok.append("corrector")

        # GUARDADO
        out_path = RESULTS_DIR / f"post_{model_id_safe}.md"
        out_path.write_text(final_post, encoding="utf-8-sig")
        job.word_count = len(final_post.split())
        job.state = "done"
        
        logger.info(f"✅ FINALIZADO: {model_name} ({job.word_count} palabras)")
        return True

    except Exception as e:
        logger.error(f"❌ ERROR en {model_name}: {e}")
        job.state = "failed"
        return False
    finally:
        subprocess.run(["ollama", "stop", model_name], check=False)

async def main():
    MODELS = ["qwen3.5:9b", "qwen2.5:14b", "deepseek-v2:16b", "mistral-nemo:latest", "gemma4:latest"]
    for m in MODELS:
        job = Job(model=m)
        await run_full_cycle(job)
        await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(main())
