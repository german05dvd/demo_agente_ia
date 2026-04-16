// ═══════════════════════════════════════════════════════════
// FRONTEND REACT + TYPESCRIPT - Corregido para main.py
// ═══════════════════════════════════════════════════════════

import { useState } from 'react'
import { Play, Loader2, CheckCircle, AlertCircle, Database, 
         Brain, FileText, Send } from 'lucide-react'
import './App.css'

// Tipos (adaptados a la respuesta del backend)
interface LogEntry {
  fecha?: string      // backend usa "fecha"
  nodo?: string       // backend usa "nodo" (ej: "1-recibir datos")
  mensaje?: string    // backend usa "mensaje"
  // compatibilidad con otros formatos
  node?: string
  message?: string
  timestamp?: string
}

interface Propuesta {
  dpo_actual: number
  dpo_propuesta: number
  ahorras_anual: number
  riesgo: string
  justificacion: string
}

function App() {
  const [companyName, setCompanyName] = useState('TechCorp')
  const [objective, setObjective] = useState('optimize_working_capital')
  const [loading, setLoading] = useState(false)
  const [logs, setLogs] = useState<LogEntry[]>([])
  const [propuesta, setPropuesta] = useState<Propuesta | null>(null)
  const [error, setError] = useState<string | null>(null)

  const runAgent = async () => {
    setLoading(true)
    setLogs([])
    setPropuesta(null)
    setError(null)

    try {
      const response = await fetch('http://localhost:8000/api/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          company: companyName,
          objective: objective
        })
      })

      if (!response.ok) {
        const text = await response.text()
        throw new Error(`HTTP ${response.status}: ${text}`)
      }

      const data = await response.json()
      console.log('Datos recibidos:', data)

      if (data.exito) {
        setPropuesta(data.propuesta)
        // El backend puede devolver "logs" o "log"
        const logsData = data.logs || data.log || []
        setLogs(logsData)
      } else {
        setError('Error en la ejecución del agente')
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Error desconocido')
    } finally {
      setLoading(false)
    }
  }

  // Obtener el nombre del nodo (prioriza "nodo" del backend)
  const getNodeName = (log: LogEntry): string => {
    return log.nodo || log.node || ''
  }

  const getNodeIcon = (log: LogEntry) => {
    const nodeName = getNodeName(log)
    if (nodeName.includes('1') || nodeName.includes('extraer')) return <Database size={16} />
    if (nodeName.includes('2') || nodeName.includes('analisis')) return <Brain size={16} />
    if (nodeName.includes('3') || nodeName.includes('propuesta')) return <FileText size={16} />
    if (nodeName.includes('4') || nodeName.includes('output')) return <Send size={16} />
    return <CheckCircle size={16} />
  }

  const getNodeColor = (log: LogEntry): string => {
    const nodeName = getNodeName(log)
    if (nodeName.includes('1')) return '#3b82f6'
    if (nodeName.includes('2')) return '#8b5cf6'
    if (nodeName.includes('3')) return '#f59e0b'
    if (nodeName.includes('4')) return '#10b981'
    return '#6b7280'
  }

  const getMessage = (log: LogEntry): string => {
    return log.mensaje || log.message || JSON.stringify(log)
  }

  const getTimestamp = (log: LogEntry): string => {
    const ts = log.fecha || log.timestamp
    if (ts) return new Date(ts).toLocaleTimeString()
    return ''
  }

  return (
    <div className="app">
      <header className="header">
        <h1>🤖 Agente Working Capital</h1>
        <p>Optimiza términos de pago con IA local (LM Studio)</p>
      </header>

      <div className="control-panel">
        <div className="input-group">
          <label>Empresa:</label>
          <input 
            type="text" 
            value={companyName}
            onChange={(e) => setCompanyName(e.target.value)}
            placeholder="Nombre de la empresa"
          />
        </div>

        <div className="input-group">
          <label>Objetivo:</label>
          <select 
            value={objective}
            onChange={(e) => setObjective(e.target.value)}
          >
            <option value="optimize_working_capital">Optimizar Working Capital</option>
            <option value="reduce_dso">Reducir DSO (Days Sales Outstanding)</option>
            <option value="extend_dpo">Extender DPO (Days Payable Outstanding)</option>
          </select>
        </div>

        <button onClick={runAgent} disabled={loading} className="run-button">
          {loading ? (
            <><Loader2 className="spin" size={20} /> Ejecutando...</>
          ) : (
            <><Play size={20} /> Ejecutar Agente</>
          )}
        </button>
      </div>

      {logs.length > 0 && (
        <div className="log-section">
          <h2>📋 Log de Ejecución</h2>
          <div className="log-container">
            {logs.map((log, index) => (
              <div 
                key={index} 
                className="log-entry" 
                style={{ borderLeftColor: getNodeColor(log) }}
              >
                <div className="log-icon" style={{ color: getNodeColor(log) }}>
                  {getNodeIcon(log)}
                </div>
                <div className="log-content">
                  <div className="log-header">
                    <span className="log-node">{getNodeName(log)}</span>
                    <span className="log-time">{getTimestamp(log)}</span>
                  </div>
                  <div className="log-message">{getMessage(log)}</div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {propuesta && (
        <div className="result-section">
          <h2>✅ Propuesta Generada</h2>
          <div className="proposal-card">
            <div className="proposal-row">
              <span>DPO Actual:</span>
              <strong>{propuesta.dpo_actual} días</strong>
            </div>
            <div className="proposal-row highlight">
              <span>DPO Propuesto:</span>
              <strong>{propuesta.dpo_propuesta} días</strong>
            </div>
            <div className="proposal-row">
              <span>Ahorro Estimado:</span>
              <strong>${propuesta.ahorras_anual?.toLocaleString() || 0} USD/año</strong>
            </div>
            <div className="proposal-row">
              <span>Nivel de Riesgo:</span>
              <span className={`risk-${(propuesta.riesgo || 'medium').toLowerCase()}`}>
                {propuesta.riesgo || 'MEDIUM'}
              </span>
            </div>
            <div className="proposal-justification">
              <h4>Justificación:</h4>
              <p>{propuesta.justificacion}</p>
            </div>
          </div>
        </div>
      )}

      {error && (
        <div className="error-section">
          <AlertCircle size={20} />
          <span>Error: {error}</span>
        </div>
      )}
    </div>
  )
}

export default App