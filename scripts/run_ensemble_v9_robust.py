"""
run_ensemble_v9_robust.py — Sistema de ensayo industrial (Versión Corregida 9.1).
"""

import asyncio
import json
import logging
import os
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Optional
from concurrent.futures import ThreadPoolExecutor
import traceback
import subprocess

# Forzar clave de Ollama
os.environ["OLLAMA_API_KEY"] = "ollama"

ROOT = Path(__file__).parent.parent
OUT = ROOT / "v9_output"
LOGS = OUT / "logs"
POSTS = OUT / "posts"

for d in (OUT, LOGS, POSTS):
    d.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOGS / "v9.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("v9")

TELEMETRY_FILE = LOGS / "telemetry.jsonl"
EXECUTOR = ThreadPoolExecutor(max_workers=1)

def log_event(trace_id, model, phase, action, **kw):
    event = {"ts": datetime.now(timezone.utc).isoformat(), "trace_id": trace_id, "model": model, "phase": phase, "action": action, **kw}
    with open(TELEMETRY_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")
    logger.info(f"[{trace_id[:8]}] {model}/{phase}/{action} {kw}")

@dataclass
class Job:
    model: str
    trace_id: str = field(default_factory=lambda: f"v9_{uuid.uuid4().hex[:6]}")
    state: str = "pending"
    word_count: int = 0
    phases: List[str] = field(default_factory=list)

async def run_full_cycle(job: Job):
    from run_agent import AIAgent
    model_name = job.model
    model_id_safe = model_name.replace(":", "_").replace("/", "_")
    t_start = time.time()
    
    try:
        # Agent instance (Driver OpenAI para Ollama)
        agent = AIAgent(model=model_name, api_key="ollama", base_url="http://localhost:11434/v1", provider="openai", quiet_mode=True)

        # 1. INVESTIGADOR
        logger.info(f"[{model_name}] Rol 1: Investigador...")
        res = agent.run_conversation("Investiga la armada castellana (1248) y El Glorioso (1747). Hechos técnicos.", system_message="Eres un Investigador Naval.")
        facts = res.get("final_response", "")
        if facts: job.phases.append("investigator")

        # 2. REDACTOR
        logger.info(f"[{model_name}] Rol 2: Redactor...")
        res = agent.run_conversation(f"Basado en: {facts}\n\nRedacta un post de +2500 palabras.", system_message="Eres un Redactor Editorial.")
        final_post = res.get("final_response", "")
        if final_post: job.phases.append("writer")

        # GUARDADO
        out_path = POSTS / f"post_{model_id_safe}.md"
        out_path.write_text(final_post, encoding="utf-8-sig")
        job.word_count = len(final_post.split())
        job.state = "done"
        return True
    except Exception as e:
        logger.error(f"Fallo en {model_name}: {e}")
        return False
    finally:
        subprocess.run(["ollama", "stop", model_name], check=False)

async def main():
    MODELS = ["qwen3.5:9b", "qwen2.5:14b", "deepseek-v2:16b"]
    for m in MODELS:
        job = Job(model=m)
        await run_full_cycle(job)
        await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(main())
