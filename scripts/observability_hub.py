import time
import subprocess
import os
import sys

def get_gpu_usage():
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used", "--format=csv,noheader,nounits"],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except:
        return "N/A"

def get_last_log_line():
    log_path = os.path.expanduser("~/.hermes/logs/agent.log")
    if os.path.exists(log_path):
        try:
            with open(log_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
                return lines[-1].strip() if lines else "Log vacío"
        except:
            return "Error leyendo log"
    return "Log no encontrado"

def check_progress():
    print(f"\n--- [OBSERVABILIDAD ENSAYO] {time.strftime('%H:%M:%S')} ---")
    gpu = get_gpu_usage()
    log = get_last_log_line()
    
    # Verificar si Ollama tiene el modelo cargado
    try:
        ollama_ps = subprocess.run(["ollama", "ps"], capture_output=True, text=True).stdout
        model_active = "qwen" in ollama_ps or "gemma" in ollama_ps or "mistral" in ollama_ps
    except:
        model_active = False

    print(f"[*] GPU (Util%, VRAM MB): {gpu}")
    print(f"[*] Modelo en Ollama: {'ACTIVO' if model_active else 'INACTIVO/CARGANDO'}")
    print(f"[*] Último Log: {log[:100]}...")
    
    if not model_active and "INFO" in log:
         print("[!] ADVERTENCIA: No hay modelo en Ollama pero el log indica actividad. Posible latencia de red o cambio de fase.")

if __name__ == "__main__":
    print("Iniciando Hub de Observabilidad (Intervalo: 15s)...")
    while True:
        check_progress()
        time.sleep(15)
