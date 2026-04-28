import time
import subprocess
import os
from pathlib import Path

RESULTS_DIR = Path("night_bench_v5/posts")

def get_gpu_usage():
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used", "--format=csv,noheader,nounits"],
            capture_output=True, text=True
        )
        return result.stdout.strip() if result.returncode == 0 else "N/A"
    except: return "N/A"

def check_files():
    if not RESULTS_DIR.exists(): return "Directorio no creado."
    files = list(RESULTS_DIR.glob("post_*.md"))
    if not files: return "Sin archivos generados."
    
    report = "\n--- [ESTADO DE ARCHIVOS REALES] ---\n"
    for f in files:
        size_kb = f.stat().st_size / 1024
        report += f"📄 {f.name} | Size: {size_kb:.2f} KB | Words (aprox): {size_kb * 150:.0f}\n"
    return report

if __name__ == "__main__":
    print("Iniciando Hub de Observabilidad v5 (Vigilancia de Tamaño Real)...")
    while True:
        gpu = get_gpu_usage()
        files_report = check_files()
        print(f"\n--- [LATIDO] {time.strftime('%H:%M:%S')} ---")
        print(f"[*] GPU: {gpu}")
        print(files_report)
        time.sleep(15)
