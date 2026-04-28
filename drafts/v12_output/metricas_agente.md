# Informe de Desempeño de Agentes Locales (V12)
| Modelo | Fase | Éxito | Tiempo Medio | Herramientas |
|---|---|---|---|---|
| `qwen3.5:9b` | investigator | ❌ 40% | 88.0s | smart-rag |
| `qwen3.5:9b` | writer | ❌ 0% | 0.0s | web |
| `qwen3.5:9b` | cycle | ❌ 0% | 0.0s | smart-rag |
| `qwen2.5:14b` | investigator | ❌ 33% | 135.6s | smart-rag |
| `qwen2.5:14b` | writer | ❌ 0% | 0.0s | web |
| `qwen2.5:14b` | cycle | ❌ 0% | 0.0s | smart-rag |
| `deepseek-v2:16b` | investigator | ❌ 0% | 0.0s | smart-rag |
| `qwen2.5:7b` | investigator | ✅ 100% | 51.7s | smart-rag |
| `qwen2.5:7b` | writer | ✅ 100% | 84.6s | web |
| `qwen2.5:7b` | corrector | ⚠️ 66% | 85.0s | file, rae |
| `qwen2.5:7b` | judge | ❌ 0% | 0.0s | google/gemini-2.0-flash-lite-001 |
| `qwen2.5:7b` | cycle | ❌ 0% | 0.0s | google/gemini-2.0-flash-lite-001, file, web, smart-rag, rae |
| `llama3.1:8b` | investigator | ✅ 100% | 53.7s | smart-rag |
| `llama3.1:8b` | writer | ❌ 50% | 142.5s | web |
| `llama3.1:8b` | corrector | ❌ 0% | 0.0s | file, rae |