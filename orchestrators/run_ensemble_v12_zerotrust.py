"""
run_ensemble_v12_zerotrust.py
Observabilidad total + Confianza Cero en escritura y validación.
Garantiza que ningún éxito falso se cuele; fuerza volcado físico al disco.
"""

import asyncio
import json
import logging
import os
import signal
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
from dotenv import load_dotenv

# Cargar variables de entorno al inicio
load_dotenv()

# ══════════════════════════════════════════════════════════════════════════════
# CONFIGURACIÓN GENERAL
# ══════════════════════════════════════════════════════════════════════════════
ROOT       = Path(__file__).parent
OUT        = ROOT / "v12_output"
LOGS       = OUT / "logs"
POSTS      = OUT / "posts"
STATUS_FILE     = OUT / "status.json"          # estado vivo
CHECKPOINT_FILE = OUT / "checkpoint.json"
TELEMETRY_FILE  = LOGS / "telemetry.jsonl"

for d in (OUT, LOGS, POSTS):
    d.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOGS / "v12.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("v12")

EXECUTOR = ThreadPoolExecutor(max_workers=1)

# Timeouts por fase (personalizables por variable de entorno)
PHASE_TIMEOUTS = {
    "investigator": int(os.environ.get("T_INVESTIGATOR", "600")),
    "writer":       int(os.environ.get("T_WRITER",       "1800")),
    "corrector":    int(os.environ.get("T_CORRECTOR",    "600")),
}
WATCHDOG_TIMEOUT      = int(os.environ.get("WATCHDOG_TIMEOUT", "300"))
HEARTBEAT_INTERVAL    = 15
MAX_RETRIES           = 3
MAX_OUTPUT_CHARS      = 100_000

JUDGE_MODEL = "google/gemini-2.0-flash-lite-001"
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
if not OPENROUTER_API_KEY:
    logger.warning("OPENROUTER_API_KEY no definida; juez externo no disponible.")
    JUDGE_MODEL = None

SESSION_ID = f"session_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}_{uuid.uuid4().hex[:6]}"

# Señal de apagado segura
SHUTDOWN_REQUESTED = False

# ══════════════════════════════════════════════════════════════════════════════
# TELEMETRÍA ESTRUCTURADA
# ══════════════════════════════════════════════════════════════════════════════
def log_event(trace_id: str, model: str, phase: str, action: str,
              aux_models: list = None, tools_config: dict = None, **kw) -> None:
    event = {
        "ts":           datetime.now(timezone.utc).isoformat(),
        "session_id":   SESSION_ID,
        "trace_id":     trace_id,
        "model":        model,
        "aux_models":   aux_models or [],
        "tools":        tools_config or {},
        "phase":        phase,
        "action":       action,
        **kw,
    }
    with open(TELEMETRY_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")
    lvl = logging.ERROR if action in ("ERROR", "TIMEOUT", "FAILED", "DEAD") else logging.INFO
    logger.log(lvl, f"[{trace_id[:8]}] {model}/{phase}/{action} {kw}")

# ══════════════════════════════════════════════════════════════════════════════
# ESTADO VIVO (status.json)
# ══════════════════════════════════════════════════════════════════════════════
def update_live_status(job_id=None, model=None, phase=None, aux=None, status="running"):
    """Actualiza el archivo de estado vivo de forma atómica."""
    data = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "session_id": SESSION_ID,
        "job_id": job_id,
        "model": model,
        "phase": phase,
        "auxiliaries": aux or [],
        "status": status,
    }
    tmp_path = STATUS_FILE.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp_path, STATUS_FILE)

# ══════════════════════════════════════════════════════════════════════════════
# MONITOR DE GPU (Ollama)
# ══════════════════════════════════════════════════════════════════════════════
async def gpu_memory_usage():
    try:
        proc = await asyncio.create_subprocess_exec(
            "nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
        return int(stdout.decode().strip())
    except Exception:
        return -1

# ══════════════════════════════════════════════════════════════════════════════
# HEARTBEAT ASÍNCRONO
# ══════════════════════════════════════════════════════════════════════════════
async def async_heartbeat(trace_id: str, model: str, phase: str, timeout: int,
                          stop_event: asyncio.Event, aux_models: list):
    t0 = time.time()
    tick = 0
    while not stop_event.is_set():
        await asyncio.sleep(HEARTBEAT_INTERVAL)
        if stop_event.is_set():
            break
        tick += 1
        elapsed = round(time.time() - t0)
        remaining = max(0, timeout - elapsed)
        vram = await gpu_memory_usage()
        log_event(trace_id, model, phase, "HEARTBEAT",
                  tick=tick, elapsed_s=elapsed, remaining_s=remaining,
                  gpu_memory_mb=vram, aux_models=aux_models)
        update_live_status(model=model, phase=phase, aux=aux_models)

# ══════════════════════════════════════════════════════════════════════════════
# WATCHDOG (con kill real implementado en run_phase)
# ══════════════════════════════════════════════════════════════════════════════
class Watchdog:
    def __init__(self, timeout: int):
        self.timeout   = timeout
        self._last     = time.time()
        self.triggered = asyncio.Event()

    def tick(self):
        self._last = time.time()

    async def monitor(self):
        while True:
            await asyncio.sleep(min(30, self.timeout))
            if time.time() - self._last > self.timeout:
                logger.error(f"Watchdog: inactividad > {self.timeout}s")
                self.triggered.set()
                return

# ══════════════════════════════════════════════════════════════════════════════
# JOB Y GESTIÓN DE ERRORES
# ══════════════════════════════════════════════════════════════════════════════
@dataclass
class Job:
    id:            str
    model:         str
    trace_id:      str = field(default_factory=lambda: f"v12_{uuid.uuid4().hex[:8]}")
    state:         str = "pending"
    retries:       int = 0
    error:         Optional[str] = None
    word_count:    int = 0
    phases:        List[str] = field(default_factory=list)
    timings:       Dict[str, float] = field(default_factory=dict)
    auxiliaries:   Dict[str, List[str]] = field(default_factory=dict)
    tools_details: Dict[str, dict] = field(default_factory=dict)
    config:        Dict = field(default_factory=lambda: {
        "temperature": 0.7,
        "max_tokens": 4096,
    })

def classify_error(e: Exception) -> str:
    if isinstance(e, asyncio.TimeoutError):
        return "timeout"
    if isinstance(e, asyncio.CancelledError):
        return "cancelled"
    if isinstance(e, ValueError) and "truncad" in str(e).lower():
        return "truncation"
    if isinstance(e, ValueError) and ("vacía" in str(e).lower() or "empty" in str(e).lower()):
        return "empty"
    if isinstance(e, MemoryError):
        return "memory"
    msg = str(e).lower()
    if "timeout" in msg:       return "timeout"
    if "truncat" in msg:       return "truncation"
    if "connection" in msg or "readtimeout" in msg: return "network"
    return "unknown"

def mutate_job(job: Job, error_type: str) -> None:
    cfg = job.config
    before = dict(cfg)
    if error_type == "timeout":
        cfg["temperature"]  = 0.5
        cfg["max_tokens"]   = 2048
    elif error_type == "truncation":
        cfg["max_tokens"]   = 4096
        cfg["temperature"]  = 0.6
    elif error_type == "empty":
        cfg["temperature"]  = 0.8
    elif error_type == "memory":
        cfg["max_tokens"]   = 1024
    elif error_type == "cancelled":
        cfg["temperature"]  = 0.5
        cfg["max_tokens"]   = 2048
    else:
        cfg["temperature"]  = 0.6
    log_event(job.trace_id, job.model, "config", "MUTATION",
              error_type=error_type, before=before, after=dict(cfg))

async def backoff(retries: int) -> None:
    delay = min(60, 2 ** retries)
    logger.info(f"Backoff {delay}s (intento {retries})")
    await asyncio.sleep(delay)

# ══════════════════════════════════════════════════════════════════════════════
# ESCRITURA ATÓMICA CON FORZADO FÍSICO (Zero-Trust)
# ══════════════════════════════════════════════════════════════════════════════
def save_section(path: Path, section_tag: str, content: str) -> None:
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    start_marker = f"\n\n# {section_tag}\n"
    if start_marker in existing:
        idx = existing.index(start_marker)
        next_section = existing.find("\n\n# ", idx + len(start_marker))
        if next_section != -1:
            existing = existing[:idx] + existing[next_section:]
        else:
            existing = existing[:idx]
    new_content = existing + start_marker + content
    tmp_path = path.with_suffix(".tmp")
    
    # Escritura con volcado físico garantizado (fsync)
    with open(tmp_path, "w", encoding="utf-8-sig") as f:
        f.write(new_content)
        f.flush()
        os.fsync(f.fileno())      # <-- Obliga al SO a escribir físicamente
    os.replace(tmp_path, path)

def is_truncated(text: str) -> bool:
    if not text:
        return True
    last_char = text.rstrip()[-1] if text.rstrip() else ""
    return last_char not in ".!?»)}]\"'"

# ══════════════════════════════════════════════════════════════════════════════
# JUEZ EXTERNO (auxiliar)
# ══════════════════════════════════════════════════════════════════════════════
async def evaluate_with_judge(content: str, job: Job) -> Optional[dict]:
    if not JUDGE_MODEL or not OPENROUTER_API_KEY:
        return None
    try:
        from openai import OpenAI
        client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=OPENROUTER_API_KEY)
        loop = asyncio.get_running_loop()
        completion = await loop.run_in_executor(
            EXECUTOR,
            lambda: client.chat.completions.create(
                model=JUDGE_MODEL,
                messages=[
                    {"role": "system", "content": "Editor naval. Evalúa calidad E-E-A-T. Devuelve JSON: {'score': float, 'justification': str}"},
                    {"role": "user", "content": f"Evalúa este post (máx 10000 chars):\n\n{content[:10000]}"}
                ],
                response_format={"type": "json_object"},
                temperature=0.2,
                max_tokens=500,
            )
        )
        result = json.loads(completion.choices[0].message.content)
        log_event(job.trace_id, job.model, "judge", "EXTERNAL_AUDIT",
                  aux_models=[JUDGE_MODEL], score=result.get("score"),
                  justification=result.get("justification", "")[:200])
        return result
    except Exception as e:
        logger.warning(f"Fallo en juez externo: {e}")
        return None

# ══════════════════════════════════════════════════════════════════════════════
# EJECUCIÓN DE FASE (con kill real al watchdog)
# ══════════════════════════════════════════════════════════════════════════════
async def run_phase(
    agent,
    prompt: str,
    system: str,
    timeout: int,
    wd: Watchdog,
    trace_id: str,
    model: str,
    phase: str,
    toolsets_used: List[str],
    tools_metadata: dict,
) -> str:
    log_event(trace_id, model, phase, "START",
              timeout_s=timeout, prompt_chars=len(prompt),
              aux_models=toolsets_used, tools_config=tools_metadata)
    update_live_status(model=model, phase=phase, aux=toolsets_used)

    hb_stop = asyncio.Event()
    hb_task = asyncio.create_task(async_heartbeat(trace_id, model, phase, timeout,
                                                  hb_stop, toolsets_used))
    t0 = time.time()
    loop = asyncio.get_running_loop()

    try:
        exec_task = loop.run_in_executor(
            EXECUTOR,
            lambda: agent.run_conversation(
                prompt + "\n\nNO muestres razonamiento. Responde directo.",
                system_message=system,
            )
        )
        wd_task = asyncio.create_task(wd.monitor())

        done, pending = await asyncio.wait(
            [exec_task, wd_task],
            timeout=timeout,
            return_when=asyncio.FIRST_COMPLETED
        )

        if wd_task in done:
            # Watchdog disparado: KILL REAL del modelo
            log_event(trace_id, model, phase, "WATCHDOG_TRIGGERED",
                      aux_models=toolsets_used, tools_config=tools_metadata)
            logger.error(f"Forzando parada de {model} (watchdog)...")
            try:
                subprocess.run(["ollama", "stop", model],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               timeout=15)
            except Exception:
                pass
            exec_task.cancel()
            wd_task.cancel()
            try:
                await exec_task
            except (asyncio.CancelledError, Exception):
                pass
            raise asyncio.TimeoutError(f"Watchdog: inactividad > {WATCHDOG_TIMEOUT}s, modelo detenido")

        if not done:
            exec_task.cancel()
            wd_task.cancel()
            try:
                await exec_task
            except (asyncio.CancelledError, Exception):
                pass
            raise asyncio.TimeoutError(f"Timeout de fase {phase} ({timeout}s)")

        wd_task.cancel()
        try:
            await wd_task
        except (asyncio.CancelledError, Exception):
            pass

        result = await exec_task
        wd.tick()
        # Corregido: Manejo robusto de NoneType en la respuesta
        raw_text = result.get("final_response") if isinstance(result, dict) else str(result)
        text = raw_text if raw_text is not None else ""

        if not text or len(text) < 100:
            raise ValueError(f"Salida vacía o muy corta ({len(text)} chars)")
        if len(text) > MAX_OUTPUT_CHARS:
            raise ValueError(f"Salida excesiva ({len(text)} chars), posible bucle")

        elapsed = round(time.time() - t0, 2)
        log_event(trace_id, model, phase, "END",
                  elapsed_s=elapsed, chars=len(text), words=len(text.split()),
                  aux_models=toolsets_used, tools_config=tools_metadata)
        return text

    except asyncio.TimeoutError:
        elapsed = round(time.time() - t0, 2)
        log_event(trace_id, model, phase, "TIMEOUT",
                  elapsed_s=elapsed, timeout_s=timeout,
                  aux_models=toolsets_used, tools_config=tools_metadata)
        raise
    except Exception as e:
        elapsed = round(time.time() - t0, 2)
        log_event(trace_id, model, phase, "ERROR",
                  elapsed_s=elapsed,
                  error_type=type(e).__name__,
                  error=str(e),
                  tb=traceback.format_exc()[-500:],
                  aux_models=toolsets_used, tools_config=tools_metadata)
        raise
    finally:
        hb_stop.set()
        hb_task.cancel()
        try:
            await hb_task
        except (asyncio.CancelledError, Exception):
            pass
        update_live_status(model=model, phase=None, aux=[], status="idle")

# ══════════════════════════════════════════════════════════════════════════════
# CICLO DE JOB CON TRAZABILIDAD TOTAL Y VALIDACIÓN ZERO‑TRUST
# ══════════════════════════════════════════════════════════════════════════════
async def run_job(job: Job) -> None:
    from run_agent import AIAgent
    import os
    
    # Forzar a que todos los procesos (agente y auxiliares) usen el modelo local
    os.environ["HERMES_FORCE_MODEL"] = job.model
    os.environ["OPENAI_BASE_URL"] = "http://localhost:11434/v1"
    os.environ["OPENAI_API_KEY"] = "ollama"  # Placeholder para el SDK

    out_file = POSTS / f"{job.model.replace(':', '_')}.md"

    while job.retries <= MAX_RETRIES:
        if SHUTDOWN_REQUESTED:
            logger.info(f"Apagado solicitado. No se reintentará {job.model}.")
            job.state = "cancelled"
            return

        if job.retries > 0:
            log_event(job.trace_id, job.model, "retry", "ATTEMPT",
                      attempt=job.retries, config=job.config)

        wd = Watchdog(timeout=WATCHDOG_TIMEOUT)
        t_cycle = time.time()
        phases_this_attempt = []
        aux_this_job = {}
        tools_details_this_job = {}

        try:
            # ── INVESTIGADOR ──────────────────────────────
            toolsets_inv = ["smart-rag"]
            tools_inv_meta = {"tool": "smart-rag", "model": job.model,
                              "description": "RAG sobre base de conocimiento naval"}
            agent_inv = AIAgent(
                model=job.model,
                api_key="ollama",
                base_url="http://localhost:11434/v1",
                request_overrides={"temperature": 0.0},
                enabled_toolsets=toolsets_inv,
                quiet_mode=True
            )
            facts = await run_phase(
                agent_inv,
                "Investiga Armada Castellana (1248) y El Glorioso (1747). "
                "Incluye fechas, nombres de barcos, comandantes y artillería.",
                "Investigador Naval experto. Solo datos técnicos verificados.",
                PHASE_TIMEOUTS["investigator"],
                wd,
                job.trace_id, job.model, "investigator",
                toolsets_used=toolsets_inv,
                tools_metadata=tools_inv_meta,
            )
            
            # Protocolo AgentFixer: Validación de calidad de investigación
            if len(facts) < 300:
                logger.warning(f"[{job.trace_id[:8]}] AgentFixer: Investigación insuficiente ({len(facts)} chars). Reintentando con refuerzo...")
                facts = await run_phase(
                    agent_inv,
                    f"La investigación previa fue insuficiente. Necesito MÁS DETALLES técnicos sobre barcos y tácticas:\n\n{facts}",
                    "Investigador Naval de Élite. Proporciona datos exhaustivos.",
                    PHASE_TIMEOUTS["investigator"],
                    wd,
                    job.trace_id, job.model, "investigator_retry",
                    toolsets_used=toolsets_inv,
                    tools_metadata=tools_inv_meta,
                )

            save_section(out_file, "FACTS", facts)
            phases_this_attempt.append("investigator")
            aux_this_job["investigator"] = toolsets_inv
            tools_details_this_job["investigator"] = tools_inv_meta

            # ── REDACTOR ─────────────────────────────────
            toolsets_writer = ["web"]
            tools_writer_meta = {"tool": "web", "model": job.model,
                                 "description": "Búsqueda web para enriquecer contenido"}
            agent_writer = AIAgent(
                model=job.model,
                api_key="ollama",
                base_url="http://localhost:11434/v1",
                request_overrides=job.config,
                enabled_toolsets=toolsets_writer,
                quiet_mode=True
            )
            draft = await run_phase(
                agent_writer,
                f"Escribe un post épico de +2500 palabras sobre historia naval española.\n"
                f"Basa el texto en estos hechos verificados:\n{facts}",
                "Redactor Editorial de élite. Prosa épica y técnica.",
                PHASE_TIMEOUTS["writer"],
                wd,
                job.trace_id, job.model, "writer",
                toolsets_used=toolsets_writer,
                tools_metadata=tools_writer_meta,
            )
            if is_truncated(draft):
                raise ValueError(f"Texto truncado: termina en '{draft.rstrip()[-20:]}' sin puntuación")
            save_section(out_file, "DRAFT", draft)
            phases_this_attempt.append("writer")
            aux_this_job["writer"] = toolsets_writer
            tools_details_this_job["writer"] = tools_writer_meta

            # ── CORRECTOR ────────────────────────────────
            toolsets_corr = ["rae", "file"]
            tools_corr_meta = {"tool": "rae, file", "model": job.model,
                               "description": "Corrección gramatical y estilo con RAE"}
            agent_corr = AIAgent(
                model=job.model,
                api_key="ollama",
                base_url="http://localhost:11434/v1",
                request_overrides={"temperature": 0.1},
                enabled_toolsets=toolsets_corr,
                quiet_mode=True
            )
            final = await run_phase(
                agent_corr,
                f"Corrige gramática y estilo. Mantén todos los datos históricos intactos.\n\n{draft}",
                "Corrector académico de estilo. Sin alterar hechos.",
                PHASE_TIMEOUTS["corrector"],
                wd,
                job.trace_id, job.model, "corrector",
                toolsets_used=toolsets_corr,
                tools_metadata=tools_corr_meta,
            )
            save_section(out_file, "FINAL", final)
            phases_this_attempt.append("corrector")
            aux_this_job["corrector"] = toolsets_corr
            tools_details_this_job["corrector"] = tools_corr_meta

            # ── JUEZ EXTERNO ─────────────────────────────
            judge_score = await evaluate_with_judge(final, job)
            if judge_score:
                with open(out_file, "a", encoding="utf-8-sig") as f:
                    f.write(f"\n\n# JUEZ EXTERNO ({JUDGE_MODEL})\nPuntuación: {judge_score.get('score')}\n"
                            f"Justificación: {judge_score.get('justification', '')}")
                aux_this_job["judge"] = [JUDGE_MODEL]
                tools_details_this_job["judge"] = {"tool": JUDGE_MODEL, "role": "external auditor"}

            # ── VALIDACIÓN FÍSICA Y LÓGICA (Zero-Trust) ───
            if not out_file.exists():
                raise FileNotFoundError(f"[Falso Éxito] El archivo físico {out_file.name} nunca se creó en disco.")

            try:
                # Leemos el archivo desde el disco para verificar integridad
                with open(out_file, "r", encoding="utf-8-sig") as f:
                    contenido_fisico = f.read()
            except Exception as e:
                raise IOError(f"[Falso Éxito] Archivo generado pero ilegible/corrupto: {e}")

            peso_bytes = out_file.stat().st_size
            if peso_bytes < 2000 or len(contenido_fisico.strip()) < 100:
                raise ValueError(f"[Falso Éxito] Archivo {out_file.name} demasiado ligero ({peso_bytes} bytes). "
                                 f"El proceso reportó DONE pero no guardó los datos.")

            # Verificar que todas las fases están presentes
            fases_esperadas = ["# FACTS", "# DRAFT", "# FINAL"]
            fases_faltantes = [f for f in fases_esperadas if f not in contenido_fisico]
            if fases_faltantes:
                raise ValueError(f"[Falso Éxito] El archivo no contiene las fases: {fases_faltantes}. Escritura truncada.")

            # Si pasa todas las pruebas, es un éxito real
            job.word_count = len(final.split())
            job.state      = "done"
            job.phases     = phases_this_attempt
            job.auxiliaries = aux_this_job
            job.tools_details = tools_details_this_job
            job.timings["total"] = round(time.time() - t_cycle, 2)

            log_event(job.trace_id, job.model, "cycle", "SUCCESS",
                      phases=job.phases, word_count=job.word_count,
                      total_s=job.timings["total"], retries=job.retries,
                      aux_models=list(set(sum(aux_this_job.values(), []))))
            break

        except Exception as e:
            elapsed   = round(time.time() - t_cycle, 2)
            job.error = str(e)
            error_type = classify_error(e)

            log_event(job.trace_id, job.model, "cycle", "FAIL",
                      attempt=job.retries, elapsed_s=elapsed,
                      error_type=error_type, error=job.error,
                      phases_completed=phases_this_attempt,
                      aux_models=list(set(sum(aux_this_job.values(), []))) if aux_this_job else [])

            job.retries += 1
            if job.retries > MAX_RETRIES or SHUTDOWN_REQUESTED:
                job.state = "failed"
                log_event(job.trace_id, job.model, "cycle", "DEAD",
                          total_retries=job.retries - 1, last_error=job.error)
                break

            mutate_job(job, error_type)
            await backoff(job.retries)

        finally:
            # Detener modelo primario
            try:
                proc = await asyncio.create_subprocess_exec(
                    "ollama", "stop", job.model,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await asyncio.wait_for(proc.wait(), timeout=15)
            except Exception:
                pass
            await asyncio.sleep(5)

    # Guardar checkpoint atómico
    save_checkpoint(job)
    update_live_status(job_id=job.id, model=job.model, phase=None, aux=[], status=job.state)

# ══════════════════════════════════════════════════════════════════════════════
# CHECKPOINT ATÓMICO
# ══════════════════════════════════════════════════════════════════════════════
def save_checkpoint(job: Job):
    checkpoint = {}
    if CHECKPOINT_FILE.exists():
        try:
            checkpoint = json.loads(CHECKPOINT_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            checkpoint = {"jobs": {}}
    checkpoint.setdefault("session_id", SESSION_ID)
    checkpoint.setdefault("jobs", {})
    checkpoint["jobs"][job.id] = {
        "model": job.model,
        "state": job.state,
        "phases": job.phases,
        "word_count": job.word_count,
        "timings": job.timings,
        "retries": job.retries,
        "error": job.error,
        "auxiliaries": job.auxiliaries,
        "tools_details": job.tools_details,
        "trace_id": job.trace_id,
    }
    tmp_path = CHECKPOINT_FILE.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(checkpoint, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp_path, CHECKPOINT_FILE)

# ══════════════════════════════════════════════════════════════════════════════
# REVISIÓN DE LOGS MEJORADA
# ══════════════════════════════════════════════════════════════════════════════
async def review_logs():
    if not TELEMETRY_FILE.exists():
        logger.info("No hay telemetría para revisar.")
        return
    lines = TELEMETRY_FILE.read_text(encoding="utf-8").splitlines()
    events = []
    for line in lines:
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    errors = [e for e in events if e.get("action") in ("ERROR", "FAIL", "FAILED", "DEAD", "TIMEOUT")]
    successes = [e for e in events if e.get("action") == "SUCCESS"]
    heartbeats = [e for e in events if e.get("action") == "HEARTBEAT"]
    wd_triggers = [e for e in events if e.get("action") == "WATCHDOG_TRIGGERED"]

    logger.info("\n" + "="*60)
    logger.info("REVISIÓN DE LOGS (TRAZABILIDAD COMPLETA)")
    logger.info(f"Sesión: {SESSION_ID}")
    logger.info(f"Total eventos: {len(events)}")
    logger.info(f"Errores: {len(errors)} | Éxitos: {len(successes)} | Heartbeats: {len(heartbeats)} | Watchdog triggers: {len(wd_triggers)}")
    if errors:
        logger.info("\nÚltimos 5 errores:")
        for e in errors[-5:]:
            logger.info(f"  {e.get('ts')} | {e.get('model')} | {e.get('phase')} | {e.get('error_type','')} | {e.get('error','')[:100]}")
    logger.info("="*60 + "\n")

# ══════════════════════════════════════════════════════════════════════════════
# MANEJO DE SEÑALES (parada segura)
# ══════════════════════════════════════════════════════════════════════════════
def handle_shutdown(signum, frame):
    global SHUTDOWN_REQUESTED
    logger.info(f"Recibida señal {signal.Signals(signum).name}. Iniciando apagado ordenado...")
    SHUTDOWN_REQUESTED = True

signal.signal(signal.SIGINT, handle_shutdown)
signal.signal(signal.SIGTERM, handle_shutdown)

async def run_final_evaluation(jobs):
    """Evalúa los resultados locales usando un modelo potente y económico de OpenRouter."""
    logger.info("Iniciando fase de evaluación final con OpenRouter...")
    
    # Filtrar solo los trabajos que terminaron con éxito
    successful_jobs = [j for j in jobs if j.state == "done"]
    if not successful_jobs:
        logger.warning("No hay trabajos locales exitosos para evaluar.")
        return

    # Usar el primer trabajo exitoso como base para la evaluación (puedes ampliar esto)
    best_job = successful_jobs[0]
    
    # Configuración para OpenRouter (selector automático del más barato)
    # OpenRouter permite usar 'openrouter/auto' para elegir el mejor/más barato
    eval_model = "openrouter/auto"
    
    payload = {
        "model": eval_model,
        "messages": [
            {"role": "system", "content": "Eres un editor experto en historia naval. Evalua el siguiente articulo y sugiere mejoras."},
            {"role": "user", "content": f"Articulo generado por {best_job.model}:\n\n{best_job.final_result}"}
        ]
    }
    
    headers = {
        "Authorization": f"Bearer {os.getenv('OPENROUTER_API_KEY')}",
        "Content-Type": "application/json"
    }

    try:
        # Nota: Aquí asumo que tienes requests o similar disponible
        import requests
        logger.info(f"Enviando crítica a {eval_model}...")
        resp = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload)
        if resp.status_code == 200:
            critique = resp.json()['choices'][0]['message']['content']
            logger.info("Critica final recibida con exito.")
            # Guardar la crítica en un archivo
            (OUT / "critica_final.md").write_text(critique, encoding="utf-8")
        else:
            logger.error(f"Error en OpenRouter: {resp.text}")
    except Exception as e:
        logger.error(f"Fallo la evaluacion final: {e}")

# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════
async def main():
    # Registrar PID para monitorización externa
    main_pid = os.getpid()
    logger.info(f"Iniciando Hermes V12 - PID Principal: {main_pid}")
    with open(OUT / "current_pid.txt", "w") as f:
        f.write(str(main_pid))

    log_event("SYSTEM", "none", "ensemble", "SYSTEM_START",
              session_id=SESSION_ID, total_models=3, main_pid=main_pid)

    models = [
        "qwen2.5:7b",
        "llama3.1:8b",
        "mistral:7b",
        "gemma2:9b",
        "phi3.5:latest"
    ]
    jobs = [Job(id=uuid.uuid4().hex[:4], model=m) for m in models]

    initial_checkpoint = {
        "session_id": SESSION_ID,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "models": models,
        "jobs": {},
    }
    tmp_path = CHECKPOINT_FILE.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(initial_checkpoint, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp_path, CHECKPOINT_FILE)

    for i, job in enumerate(jobs, 1):
        if SHUTDOWN_REQUESTED:
            logger.info("Apagado solicitado antes de comenzar el siguiente job.")
            break
        logger.info(f"\n[{i}/{len(jobs)}] Iniciando: {job.model} (trace={job.trace_id})")
        log_event(job.trace_id, job.model, "ensemble", "JOB_START",
                  job_id=job.id, position=i, total=len(jobs))
        update_live_status(job_id=job.id, model=job.model, phase="starting", aux=[], status="running")
        
        try:
            await run_job(job)
        finally:
            # Forzar descarga de VRAM en Ollama enviando keep_alive: 0
            logger.info(f"Descargando {job.model} de la VRAM...")
            try:
                import requests
                requests.post("http://localhost:11434/api/generate", 
                             json={"model": job.model, "keep_alive": 0})
            except:
                pass
        
        await asyncio.sleep(5)

    # --- FASE DE EVALUACIÓN FINAL ---
    await run_final_evaluation(jobs)

    log_event("SYSTEM", "none", "ensemble", "SYSTEM_END")
    update_live_status(status="finished")
    await review_logs()

    # Informe final
    lines = [
        f"# Informe Ensayo V12 – Sesión {SESSION_ID}",
        f"Generado: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        "| Modelo (primario) | Estado | Palabras | Fases | Retries | Herramientas usadas | Sub-modelos | trace_id |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for j in jobs:
        icon = {"done": "✓", "failed": "✗", "pending": "?", "cancelled": "⏹️"}.get(j.state, "?")
        aux_str = ", ".join(sorted(set(sum(j.auxiliaries.values(), [])))) if j.auxiliaries else "—"
        tools_desc = "; ".join(f"{k}: {v.get('tool','')}" for k,v in j.tools_details.items()) if j.tools_details else "—"
        lines.append(
            f"| `{j.model}` | {icon} {j.state} | {j.word_count} "
            f"| {','.join(j.phases) or '—'} | {j.retries} | {aux_str} | {tools_desc} | `{j.trace_id}` |"
        )
    lines += [
        "",
        "## Diagnóstico rápido",
        "```bash",
        "cat v12_output/status.json",
        "grep '\"action\": \"ERROR\"' v12_output/logs/telemetry.jsonl",
        "grep 'WATCHDOG_TRIGGERED' v12_output/logs/telemetry.jsonl",
        "```",
        f"**Checkpoint:** {CHECKPOINT_FILE} – ahora a prueba de corrupción.",
    ]
    report = "\n".join(lines)
    (OUT / "report.md").write_text(report, encoding="utf-8")
    logger.info(f"\nInforme: {OUT / 'report.md'}")
    print("\n" + report)

if __name__ == "__main__":
    asyncio.run(main())
