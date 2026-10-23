import type { Metrics, SystemStats } from '../api'
import { inrShort, pct } from '../api'

function rate(s: SystemStats) {
  return s.fraud_seen ? s.fraud_caught / s.fraud_seen : 0
}

export function Scoreboard({ m }: { m: Metrics | null }) {
  if (!m) {
    return (
      <section className="panel" aria-label="Scoreboard">
        <header><h2>Scoreboard</h2></header>
        <div className="empty">Waiting for the stream…</div>
      </section>
    )
  }
  const cb = m.circuit_breaker
  const re = m.rules_engine
  const better = (a: number, b: number, lowerIsBetter = false) => (a === b ? '' : (lowerIsBetter ? a < b : a > b) ? 'win' : 'lose')

  return (
    <section className="panel" aria-label="Circuit Breaker versus rules engine scoreboard">
      <header>
        <h2>Circuit Breaker vs Rules Engine</h2>
        <span className="meta">{cb.seen.toLocaleString('en-IN')} payments · {cb.fraud_seen} fraud seen</span>
      </header>
      <div className="score" role="table">
        <div role="columnheader" />
        <div role="columnheader" className="h c-pass">Circuit Breaker</div>
        <div role="columnheader" className="h muted">Rules Engine</div>

        <div className="lbl" role="rowheader">Fraud intercepted<span className="sub">hold or block / fraud seen</span></div>
        <div className={better(cb.fraud_caught, re.fraud_caught)}>
          <span className="num">{cb.fraud_caught}</span> <span className="muted">/ {cb.fraud_seen}</span>
          <span className="sub">{pct(cb.fraud_caught, cb.fraud_seen)}</span>
          <div className="meter"><b style={{ width: `${rate(cb) * 100}%` }} /></div>
        </div>
        <div className={better(re.fraud_caught, cb.fraud_caught)}>
          <span className="num">{re.fraud_caught}</span> <span className="muted">/ {re.fraud_seen}</span>
          <span className="sub">{pct(re.fraud_caught, re.fraud_seen)}</span>
          <div className="meter"><b style={{ width: `${rate(re) * 100}%` }} /></div>
        </div>

        <div className="lbl" role="rowheader">Legit users wrongly blocked<span className="sub">genuine payments stopped</span></div>
        <div className={better(cb.legit_blocked, re.legit_blocked, true)}>
          <span className="num">{cb.legit_blocked}</span>
          <span className="sub">+{cb.legit_held} held for a question · {cb.legit_nudged} nudged</span>
        </div>
        <div className={better(re.legit_blocked, cb.legit_blocked, true)}>
          <span className="num">{re.legit_blocked}</span>
          <span className="sub">no softer option</span>
        </div>

        <div className="lbl" role="rowheader">Rupees saved<span className="sub">fraud amount intercepted</span></div>
        <div className={better(cb.rupees_saved, re.rupees_saved)}>
          <span className="num">{inrShort(cb.rupees_saved)}</span>
          <span className="sub">of {inrShort(cb.fraud_amount)} at risk</span>
        </div>
        <div className={better(re.rupees_saved, cb.rupees_saved)}>
          <span className="num">{inrShort(re.rupees_saved)}</span>
          <span className="sub">of {inrShort(re.fraud_amount)} at risk</span>
        </div>

        <div className="lbl" role="rowheader">Decision latency<span className="sub">p50 / p95, measured</span></div>
        <div>
          <span className="num">{cb.p50_ms.toFixed(2)}</span> <span className="muted">/ {cb.p95_ms.toFixed(2)} ms</span>
          <span className="sub">XGBoost + factor attribution</span>
        </div>
        <div>
          <span className="num">{re.p50_ms.toFixed(3)}</span> <span className="muted">/ {re.p95_ms.toFixed(3)} ms</span>
          <span className="sub">3 static rules</span>
        </div>
      </div>
      <div className="legend">
        <span>Model v{m.model.version} · trained on {m.model.trained_on.toLocaleString('en-IN')} payments · {m.model.features} features</span>
        <span>Base model AUC on held-out days (typologies 1–4): {m.model.base_auc_typologies_1_4.toFixed(4)}</span>
      </div>
    </section>
  )
}
