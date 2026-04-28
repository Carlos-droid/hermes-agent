"""
run_ensemble_v2.py — Ensayo multi-modelo con observabilidad completa (Versión Maestra).
"""

import asyncio
import json
import logging
import os
import subprocess
import sys
import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Any

# ── Configuración de directorios ───────────────────────────────────────────────
ROOT_DIR      = Path(__file__).parent.parent
OUTPUT_DIR    = ROOT_DIR / "output"
LOG_DIR       = ROOT_DIR / "logs"
TELEMETRY_FILE = LOG_DIR / "structured_log.jsonl"
RESULTS_DIR   = OUTPUT_DIR / "posts"
REPORT_FILE   = OUTPUT_DIR / "ensemble_report.md"

for d in (OUTPUT_DIR, LOG_DIR, RESULTS_DIR):
    d.mkdir(parents=True, exist_ok=True)

# ── Logging estructurado ───────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_DIR / "ensemble.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("EnsembleRunner")

# ── Timeouts por fase (segundos) ───────────────────────────────────────────────
PHASE_TIMEOUTS = {
    "investigator": 300,   # 5 min
    "writer":       900,   # 15 min (Para +2500 palabras)
    "corrector":    300,   # 5 min
    "judge":        180,   # 3 min
}

HEARTBEAT_INTERVAL = 15 

# ── Modelos a ensayar ──────────────────────────────────────────────────────────
MODELS_TO_TEST = [
    {"name": "qwen3.5:9b", "provider": "ollama", "base_url": "http://localhost:11434/v1"},
    {"name": "qwen2.5:14b", "provider": "ollama", "base_url": "http://localhost:11434/v1"},
    {"name": "deepseek-v2:16b", "provider": "ollama", "base_url": "http://localhost:11434/v1"},
    {"name": "mistral-nemo:latest", "provider": "ollama", "base_url": "http://localhost:11434/v1"},
    {"name": "gemma4:latest", "provider": "ollama", "base_url": "http://localhost:11434/v1"},
]

# ── Parámetros de los roles ────────────────────────────────────────────────────
ROLE_CONFIG = {
    "investigator": {
        "params": {"temperature": 0.0, "top_p": 0.1},
        "system": "Eres un Investigador Naval experto. Tu única tarea es extraer datos precisos y técnicos usando Smart-RAG.",
        "toolsets": ["smart-rag"],
        "prompt": "Utiliza 'smart_rag_query' para investigar la armada castellana (1248) y El Glorioso (1747). Resumen técnico de hechos.",
    },
    "writer": {
        "params": {"temperature": 0.85, "top_p": 0.9, "num_ctx": 32768},
        "system": "Eres un Redactor Editorial de élite. Crea prosa épica y técnica basada en hechos reales.",
        "toolsets": ["web"],
        "prompt_template": "Basado en estos hechos:\n{facts}\n\nRedacta el post completo de +2500 palabras, autoritario y técnico.",
    },
    "corrector": {
        "params": {"temperature": 0.1, "top_p": 0.1},
        "system": "Eres un Académico de la RAE. Corrige el estilo, la gramática y el léxico técnico.",
        "toolsets": ["rae", "file"],
        "prompt_template": "Utiliza 'rae_check' y el manual en {rae_path} para corregir este texto:\n\n{draft}",
    },
}

# RUTA REAL DETECTADA EN EL SISTEMA
RAE_DB_PATH = "C:/Users/carlo/Documents/Proyectos_Phyton/smart-RAG/Smart-RAG-v7-main/smart_rag/data/processed/rae/manual_de_estilo_2018.md"

def log_event(trace_id, model, phase, action, **metrics):
    event = {
        "trace_id": trace_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "model": model,
        "phase": phase,
        "action": action,
        **metrics,
    }
    with open(TELEMETRY_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")
    logger.info(f"[{trace_id[:8]}] {model} | {phase} | {action} | {metrics}")

class HeartbeatMonitor:
    def __init__(self, trace_id, model, phase, timeout):
        self.trace_id = trace_id
        self.model = model
        self.phase = phase
        self.timeout = timeout
        self._stop_evt = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._start_ts = None

    def start(self):
        self._start_ts = time.time()
        self._thread.start()
        return self

    def stop(self):
        self._stop_evt.set()
        self._thread.join(timeout=2)
        return round(time.time() - self._start_ts, 2) if self._start_ts else 0.0

    def _run(self):
        while not self._stop_evt.wait(timeout=HEARTBEAT_INTERVAL):
            elapsed = round(time.time() - self._start_ts, 0)
            log_event(self.trace_id, self.model, self.phase, "HEARTBEAT", elapsed_s=elapsed, status="alive")

@dataclass
class ModelResult:
    model: str
    trace_id: str
    status: str = "pending"
    word_count: int = 0
    duration: float = 0.0
    phases_ok: list = field(default_factory=list)

async def run_phase(phase_name, model_info, prompt, system_message, params, toolsets, trace_id):
    model = model_info["name"]
    timeout = PHASE_TIMEOUTS.get(phase_name, 300)
    log_event(trace_id, model, phase_name, "START")
    
    hb = HeartbeatMonitor(trace_id, model, phase_name, timeout).start()
    t_start = time.time()
    
    try:
        from run_agent import AIAgent
        agent = AIAgent(model=model, base_url=model_info["base_url"], api_key="ollama", provider=model_info["provider"], 
                        request_overrides=params, enabled_toolsets=toolsets, quiet_mode=True)
        
        loop = asyncio.get_event_loop()
        response = await asyncio.wait_for(
            loop.run_in_executor(None, lambda: agent.run_conversation(prompt, system_message=system_message)),
            timeout=timeout
        )
        result = response.get("final_response", "")
        log_event(trace_id, model, phase_name, "END", duration=time.time()-t_start)
        return result
    except Exception as e:
        log_event(trace_id, model, phase_name, "ERROR", msg=str(e))
        return None
    finally:
        hb.stop()

async def run_full_cycle(model_info):
    model = model_info["name"]
    trace_id = f"ens_{uuid.uuid4().hex[:6]}"
    res = ModelResult(model=model, trace_id=trace_id)
    
    # 1. Investigador
    facts = await run_phase("investigator", model_info, ROLE_CONFIG["investigator"]["prompt"], 
                            ROLE_CONFIG["investigator"]["system"], ROLE_CONFIG["investigator"]["params"], 
                            ["smart-rag"], trace_id)
    if facts: res.phases_ok.append("investigator")
    else: facts = "Hechos básicos de fallback."

    # 2. Redactor
    draft = await run_phase("writer", model_info, ROLE_CONFIG["writer"]["prompt_template"].format(facts=facts), 
                            ROLE_CONFIG["writer"]["system"], ROLE_CONFIG["writer"]["params"], 
                            ["web"], trace_id)
    if draft: res.phases_ok.append("writer")
    else: return res

    # 3. Corrector
    final = await run_phase("corrector", model_info, ROLE_CONFIG["corrector"]["prompt_template"].format(rae_path=RAE_DB_PATH, draft=draft), 
                            ROLE_CONFIG["corrector"]["system"], ROLE_CONFIG["corrector"]["params"], 
                            ["rae", "file"], trace_id)
    if final: res.phases_ok.append("corrector")
    else: final = draft

    # Guardar post
    out_path = RESULTS_DIR / f"post_{model.replace(':','_')}.md"
    out_path.write_text(final, encoding="utf-8")
    res.word_count = len(final.split())
    res.status = "success"
    return res

async def main():
    logger.info("🚀 Iniciando Ensayo v2")
    results = []
    for m in MODELS_TO_TEST:
        r = await run_full_cycle(m)
        results.append(r)
        subprocess.run(["ollama", "stop", m["name"]], check=False)
        await asyncio.sleep(5)
    
    # Generar tabla final
    report = "# Resumen de Ensayo\n\n| Modelo | Estado | Palabras | Fases OK |\n|---|---|---|---|\n"
    for r in results:
        report += f"| {r.model} | {r.status} | {r.word_count} | {', '.join(r.phases_ok)} |\n"
    REPORT_FILE.write_text(report)
    logger.info(f"✅ Ensayo terminado. Reporte en {REPORT_FILE}")

if __name__ == "__main__":
    asyncio.run(main())
