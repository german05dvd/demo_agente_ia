# ═══════════════════════════════════════════════════════════
# IMPORTS
# ═══════════════════════════════════════════════════════════

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import TypedDict, List, Dict, Any, Optional, Literal
import requests
import json
import asyncio
from datetime import datetime

# LangGraph: framework de grafos de estados para agentes
from langgraph.graph import StateGraph, END

# ═══════════════════════════════════════════════════════════
# CONFIGURACIÓN: LM Studio local
# ═══════════════════════════════════════════════════════════

LM_STUDIO_URL = "http://localhost:1234/v1/chat/completions"
MODEL_NAME = "qwen2.5-7b-instruct"  # Ajusta según tu modelo descargado

# ═══════════════════════════════════════════════════════════
# TIPOS DE DATOS (TypedDict)
# 
# State es el "objeto de memoria" que persiste entre nodos.
# Cada nodo lee y escribe campos de este diccionario.
# ═══════════════════════════════════════════════════════════

class AgentState(TypedDict):
    # Input del usuario
    company_name: str
    objective: str  # ej: "optimize_working_capital"
    
    # Datos percibidos (Node 1)
    vendor_data: Optional[List[Dict]]
    current_dpo: Optional[int]  # Days Payable Outstanding actual
    
    # Análisis (Node 2)
    analysis: Optional[str]       # Texto del LLM explicando hallazgos
    sufficient_data: Optional[bool]
    missing_info: Optional[List[str]]
    
    # Plan (Node 3)
    proposal: Optional[Dict]     # {"new_dpo": 45, "expected_savings": 150000}
    
    # Control de flujo
    needs_more_data: Optional[bool]  # Flag para conditional edge
    
    # Log para frontend (acumulamos mensajes)
    execution_log: List[Dict]  # [{"timestamp": "...", "node": "...", "message": "..."}]

# ═══════════════════════════════════════════════════════════
# FUNCIÓN: Llamar a LM Studio (tu "LLM local")
# ═══════════════════════════════════════════════════════════

def call_llm(messages: List[Dict], temperature: float = 0.7) -> str:
    """
    messages: lista de {"role": "system"|"user"|"assistant", "content": "..."}
    retorna: texto generado por el modelo
    """
    payload = {
        "model": MODEL_NAME,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": 500
    }
    
    try:
        response = requests.post(LM_STUDIO_URL, json=payload, timeout=30)
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]
    except Exception as e:
        return f"ERROR_LLM: {str(e)}"

# ═══════════════════════════════════════════════════════════
# NODE 1: PERCEIVE (Simulación de consulta a ERP)
# ═══════════════════════════════════════════════════════════

def node_perceive(state: AgentState) -> Dict[str, Any]:
    """
    Simula consultar un ERP. En producción, aquí iría MCP client
    llamando a NetSuite/SAP.
    """
    # Log para frontend
    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "node": "PERCEIVE",
        "message": f"Consultando datos de {state['company_name']}..."
    }
    
    # SIMULACIÓN: Datos mock de "ERP"
    mock_vendor_data = [
        {"id": "VEN-001", "name": "Acme Supplies", "annual_spend": 500000, 
         "current_dpo": 30, "payment_history": [28, 32, 31, 29]},
        {"id": "VEN-002", "name": "Global Tech", "annual_spend": 1200000,
         "current_dpo": 35, "payment_history": [35, 36, 34, 35]},
    ]
    
    # Calcular DPO promedio actual
    avg_dpo = sum(v["current_dpo"] for v in mock_vendor_data) // len(mock_vendor_data)
    
    return {
        "vendor_data": mock_vendor_data,
        "current_dpo": avg_dpo,
        "execution_log": state.get("execution_log", []) + [log_entry]
    }

# ═══════════════════════════════════════════════════════════
# NODE 2: ANALYZE (LLM decide si tenemos suficiente info)
# ═══════════════════════════════════════════════════════════

def node_analyze(state: AgentState) -> Dict[str, Any]:
    """
    El LLM analiza los datos y decide: ¿sigue adelante o necesita más?
    """
    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "node": "ANALYZE",
        "message": f"Analizando DPO actual: {state['current_dpo']} días..."
    }
    
    # Construir prompt para LLM
    system_prompt = """Eres un agente financiero experto en working capital.
Analiza los datos proporcionados y determina si tienes suficiente información 
para proponer optimización de términos de pago.

Responde ÚNICAMENTE en este formato JSON:
{
    "sufficient_data": true/false,
    "missing_info": ["campo1", "campo2"] o [],
    "analysis": "tu explicación aquí",
    "reasoning": "por qué sí o no hay suficiente info"
}"""

    user_prompt = f"""
Datos de {state['company_name']}:
- Proveedores analizados: {len(state['vendor_data'])}
- DPO promedio actual: {state['current_dpo']} días
- Objetivo: {state['objective']}

¿Tienes suficiente información para proponer nuevos términos?
"""
    
    # Llamar a LM Studio
    llm_response = call_llm([
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ])
    
    # Parsear respuesta (con fallback si el LLM no responde JSON válido)
    try:
        # Extraer JSON de la respuesta (a veces el LLM pone texto extra)
        json_start = llm_response.find('{')
        json_end = llm_response.rfind('}') + 1
        parsed = json.loads(llm_response[json_start:json_end])
    except:
        parsed = {
            "sufficient_data": True,  # Fallback conservador
            "missing_info": [],
            "analysis": llm_response[:200],
            "reasoning": "Fallback por error de parseo"
        }
    
    return {
        "analysis": parsed.get("analysis", ""),
        "sufficient_data": parsed.get("sufficient_data", True),
        "missing_info": parsed.get("missing_info", []),
        "needs_more_data": not parsed.get("sufficient_data", True),
        "execution_log": state["execution_log"] + [log_entry]
    }

# ═══════════════════════════════════════════════════════════
# NODE 3: PLAN (LLM genera propuesta concreta)
# ═══════════════════════════════════════════════════════════

def node_plan(state: AgentState) -> Dict[str, Any]:
    """
    El LLM genera una propuesta numérica de nuevos términos.
    """
    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "node": "PLAN",
        "message": "Generando propuesta de optimización..."
    }
    
    system_prompt = """Eres un agente financiero. Genera una propuesta 
concreta de optimización de working capital.

Responde en JSON:
{
    "current_dpo": número,
    "proposed_dpo": número,
    "expected_annual_savings_usd": número,
    "risk_level": "LOW"/"MEDIUM"/"HIGH",
    "justification": "explicación"
}"""

    user_prompt = f"""
Empresa: {state['company_name']}
DPO actual promedio: {state['current_dpo']} días
Proveedores: {json.dumps(state['vendor_data'], indent=2)}

Genera propuesta de nuevos términos de pago.
"""
    
    llm_response = call_llm([
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ])
    
    # Parsear con fallback
    try:
        json_start = llm_response.find('{')
        json_end = llm_response.rfind('}') + 1
        proposal = json.loads(llm_response[json_start:json_end])
    except:
        proposal = {
            "current_dpo": state['current_dpo'],
            "proposed_dpo": state['current_dpo'] + 10,
            "expected_annual_savings_usd": 100000,
            "risk_level": "MEDIUM",
            "justification": "Propuesta fallback por error de parseo: " + llm_response[:100]
        }
    
    return {
        "proposal": proposal,
        "execution_log": state["execution_log"] + [log_entry]
    }

# ═══════════════════════════════════════════════════════════
# NODE 4: EXECUTE (Formatea resultado final)
# ═══════════════════════════════════════════════════════════

def node_execute(state: AgentState) -> Dict[str, Any]:
    """
    Nodo final: prepara output para el usuario.
    """
    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "node": "EXECUTE",
        "message": f"✓ Propuesta final: DPO {state['proposal']['proposed_dpo']} días"
    }
    
    return {
        "execution_log": state["execution_log"] + [log_entry]
    }

# ═══════════════════════════════════════════════════════════
# FUNCIÓN DE RUTEO: Decide si ciclar o seguir adelante
# ═══════════════════════════════════════════════════════════

def route_after_analyze(state: AgentState) -> Literal["perceive", "plan"]:
    """
    Conditional edge: lee la flag que el LLM dejó en el state.
    Si necesita más datos, vuelve a PERCEIVE (ciclo).
    Si no, sigue a PLAN.
    """
    if state.get("needs_more_data", False):
        return "perceive"  # ← CICLO: vuelve a empezar
    return "plan"

# ═══════════════════════════════════════════════════════════
# CONSTRUCCIÓN DEL GRAFO LANGGRAPH
# ═══════════════════════════════════════════════════════════

def build_agent():
    # Crear grafo con el tipo de estado definido
    workflow = StateGraph(AgentState)
    
    # Agregar nodos
    workflow.add_node("perceive", node_perceive)
    workflow.add_node("analyze", node_analyze)
    workflow.add_node("plan", node_plan)
    workflow.add_node("execute", node_execute)
    
    # Definir flujo
    workflow.set_entry_point("perceive")           # Inicio
    workflow.add_edge("perceive", "analyze")       # Siempre de perceive a analyze
    
    # Conditional edge: analyze decide si cicla o sigue
    workflow.add_conditional_edges(
        "analyze",
        route_after_analyze,                       # Función que decide
        {
            "perceive": "perceive",                # ← CICLO
            "plan": "plan"                         # → Sigue adelante
        }
    )
    
    workflow.add_edge("plan", "execute")           # plan → execute
    workflow.add_edge("execute", END)              # Fin
    
    # Compilar (sin checkpointer para simplidad, en producción usar SQLiteSaver)
    return workflow.compile()

# Instancia global del agente
agent = build_agent()

# ═══════════════════════════════════════════════════════════
# FASTAPI: API HTTP para el frontend
# ═══════════════════════════════════════════════════════════

app = FastAPI(title="Agente Working Capital")

# CORS: permitir que frontend en localhost:5173 llame a backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Modelo de entrada
class RunRequest(BaseModel):
    company_name: str
    objective: str = "optimize_working_capital"

# Endpoint síncrono (para probar rápido)
@app.post("/api/run")
async def run_agent(request: RunRequest):
    """
    Ejecuta el agente completo y retorna resultado final.
    """
    # Estado inicial
    initial_state = {
        "company_name": request.company_name,
        "objective": request.objective,
        "vendor_data": None,
        "current_dpo": None,
        "analysis": None,
        "sufficient_data": None,
        "missing_info": None,
        "proposal": None,
        "needs_more_data": None,
        "execution_log": []
    }
    
    # Ejecutar grafo
    final_state = agent.invoke(initial_state)
    
    return {
        "success": True,
        "company": request.company_name,
        "proposal": final_state["proposal"],
        "execution_log": final_state["execution_log"],
        "total_steps": len(final_state["execution_log"])
    }

# Endpoint streaming (log en vivo vía Server-Sent Events)
@app.post("/api/run-stream")
async def run_agent_stream(request: RunRequest):
    """
    Ejecuta el agente y emite eventos en vivo para el frontend.
    """
    async def event_generator():
        initial_state = {
            "company_name": request.company_name,
            "objective": request.objective,
            "vendor_data": None,
            "current_dpo": None,
            "analysis": None,
            "sufficient_data": None,
            "missing_info": None,
            "proposal": None,
            "needs_more_data": None,
            "execution_log": []
        }
        
        # LangGraph permite iterar paso a paso
        for step_state in agent.stream(initial_state):
            # Emitir cada paso como evento SSE
            yield f"data: {json.dumps({'type': 'step', 'state': step_state})}\n\n"
            await asyncio.sleep(0.1)  # Pequeña pausa para no saturar
        
        # Evento final
        yield f"data: {json.dumps({'type': 'complete', 'final': step_state})}\n\n"
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream"
    )

# Health check
@app.get("/health")
async def health():
    return {"status": "ok", "lm_studio": LM_STUDIO_URL}

# ═══════════════════════════════════════════════════════════
# EJECUCIÓN
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn
    print("🚀 Iniciando servidor en http://localhost:8000")
    print("🧠 Usando LM Studio en", LM_STUDIO_URL)
    uvicorn.run(app, host="0.0.0.0", port=8000)