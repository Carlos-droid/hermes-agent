"""
run_ensemble_v3_distributed.py — Arquitectura de Cola + Workers para Ensayo Industrial.
Integra Heartbeat, Telemetría JSONL y Retries automáticos.
"""

import asyncio
import json
import logging
import os
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Any, List

# ── CONFIGURACIÓN DE RUTAS ───────────────────────────────────────────────────
ROOT_DIR      = Path(__file__).parent.parent
OUTPUT_DIR    = ROOT_DIR / "output"
LOG_DIR       = ROOT_DIR / "logs"
TELEMETRY_FILE = LOG_DIR / "structured_log_v3.jsonl"
RESULTS_DIR   = OUTPUT_DIR / "posts"
REPORT_FILE   = OUTPUT_DIR / "ensemble_report_v3.md"

for d in (OUTPUT_DIR, LOG_DIR, RESULTS_DIR):
    d.mkdir(parents=True, exist_ok=True)

# ── LOGGING ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler(LOG_DIR / "ensemble_v3.log", encoding="utf-8")]
)
logger = logging.getLogger("EnsembleOrchestrator")

# ── MODELO DE DATOS (JOB) ────────────────────────────────────────────────────
@dataclass
class Job:
    id: str
    model_info: dict
    state: str = "pending"  # pending | running | done | failed
    retries: int = 0
    max_retries: int = 2
    phases_ok: List[str] = field(default_factory=list)
    word_count: int = 0
    duration: float = 0.0
    error: Optional[str] = None
    result_data: dict = field(default_factory=dict)

# ── COLA GLOBAL ──────────────────────────────────────────────────────────────
job_queue = asyncio.Queue()
result_queue = asyncio.Queue()

# ── CONFIGURACIÓN DE ROLES & TIMEOUTS ──────────────────────────────────────────
PHASE_TIMEOUTS = {"investigator": 300, "writer": 1200, "corrector": 300, "judge": 180}
RAE_DB_PATH = "C:/Users/carlo/Documents/Proyectos_Phyton/smart-RAG/Smart-RAG-v7-main/smart_rag/data/processed/rae/manual_de_estilo_2018.md"

# ── TELEMETRÍA ───────────────────────────────────────────────────────────────
def log_event(trace_id, model, phase, action, **metrics):
    event = {"trace_id": trace_id, "timestamp": datetime.now(timezone.utc).isoformat(), "model": model, "phase": phase, "action": action, **metrics}
    with open(TELEMETRY_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")

# ── WORKER (CONSUMIDOR) ──────────────────────────────────────────────────────
async def worker(worker_id: str):
    logger.info(f"👷 Worker {worker_id} iniciado.")
    while True:
        job: Job = await job_queue.get()
        job.state = "running"
        model_name = job.model_info["name"]
        
        try:
            logger.info(f"[{worker_id}] Procesando Job {job.id} ({model_name})")
            result = await run_full_cycle(job)
            
            if result:
                job.state = "done"
                await result_queue.put(job)
            else:
                raise Exception("Ciclo de ejecución devolvió Falso/Vacio")

        except Exception as e:
            job.retries += 1
            logger.error(f"❌ Error en Job {job.id} ({model_name}): {e}")
            if job.retries <= job.max_retries:
                logger.info(f"🔄 Reencolando Job {job.id} (Intento {job.retries})")
                await job_queue.put(job)
            else:
                job.state = "failed"
                job.error = str(e)
                await result_queue.put(job)
        finally:
            # Limpieza de Ollama post-job
            subprocess.run(["ollama", "stop", model_name], check=False)
            job_queue.task_done()

# ── EL MOTOR DE EJECUCIÓN (Lógica de los 4 Roles) ─────────────────────────────
async def run_full_cycle(job: Job) -> bool:
    m = job.model_info
    trace_id = job.id
    model_name = m["name"]
    model_id_safe = model_name.replace(":", "_").replace("/", "_")
    t_start = time.time()

    try:
        from run_agent import AIAgent
        from scripts.monitor_metrics import save_report
        from scripts.evaluate_results import evaluate_post, generate_final_report

        # 1. INVESTIGADOR
        print(f"   [Role: Investigator] {model_name}...")
        agent = AIAgent(model=model_name, base_url=m["base_url"], api_key="ollama", provider=m["provider"], 
                        request_overrides={"temperature": 0.0}, enabled_toolsets=["smart-rag"], quiet_mode=True)
        res = agent.run_conversation("Utiliza 'smart_rag_query' para investigar la armada castellana y El Glorioso. Resumen técnico.", 
                                      system_message="Eres un Investigador experto.")
        facts = res.get("final_response", "")
        if facts: job.phases_ok.append("investigator")
        Path(LOG_DIR / f"facts_{model_id_safe}.md").write_text(facts, encoding="utf-8")

        # 2. REDACTOR
        print(f"   [Role: Writer] {model_name}...")
        agent = AIAgent(model=model_name, base_url=m["base_url"], api_key="ollama", provider=m["provider"], 
                        request_overrides={"temperature": 0.85, "num_ctx": 32768}, enabled_toolsets=["web"], quiet_mode=True)
        res = agent.run_conversation(f"Basado en:\n{facts}\n\nRedacta el post de +2500 palabras.", 
                                      system_message="Eres un Redactor de élite.")
        draft = res.get("final_response", "")
        if draft: job.phases_ok.append("writer")
        Path(LOG_DIR / f"draft_{model_id_safe}.md").write_text(draft, encoding="utf-8")

        # 3. CORRECTOR
        print(f"   [Role: Corrector] {model_name}...")
        agent = AIAgent(model=model_name, base_url=m["base_url"], api_key="ollama", provider=m["provider"], 
                        request_overrides={"temperature": 0.1}, enabled_toolsets=["rae", "file"], quiet_mode=True)
        res = agent.run_conversation(f"Corrige este texto usando 'rae_check':\n\n{draft}", 
                                      system_message="Eres un Académico de la RAE.")
        final_post = res.get("final_response", draft)
        if res.get("final_response"): job.phases_ok.append("corrector")
        
        out_path = RESULTS_DIR / f"post_{model_id_safe}.md"
        out_path.write_text(final_post, encoding="utf-8")
        job.word_count = len(final_post.split())

        # 4. JUEZ
        print(f"   [Role: Judge] Evaluando...")
        eval_data = evaluate_post(final_post)
        if eval_data:
            job.phases_ok.append("judge")
            job.result_data = eval_data
            generate_final_report(model_id_safe, eval_data, final_post)

        job.duration = time.time() - t_start
        return True

    except Exception as e:
        job.error = str(e)
        return False

# ── MAIN ─────────────────────────────────────────────────────────────────────
async def main():
    MODELS = [
        {"name": "qwen3.5:9b", "provider": "ollama", "base_url": "http://localhost:11434/v1"},
        {"name": "qwen2.5:14b", "provider": "ollama", "base_url": "http://localhost:11434/v1"},
        {"name": "deepseek-v2:16b", "provider": "ollama", "base_url": "http://localhost:11434/v1"},
        {"name": "mistral-nemo:latest", "provider": "ollama", "base_url": "http://localhost:11434/v1"},
        {"name": "gemma4:latest", "provider": "ollama", "base_url": "http://localhost:11434/v1"},
    ]

    logger.info("🚀 SISTEMA DE COLA ACTIVADO - Cargando Jobs...")
    for m in MODELS:
        await job_queue.put(Job(id=f"job_{uuid.uuid4().hex[:4]}", model_info=m))

    # Definir Workers (1 por hardware local, 2 si tienes 24GB+ vRAM)
    NUM_WORKERS = 1 
    workers = [asyncio.create_task(worker(f"W-{i}")) for i in range(NUM_WORKERS)]

    # Recolectar resultados
    all_jobs = []
    for _ in range(len(MODELS)):
        completed_job = await result_queue.get()
        all_jobs.append(completed_job)
        logger.info(f"✅ Job {completed_job.id} terminado (Estado: {completed_job.state})")

    # Cancelar workers
    for w in workers: w.cancel()

    # Generar Informe Maestro
    report = "# Informe de Ensayo Distribuído v3\n\n| Job ID | Modelo | Estado | Palabras | Duración | Fases OK |\n|---|---|---|---|---|---|\n"
    for j in all_jobs:
        report += f"| {j.id} | {j.model_info['name']} | {j.state} | {j.word_count} | {j.duration:.1f}s | {', '.join(j.phases_ok)} |\n"
    
    REPORT_FILE.write_text(report, encoding="utf-8")
    logger.info(f"📊 Reporte final generado en {REPORT_FILE}")

if __name__ == "__main__":
    asyncio.run(main())
