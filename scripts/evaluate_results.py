import os
import json
from openai import OpenAI

# Configuración de OpenRouter para el Juez
client = OpenAI(
  base_url="https://openrouter.ai/api/v1",
  api_key=os.getenv("OPENROUTER_API_KEY"),
)

JUDGE_MODEL = "deepseek/deepseek-r1"

# ESTACIÓN 3: El Juez (Zero-Tolerance)
STATION_3_CONFIG = {
    "temperature": 0.0,
    "top_p": 1.0,
    "frequency_penalty": 0.0,
    "presence_penalty": 0.0,
    "max_tokens": 1000 # Equivalente a num_predict en la API de OpenAI/OpenRouter
}

SYSTEM_PROMPT = """Eres un experto evaluador SEO y editor técnico especializado en las directrices E-E-A-T de Google 2025.
Tu comportamiento es de "Zero-Tolerance". Eres un auditor técnico riguroso.
Tu tarea es evaluar textos históricos/técnicos según estos criterios:
1. Experience (Experiencia)
2. Expertise (Conocimiento técnico)
3. Authoritativeness (Autoridad)
4. Trustworthiness (Confiabilidad)

Debes devolver un JSON estrictamente estructurado con este formato:
{
  "scores": {
    "experience": int,
    "expertise": int,
    "authoritativeness": int,
    "trustworthiness": int
  },
  "justification": "breve explicación detallada de la nota",
  "word_count": int,
  "is_original": bool
}
No añadas texto adicional fuera del JSON."""

def evaluate_post(post_content):
    try:
        completion = client.chat.completions.create(
          model=JUDGE_MODEL,
          messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Evalúa el siguiente post:\n\n{post_content}"}
          ],
          response_format={"type": "json_object"},
          **STATION_3_CONFIG
        )
        return json.loads(completion.choices[0].message.content)
    except Exception as e:
        print(f"Error evaluating post: {e}")
        return None

def main():
    results = {}
    for file in os.listdir("."):
        if file.startswith("post_") and file.endswith(".md"):
            model_name = file.replace("post_", "").replace(".md", "")
            print(f"Evaluating {model_name}...")
            with open(file, "r", encoding="utf-8") as f:
                content = f.read()
            
            evaluation = evaluate_post(content)
            if evaluation:
                metrics_file = f"test_report_{model_name}.json"
                if os.path.exists(metrics_file):
                    with open(metrics_file, "r") as f:
                        metrics = json.load(f)
                    evaluation["metrics"] = metrics
                
                results[model_name] = evaluation
                generate_final_report(model_name, evaluation, content)

    with open("full_benchmark_results.json", "w") as f:
        json.dump(results, f, indent=4)

def generate_final_report(model_name, data, post_content):
    # Calcular promedios y veredictos
    score_avg = sum(data['scores'].values()) / 4
    report = f"""# Informe de Prueba Analítica: {model_name}
## 1. Métricas de Rendimiento (Datos Brutos)
- Velocidad: {data['metrics']['tps']:.2f} tokens/s
- Tiempo Total: {data['metrics']['duration_s']:.2f} segundos
- vRAM Max: {data['metrics']['vram_max_mb']} MB
- Longitud del Texto: {data['word_count']} palabras

## 2. Evaluación de Contenido (Escala 1-10)
- Cumplimiento E-E-A-T: {score_avg:.1f}
- Creatividad y Originalidad: {data['scores']['experience']}
- Precisión Histórica: {data['scores']['expertise']}

## 3. Post Generado
{post_content}

## 4. Veredicto del Coordinador
- Fortalezas y Debilidades: {data['justification']}
- Recomendación de uso: Basado en TPS y calidad, este modelo es {'ideal para redacción extensa' if data['metrics']['tps'] > 12 else 'mejor para planificación detallada'}.
"""
    with open(f"REPORT_{model_name}.md", "w", encoding="utf-8") as f:
        f.write(report)

if __name__ == "__main__":
    main()
