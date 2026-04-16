from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import TypedDict, List, Dict, Any, Optional, Literal
import requests
import json
import asyncio
from datetime import datetime

from langgraph.graph import StateGraph, END

url = "http://127.0.0.1:1234/v1/chat/completions" 
model = "llama-3.2-1b-instruct"

class state(TypedDict):
    company : str
    objective : str
    data_vendedor : Optional[List[Dict]]
    dpo_actual : Optional[int]
    analisis : Optional[str]
    suficiente : Optional[bool]
    faltante : Optional[list[str]]
    propuesta : Optional[Dict]
    suficiente2: Optional[bool]
    logs: List[Dict] 

def LLM(mensajes: List[Dict], temperatura: float = 0.7) -> str:
    carga = {
        "model": model,
        "messages": mensajes,
        "temperature": temperatura,
        "max_tokens": 1000
        }
    try:
        respuesta = requests.post(url, json=carga, timeout=30)
        respuesta.raise_for_status()
        return respuesta.json()["choices"][0]["message"]["content"]
    except Exception as e:
        return f"error: {str(e)}"
    
def nodo1(estado: state) -> Dict[str, Any]:
    entrada = {
        "fecha": datetime.now().isoformat(),
        "nodo": "1-recibir datos",
        "mensaje": f"leyendo datos de {estado['company']}"
    }
    mock = [
        {"id": "VEN-001", "name": "Acme Supplies", "annual_spend": 500000, 
         "dpo_actual": 30, "payment_history": [28, 32, 31, 29]},
        {"id": "VEN-002", "name": "Global Tech", "annual_spend": 1200000,
         "dpo_actual": 35, "payment_history": [35, 36, 34, 35]},
    ]
    avg_dpo = sum(v["dpo_actual"] for v in mock) // len(mock)
    return {
        "data_vendedor": mock,
        "dpo_actual": avg_dpo,
        "logs": estado.get("logs", []) + [entrada]
    }

def nodo2(estado: state) -> Dict[str, Any]:
    entrada = {
        "fecha":datetime.now().isoformat(),
        "nodo": "2-analisis calidad de los datos",
        "mensaje": f"modelo({model}) analizando calidad de datos"
    }
    base = """Eres un agente financiero experto en working capital.
Analiza los datos proporcionados y determina si tienes suficiente información 
para proponer optimización de términos de pago.

Responde ÚNICAMENTE en este formato JSON:
{
    "suficiente": true/false,
    "faltante": ["campo1", "campo2"] o [],
    "analisis": "tu explicación aquí",
    "razonamiento": "por qué sí o no hay suficiente info"
}"""

    usuario = f"""
Datos de {estado['company']}:
- Proveedores analizados: {len(estado['data_vendedor'])}
- DPO promedio actual: {estado['dpo_actual']} días
- Objetivo: {estado['objective']}

¿Tienes suficiente información para proponer nuevos términos?
"""

    respuesta = LLM([
        {"role": "system", "content": base},
        {"role": "user", "content": usuario}
    ])

    try:
        start = respuesta.find('{')
        end = respuesta.rfind('}') + 1
        parsed = json.loads(respuesta[start:end])
    except:
        parsed = {
            "suficiente": True,
            "faltante": [],
            "analisis": respuesta[:200],
            "razonamieto": "Fallback por error de parseo"
        }
    
    suficiente = parsed.get("suficiente", True)
    return {
        "analisis": parsed.get("analisis", ""),
        "suficiente": suficiente,
        "faltante": parsed.get("faltante", []),
        "necesito": not suficiente,
        "logs": estado.get("logs", []) + [entrada]  
    }

def nodo3(estado: state) -> Dict[str, Any]:
    entrada = {
        "fecha": datetime.now().isoformat(),
        "nodo": "3-propuesta valor numerico",
        "mensaje": "generando propuesta de optimización"
    }
    
    base = """Eres un agente financiero. Genera una propuesta 
concreta de optimización de working capital.

Responde en JSON:
{
    "dpo_actual": número,
    "dpo_propuesta": número,
    "ahorras_anual": número,
    "riesgo": "LOW"/"MEDIUM"/"HIGH",
    "justificacion": "explicación"
}"""

    usuario = f"""
Empresa: {estado['company']}
DPO actual promedio: {estado['dpo_actual']} días
Proveedores: {json.dumps(estado['data_vendedor'], indent=2)}

Genera propuesta de nuevos términos de pago.
"""
    
    respuesta = LLM([
        {"role": "system", "content": base},
        {"role": "user", "content": usuario}
    ])
    
    # Parsear con fallback
    try:
        start = respuesta.find('{')
        end = respuesta.rfind('}') + 1
        proposal = json.loads(respuesta[start:end])
    except:
        proposal = {
            "dpo_actual": estado['dpo_actual'],
            "dpo_propuesta": estado['dpo_actual'] + 10,
            "ahorras_anual": 100000,
            "riesgo": "MEDIUM",
            "justificacion": "Propuesta fallback por error de parseo: " + respuesta[:100]
        }
    
    if "dpo_propuesta" not in proposal:
        proposal["dpo_propuesta"] = estado['dpo_actual'] + 10
    if "justificacion" not in proposal:
        proposal["justificacion"] = "Propuesta generada automáticamente"
    if "ahorras_anual" not in proposal:
        proposal["ahorras_anual"] = 0
    if "riesgo" not in proposal:
        proposal["riesgo"] = "MEDIUM"
    
    return {
        "propuesta": proposal,
        "logs": estado.get("logs", []) + [entrada]
    }

def nodo4(estado: state) -> Dict[str, Any]:
    propuesta = estado.get('propuesta', {})
    dpo_propuesta = propuesta.get('dpo_propuesta', '?')
    justificacion = propuesta.get('justificacion', 'Sin justificación')
    
    entrada = {
        "fecha": datetime.now().isoformat(),
        "nodo": "4-output para cliente",
        "mensaje": f"Propuesta final: DPO {dpo_propuesta} días. {justificacion}"
    }
    return {"logs": estado.get("logs", []) + [entrada]}    

def ruta(estado: state) -> Literal["1-extraer", "3-propuesta"]:
    # Si no hay suficiente información, volvemos a nodo1 para pedir más datos
    if estado.get("suficiente", True) is False:
        return "1-extraer"   # ciclo
    return "3-propuesta"

def agente():
    workflow = StateGraph(state)
    workflow.add_node("1-extraer", nodo1)
    workflow.add_node("2-analizar", nodo2)
    workflow.add_node("3-propuesta", nodo3)
    workflow.add_node("4-mostrar", nodo4)
    
    workflow.set_entry_point("1-extraer")
    workflow.add_edge("1-extraer", "2-analizar")
    workflow.add_conditional_edges(
        "2-analizar",
        ruta,
        {
            "1-extraer": "1-extraer",
            "3-propuesta": "3-propuesta"
        }
    )
    workflow.add_edge("3-propuesta", "4-mostrar")
    workflow.add_edge("4-mostrar", END)
    return workflow.compile()
agent = agente()

app = FastAPI(title="Agente Working Capital")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"], 
    # hay que cambiarlo el puerto vite se va cambiando entre numeros del 1-9
    # recomiendo correr primero el frontend ver que puerto da y editarlo aqui
    # tambien se puede fijar el puerto de vite pero no lo hice
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class inicio(BaseModel):
    company: str
    objective: str = "optimize_working_capital"

@app.post("/api/run")
async def correr(request: inicio):
    inicial = {
        "company": request.company,
        "objective": request.objective,
        "data_vendedor": None,
        "dpo_actual": None,
        "analisis": None,
        "suficiente": None,
        "faltante": None,
        "propuesta": None,
        "necesito": None,
        "logs": []          
    }
    final = agent.invoke(inicial)
    return {
        "exito": True,
        "company": request.company,
        "propuesta": final["propuesta"],
        "logs": final["logs"],
        "pasos": len(final["logs"])
    }

@app.post("/api/run-stream")
async def stream(request: inicio):
    async def evento():
        inicial = {
            "company": request.company,
            "objective": request.objective,
            "data_vendedor": None,
            "dpo_actual": None,
            "analisis": None,
            "suficiente": None,
            "faltante": None,
            "propuesta": None,
            "necesito": None,
            "logs": []
        }
        for paso in agent.stream(inicial):
            yield f"data: {json.dumps({'type': 'step', 'state': paso})}\n\n"
            await asyncio.sleep(0.1)
        yield f"data: {json.dumps({'type': 'complete', 'final': paso})}\n\n"
    return StreamingResponse(evento(), media_type="text/event-stream")

@app.get("/health")
async def health():
    return {"status": "ok", "lm_studio": url}

if __name__ == "__main__":
    import uvicorn
    print("iniciando servidor en http://localhost:8000")
    print("usando LM Studio en", url)
    uvicorn.run(app, host="0.0.0.0", port=8000)