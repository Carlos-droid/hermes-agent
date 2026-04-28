import subprocess
import time
import json
import asyncio
import os

class HermesMonitor:
    def __init__(self, interval=1.0):
        self.interval = interval
        self.metrics = []
        self.running = False

    async def collect_vram(self):
        while self.running:
            try:
                # Query nvidia-smi for used memory in MB
                result = subprocess.run(
                    ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                    capture_output=True, text=True
                )
                if result.returncode == 0:
                    vram_mb = int(result.stdout.strip())
                    self.metrics.append({"timestamp": time.time(), "vram_mb": vram_mb})
            except Exception as e:
                print(f"Monitor error: {e}")
            await asyncio.sleep(self.interval)

    def start(self):
        self.running = True
        self.loop = asyncio.get_event_loop()
        self.task = self.loop.create_task(self.collect_vram())

    def stop(self):
        self.running = False
        return self.metrics

def save_report(model_name, metrics, start_time, end_time, total_tokens, output_text):
    duration = end_time - start_time
    tps = total_tokens / duration if duration > 0 else 0
    vram_avg = sum(m['vram_mb'] for m in metrics) / len(metrics) if metrics else 0
    vram_max = max(m['vram_mb'] for m in metrics) if metrics else 0

    report = {
        "model": model_name,
        "duration_s": duration,
        "total_tokens": total_tokens,
        "tps": tps,
        "vram_avg_mb": vram_avg,
        "vram_max_mb": vram_max,
        "output_length": len(output_text)
    }
    
    with open(f"test_report_{model_name}.json", "w") as f:
        json.dump(report, f, indent=4)
    
    return report
