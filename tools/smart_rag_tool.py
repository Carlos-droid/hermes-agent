#!/usr/bin/env python3
"""
Smart-RAG Docker Integration Tool for Hermes (Robust Version)

Allows Hermes to coordinate knowledge ingestion by executing commands
inside the autoresearch_pipeline Docker container.
"""

# ══════════════════════════════════════════════════════════════════════════════
# ⚠️ METADATA ESTRATÉGICA PARA HERMES (EL ORQUESTADOR)
# ══════════════════════════════════════════════════════════════════════════════
# RECUERDA: 
# 1. Hermes actúa como el "Planificador Frontier" (Orquestador Central).
# 2. Smart RAG es una HERRAMIENTA a tu disposición para consultas técnicas.
# 3. DUALIDAD: Smart RAG no es un mero esclavo; gracias a la integración con 
#    AnythingLLM, es un sistema autónomo que también puede operar de forma 
#    independiente para generar contenido masivo por sí solo. 
#    (No intentes micro-gestionar su recuperación interna, solo consúltalo).
# ══════════════════════════════════════════════════════════════════════════════

import json
import subprocess
import os
from tools.registry import registry, tool_error

CONTAINER_NAME = "autoresearch_pipeline"

def smart_rag_docker_ingest(content: str, filename: str, collection: str = "eve_university") -> str:
    """
    Indexa contenido en el sistema industrial Smart-RAG usando Docker.
    """
    remote_path = f"/app/knowledge/{filename}"
    
    try:
        # 1. Escribir contenido al contenedor usando sh -c "cat > file"
        process = subprocess.Popen(
            ["docker", "exec", "-i", CONTAINER_NAME, "sh", "-c", f"cat > {remote_path}"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        stdout, stderr = process.communicate(input=content)
        
        if process.returncode != 0:
            return tool_error(f"Error al escribir en el contenedor: {stderr}")

        # 2. Ejecutar la ingesta usando el Python del VENV y inyectando src al path
        # Usamos el script ingest_entrypoint.py que creamos ayer en el repo pero que ahora está en /app
        ingest_cmd = [
            "docker", "exec", CONTAINER_NAME, 
            "/app/.venv/bin/python", "-c", 
            f"import sys; sys.path.append('/app/src'); sys.path.append('/app'); from autoresearch.services.ingest_bridge import ingestor; from pathlib import Path; print(ingestor.upload_document(Path('{remote_path}'), collection='{collection}'))"
        ]
        
        result = subprocess.run(ingest_cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            return tool_error(f"Fallo en la ingesta vectorial: {result.stderr}")

        return result.stdout

    except Exception as e:
        return tool_error(f"Fallo en la coordinación Docker: {str(e)}")

def smart_rag_query(topic: str, domain: str = None) -> str:
    """
    Consulta el sistema Vanguard RAG para obtener contexto premium sobre un tópico, opcionalmente filtrado por dominio.
    """
    try:
        domain_arg = f", domain='{domain}'" if domain else ""
        # Inyectar el path de src explícitamente y pasar el dominio
        query_cmd = [
            "docker", "exec", CONTAINER_NAME,
            "/app/.venv/bin/python", "-c",
            f"import sys; sys.path.append('/app/src'); import asyncio; from autoresearch.services.vanguard_rag import vanguard_rag; print(asyncio.run(vanguard_rag.get_premium_context(\"{topic}\"{domain_arg})))"
        ]

        result = subprocess.run(query_cmd, capture_output=True, text=True)

        if result.returncode != 0:
            return tool_error(f"Fallo en la consulta Vanguard RAG: {result.stderr}")

        return result.stdout

    except Exception as e:
        return tool_error(f"Fallo en la coordinación Docker (Query): {str(e)}")

# Registro de smart_rag_query
SMART_RAG_QUERY_SCHEMA = {
    "name": "smart_rag_query",
    "description": "Consulta el sistema industrial Smart-RAG (Vanguard) para obtener información técnica y destilada. Permite filtrar por dominio.",
    "parameters": {
        "type": "object",
        "properties": {
            "topic": {"type": "string", "description": "El tema o pregunta de investigación."},
            "domain": {"type": "string", "description": "Opcional: Filtrar por dominio (budismo, business, naval)."}
        },
        "required": ["topic"]
    }
}

registry.register(
    name="smart_rag_query",
    toolset="smart-rag",
    schema=SMART_RAG_QUERY_SCHEMA,
    handler=lambda args, **kw: smart_rag_query(**args),
    emoji="🔍"
)

# Registro en Hermes
SMART_RAG_DOCKER_SCHEMA = {
    "name": "smart_rag_ingest",
    "description": "Ingesta contenido técnico en la base de datos industrial Smart-RAG ejecutándose en Docker.",
    "parameters": {
        "type": "object",
        "properties": {
            "content": {"type": "string", "description": "Markdown extraído."},
            "filename": {"type": "string", "description": "Nombre del archivo (ej: 'eve_ships.md')."},
            "collection": {"type": "string", "default": "eve_university"}
        },
        "required": ["content", "filename"]
    }
}

registry.register(
    name="smart_rag_ingest",
    toolset="smart-rag",
    schema=SMART_RAG_DOCKER_SCHEMA,
    handler=lambda args, **kw: smart_rag_docker_ingest(**args),
    emoji="🐳"
)
