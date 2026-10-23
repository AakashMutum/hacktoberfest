import { useState } from 'react'
import { api, inr, type Lang, type ScanResult } from '../api'

export function Scan({ lang, llmAvailable }: { lang: Lang; llmAvailable: boolean }) {
  const [over, setOver] = useState(false)
  const [busy, setBusy] = useState(false)
  const [res, setRes] = useState<ScanResult | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [name, setName] = useState<string | null>(null)

  const send = async (file: File | undefined) => {
    if (!file) return
    setName(file.name)
    setBusy(true)
    setErr(null)
    setRes(null)
    try {
      setRes(await api.scan(file, lang))
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="panel" aria-label="Screenshot scan">
      <header>
        <h2>Scan a screenshot</h2>
        <span className="meta">Gemma 4 vision</span>
      </header>
      <div className="body stack">
        <label
          className={`drop${over ? ' over' : ''}`}
          onDragOver={(e) => { e.preventDefault(); setOver(true) }}
          onDragLeave={() => setOver(false)}
          onDrop={(e) => { e.preventDefault(); setOver(false); send(e.dataTransfer.files[0]) }}
        >
          <input type="file" accept="image/png,image/jpeg,image/webp" onChange={(e) => send(e.target.files?.[0])} />
          {busy ? `Reading ${name}…` : 'Drop a payment request or scam SMS screenshot, or tap to choose'}
        </label>
        {!llmAvailable && <span className="c-warn">No Gemma provider is reachable right now, so a scan will report unavailable.</span>}
        {res && (
          <div className="stack" style={{ gap: 6 }} aria-live="polite">
            <div className="kv">
              <span>payee <b>{res.payee ?? '—'}</b></span>
              <span>amount <b>{res.amount != null ? inr(res.amount) : '—'}</b></span>
              <span>urgency <b className={res.urgency === 'high' ? 'c-trip' : res.urgency === 'medium' ? 'c-warn' : 'c-pass'}>{res.urgency}</b></span>
              <span>risk contribution <b>+{res.risk_contribution.toFixed(2)}</b></span>
            </div>
            {res.summary && <div lang={lang}>{res.summary}</div>}
            {res.scam_signals.length > 0 && (<div><span className="src muted">Scam signals</span><ul className="list">{res.scam_signals.map((s, i) => <li key={i}>{s}</li>)}</ul></div>)}
            {res.pressure_cues.length > 0 && (<div><span className="src muted">Pressure cues</span><ul className="list">{res.pressure_cues.map((s, i) => <li key={i}>{s}</li>)}</ul></div>)}
            <span className="src c-pass">{res.label} · {(res.latency_ms / 1000).toFixed(1)} s</span>
          </div>
        )}
        {err && <span className="err">{err}</span>}
      </div>
    </section>
  )
}
