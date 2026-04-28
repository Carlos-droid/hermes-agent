# Informe Ensayo V12 – Sesión session_20260428T085159_7a664d
Generado: 2026-04-28 10:54

| Modelo (primario) | Estado | Palabras | Fases | Retries | Herramientas usadas | Sub-modelos | trace_id |
|---|---|---|---|---|---|---|---|
| `qwen3.5:9b` | ✗ failed | 0 | — | 4 | — | — | `v12_788a06c3` |
| `qwen2.5:14b` | ✗ failed | 0 | — | 4 | — | — | `v12_436fdaaf` |
| `deepseek-v2:16b` | ✗ failed | 0 | — | 4 | — | — | `v12_e810e796` |

## Diagnóstico rápido
```bash
cat v12_output/status.json
grep '"action": "ERROR"' v12_output/logs/telemetry.jsonl
grep 'WATCHDOG_TRIGGERED' v12_output/logs/telemetry.jsonl
```
**Checkpoint:** C:\Users\carlo\Documents\Proyectos_Phyton\hermes\hermes-agent-main\v12_output\checkpoint.json – ahora a prueba de corrupción.