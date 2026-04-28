import sys
import os
import pytest
from unittest.mock import AsyncMock, patch

# Añadir el path para importar el orquestador
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from orchestrators.run_editorial_v85_master import (
    router, 
    node_frontier, 
    node_researcher,
    EditorialState
)

# ══════════════════════════════════════════════════════════════════════════════
# TDD: Pruebas del Router (Swarm Handoffs)
# ══════════════════════════════════════════════════════════════════════════════

def test_router_flujo_normal():
    """Verifica que la cadena de montaje avance secuencialmente."""
    state = EditorialState(estado_actual="inicio", error_critico=None)
    assert router(state) == "researcher"
    
    state["estado_actual"] = "investigado"
    assert router(state) == "writer"
    
    state["estado_actual"] = "redactado"
    assert router(state) == "gemini_auditor"
    
    state["estado_actual"] = "auditado_gemini"
    assert router(state) == "corrector"
    
    state["estado_actual"] = "corregido"
    assert router(state) == "translator"
    
    state["estado_actual"] = "traducido"
    assert router(state) == "frontier"

def test_router_emergencia_fail_fast():
    """Verifica que un error dispare el retorno inmediato al Frontier (Supervisor)."""
    state = EditorialState(estado_actual="investigado", error_critico="RAG Timeout")
    assert router(state) == "frontier"

# ══════════════════════════════════════════════════════════════════════════════
# TDD: Pruebas de los Nodos
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_frontier_mitiga_errores():
    """Verifica que el Frontier limpie el error y reinicie la ruta."""
    state = EditorialState(estado_actual="investigado", error_critico="Database Error")
    new_state = await node_frontier(state)
    
    assert new_state["error_critico"] is None
    assert new_state["estado_actual"] == "inicio"

@pytest.mark.asyncio
@patch('orchestrators.run_editorial_v85_master.researcher_llm')
async def test_researcher_falla_rapido(mock_llm):
    """Verifica que si el LLM/RAG explota, el investigador genera un error crítico."""
    # Simulamos que el RAG o el LLM fallan
    mock_llm.ainvoke.side_effect = Exception("Conexión Rechazada")
    
    state = EditorialState(topic="Test", domain="naval", estado_actual="inicio", error_critico=None)
    new_state = await node_researcher(state)
    
    assert "Conexión Rechazada" in new_state["error_critico"]
    assert new_state["estado_actual"] == "inicio" # El estado no avanzó

