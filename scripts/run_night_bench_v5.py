"""
run_night_bench_v5.py — Versión Corregida (Sin errores de parámetros API).
Diseñado para redacción de larga extensión en Ollama.
"""

import os
os.environ["OLLAMA_API_KEY"] = "ollama" # Forzar clave para evitar RuntimeError de Hermes

import asyncio
import json
import logging
import os
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Any, List
from openai import OpenAI

# ── CONFIGURACIÓN ───────────────────────────────────────────────────
ROOT_DIR      = Path(__file__).parent.parent
OUTPUT_DIR    = ROOT_DIR / "night_bench_v5"
RESULTS_DIR   = OUTPUT_DIR / "posts"
TELEMETRY_FILE = OUTPUT_DIR / "audit_log.jsonl"

for d in (OUTPUT_DIR, RESULTS_DIR):
    d.mkdir(parents=True, exist_ok=True)

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger("NightEngineV5")

client_judge = OpenAI(
  base_url="https://openrouter.ai/api/v1",
  api_key=os.getenv("OPENROUTER_API_KEY"),
)
JUDGE_MODEL = "google/gemini-2.0-flash-lite-001"

@dataclass
class Job:
    id: str
    model: str
    temp: float
    state: str = "pending"
    word_count: int = 0

async def audit_post(content: str) -> dict:
    try:
        completion = client_judge.chat.completions.create(
          model=JUDGE_MODEL,
          messages=[
            {"role": "system", "content": "Eres un editor naval. Evalúa calidad E-E-A-T. JSON: {'score': float, 'justification': str}"},
            {"role": "user", "content": f"Evalúa este post:\n\n{content[:10000]}"}
          ],
          response_format={"type": "json_object"}
        )
        return json.loads(completion.choices[0].message.content)
    except: return {"score": 0.0, "justification": "Fallo auditoría"}

async def run_experiment(job: Job):
    logger.info(f"🚀 Ejecutando: {job.model} (T:{job.temp})")
    from run_agent import AIAgent
    try:
        # 1. INVESTIGADOR
        agent = AIAgent(model=job.model, api_key="ollama", provider="ollama", request_overrides={"temperature": 0.0}, enabled_toolsets=["smart-rag"], quiet_mode=True)
        res = agent.run_conversation("Investiga la Armada Castellana (1248) y El Glorioso (1747). Devuelve hechos técnicos.", system_message="Eres un Investigador experto.")
        facts = res.get("final_response", "Sin hechos.")

        # 2. REDACTOR (Parámetros limpios para evitar TypeError)
        agent = AIAgent(model=job.model, api_key="ollama", provider="ollama", request_overrides={"temperature": job.temp}, enabled_toolsets=["web"], quiet_mode=True)
        res = agent.run_conversation(f"Escribe un post de +2500 palabras sobre la Armada y El Glorioso basado en: {facts}", system_message="Eres un Redactor de élite.")
        draft = res.get("final_response", "")

        # 3. GUARDADO Y AUDITORÍA
        job.word_count = len(draft.split())
        filename = f"post_{job.model.replace(':','_')}_T{job.temp}.md"
        filepath = RESULTS_DIR / filename
        filepath.write_text(draft, encoding="utf-8-sig")

        audit = await audit_post(draft)
        with open(filepath, "a", encoding="utf-8-sig") as f:
            f.write(f"\n\n--- AUDITORÍA ---\nScore: {audit.get('score')}\nJustificación: {audit.get('justification')}")
        
        job.state = "done"
        logger.info(f"✅ Éxito: {job.model} ({job.word_count} palabras)")
    except Exception as e:
        logger.error(f"❌ Error: {e}")
        job.state = "failed"
    finally:
        subprocess.run(["ollama", "stop", job.model], check=False)

async def main():
    MODELS = ["qwen3.5:9b", "qwen2.5:14b", "deepseek-v2:16b"]
    TEMPS = [0.7] # Una sola pasada para asegurar velocidad
    jobs = [Job(id=uuid.uuid4().hex[:4], model=m, temp=t) for m in MODELS for t in TEMPS]
    for job in jobs:
        await run_experiment(job)
        await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(main())
