\"\"\"
run_night_bench_v4.py — Motor de búsqueda de hiperparámetros (Grid Search).
Optimizado para ejecución nocturna desatendida en RTX.
\"\"\"

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

# ── CONFIGURACIÓN DE RUTAS ───────────────────────────────────────────────────
ROOT_DIR      = Path(__file__).parent.parent
OUTPUT_DIR    = ROOT_DIR / "night_bench_v4"
LOG_DIR       = OUTPUT_DIR / "logs"
RESULTS_DIR   = OUTPUT_DIR / "posts"
TELEMETRY_FILE = LOG_DIR / "param_search_metrics.jsonl"

for d in (OUTPUT_DIR, LOG_DIR, RESULTS_DIR):
    d.mkdir(parents=True, exist_ok=True)

# ── MODELO DE DATOS ────────────────────────────────────────────────────
@dataclass
class ExperimentJob:
    id: str
    model: str
    temp: float
    ctx: int
    state: str = "pending"
    metrics: dict = field(default_factory=dict)
    phases_ok: list = field(default_factory=list)

job_queue = asyncio.Queue()
result_queue = asyncio.Queue()

# ── LOGGING ──────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger("NightEngine")

# ── MOTOR DE VERIFICACIÓN (GROUNDING USA/ACADEMIA) ──────────────────────────
async def verify_facts_global(text: str, agent_instance: Any) -> str:
    \"\"\"
    Usa Hermes para contrastar el texto con fuentes de autoridad (USA/Navy).
    \"\"\"
    sources = \"history.navy.mil, usna.edu, armada.defensa.gob.es\"
    prompt = f\"Actúa como un Fact-Checker de la Academia Naval. Verifica este texto contra {sources}. Detecta contradicciones y añade citas de autoridad.\\n\\nTexto:\\n{text[:2000]}...\"
    res = agent_instance.run_conversation(prompt, system_message=\"Eres un Auditor de la U.S. Naval Academy.\")
    return res.get(\"final_response\", \"Sin verificación externa.\")

# ── WORKER CON PROTECCIÓN RTX ────────────────────────────────────────────────
async def rtx_worker(worker_id: str):
    logger.info(f"👷 Worker {worker_id} activo. Cubierta despejada.")
    while True:
        job: ExperimentJob = await job_queue.get()
        job.state = "running"
        t_start = time.time()
        
        try:
            from run_agent import AIAgent
            from scripts.evaluate_results import evaluate_post
            
            logger.info(f"🚀 Iniciando Exp {job.id}: {job.model} (Temp={job.temp}, Ctx={job.ctx})")
            
            # 1. INVESTIGADOR
            agent_inv = AIAgent(model=job.model, api_key="ollama", request_overrides={"temperature": 0.0}, enabled_toolsets=["smart-rag"], quiet_mode=True)
            res_inv = agent_inv.run_conversation(\"Investiga la Armada Castellana y El Glorioso.\")
            facts = res_inv.get(\"final_response\", \"\")
            
            # 2. REDACTOR (Ajustado a hiperparámetros del Job)
            agent_writer = AIAgent(model=job.model, api_key="ollama", 
                                   request_overrides={"temperature": job.temp, "num_ctx": job.ctx, "num_predict": 4096}, 
                                   enabled_toolsets=["web"], quiet_mode=True)
            res_writer = agent_writer.run_conversation(f"Escribe un post de +2500 palabras sobre la Armada y El Glorioso.")
            draft = res_writer.get("final_response", "")

            # Guardar borrador inmediatamente
            draft_filename = f"draft_{job.model.replace(':','_')}_T{job.temp}.md"
            (RESULTS_DIR / draft_filename).write_text(draft, encoding="utf-8-sig")

            
            # 3. VERIFICADOR GLOBAL (Grounding)
            audit = await verify_facts_global(draft, agent_inv)
            
            # 4. JUEZ
            eval_data = evaluate_post(draft)
            
            # Guardar resultados
            job.metrics = {
                \"duration\": time.time() - t_start,
                \"score\": eval_data.get(\"scores\", {}).get(\"expertise\", 0) if eval_data else 0,
                \"words\": len(draft.split())
            }
            
            filename = f\"post_{job.model.replace(':','_')}_T{job.temp}_C{job.ctx}.md\"
            (RESULTS_DIR / filename).write_text(f\"# AUDITORÍA USA/NAVY\\n{audit}\\n\\n{draft}\", encoding=\"utf-8-sig\")
            
            job.state = \"done\"
            await result_queue.put(job)
            
        except Exception as e:
            logger.error(f"❌ Fallo en Job {job.id}: {e}")
            job.state = \"failed\"
            await result_queue.put(job)
        finally:
            subprocess.run([\"ollama\", \"stop\", job.model], check=False)
            await asyncio.sleep(10) # Pausa para enfriar GPU
            job_queue.task_done()

# ── PLANIFICADOR NOCTURNO ───────────────────────────────────────────────────
async def main():
    MODELS = [\"qwen3.5:9b\", \"qwen2.5:14b\", \"deepseek-v2:16b\"]
    TEMPS = [0.2, 0.7, 1.0]
    CTXS = [16384, 32768]
    
    logger.info(\"📊 Cargando matriz de experimentos...\")
    for m in MODELS:
        for t in TEMPS:
            for c in CTXS:
                await job_queue.put(ExperimentJob(id=f\"exp_{uuid.uuid4().hex[:4]}\", model=m, temp=t, ctx=c))

    # Lanzar Worker (1 solo para estabilidad VRAM absoluta)
    asyncio.create_task(rtx_worker(\"Master-Worker\"))

    # Esperar resultados
    total = len(MODELS) * len(TEMPS) * len(CTXS)
    results = []
    for _ in range(total):
        results.append(await result_queue.get())
        logger.info(f"📉 Progreso: {len(results)}/{total}")

    # Generar Tabla de Hiperparámetros
    table = \"# Reporte Grid Search Nocturno\\n\\n| Modelo | Temp | Ctx | Score | Palabras | Duración |\\n|---|---|---|---|---|---|\\n\"
    for r in results:
        table += f\"| {r.model} | {r.temp} | {r.ctx} | {r.metrics.get('score')} | {r.metrics.get('words')} | {r.metrics.get('duration',0):.1f}s |\\n\"
    
    (OUTPUT_DIR / \"summary.md\").write_text(table)
    logger.info(\"✅ ENSAYO NOCTURNO FINALIZADO. Resultados en night_bench_v4/summary.md\")

if __name__ == \"__main__\":
    asyncio.run(main())
