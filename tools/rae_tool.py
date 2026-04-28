import requests
import json
import time
from tools.registry import registry

# Caché simple para evitar peticiones redundantes
RAE_CACHE = {}

def rae_check(word: str) -> str:
    """
    Consulta la definición de una palabra en la RAE vía rae-api.com con protección de Rate Limit.
    """
    word = word.lower().strip()
    
    # 1. Verificar caché
    if word in RAE_CACHE:
        return f"[Cache] {RAE_CACHE[word]}"
    
    try:
        # 2. Respetar al servidor (Throttling)
        time.sleep(0.5) 
        
        url = f"https://rae-api.com/api/words/{word}"
        response = requests.get(url, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            defs = data.get("definitions", [])
            if not defs:
                return f"No se encontraron definiciones para '{word}'."
                
            result = f"Definiciones para '{word}':\n"
            for i, d in enumerate(defs, 1):
                result += f"{i}. {d.get('definition')}\n"
            
            # Guardar en caché
            RAE_CACHE[word] = result
            return result
            
        elif response.status_code == 429:
            return "AVISO: Rate limit alcanzado en la API de la RAE. Usando conocimientos previos o manual local."
        else:
            return f"La API de la RAE no pudo procesar la palabra '{word}' (Error {response.status_code})."
            
    except Exception as e:
        return f"Error técnico consultando la RAE: {str(e)}"

RAE_CHECK_SCHEMA = {
    "name": "rae_check",
    "description": "Consulta el diccionario de la RAE para verificar definiciones y léxico técnico.",
    "parameters": {
        "type": "object",
        "properties": {
            "word": {"type": "string", "description": "La palabra a consultar."}
        },
        "required": ["word"]
    }
}

registry.register(
    name="rae_check",
    toolset="rae",
    schema=RAE_CHECK_SCHEMA,
    handler=lambda args, **kw: rae_check(**args),
    emoji="📖"
)
