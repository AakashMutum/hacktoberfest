import type { Metrics, SystemStats } from '../api'
import { inrShort, pct } from '../api'

function rate(s: SystemStats) {
  return s.fraud_seen ? s.fraud_caught / s.fraud_seen : 0
}

function RulesHead({ name, rules }: { name: string; rules: string[] }) {
  return (
    <div role="columnheader" className="h muted rules-head" tabIndex={0} aria-describedby={`rules-${name}`}>
      {name === 'simple' ? 'Rules A · simple' : 'Rules B · tight'}
      <span className="tooltip" role="tooltip" id={`rules-${name}`}>
        Blocks if any rule fires:
        <ul className="list">{rules.map((r) => <li key={r}>{r}</li>)}</ul>
      </span>
    </div>
  )
}

export function Scoreboard({ m, rules }: { m: Metrics | null; rules: { simple: string[]; tight: string[] } | null }) {
  if (!m) {
    return (
      <section className="panel" aria-label="Scoreboard">
        <header><h2>Scoreboard</h2></header>
        <div className="empty">Waiting for the stream…</div>
      </section>
    )
  }
  const systems: SystemStats[] = [m.circuit_breaker, m.rules_engine, m.rules_tight]
  const best = (vals: number[], lower = false) => {
    const target = lower ? Math.min(...vals) : Math.max(...vals)
    return vals.map((v) => (vals.every((x) => x === v) ? '' : v === target ? 'win' : ''))
  }
  const caught = best(systems.map((s) => s.fraud_caught))
  const blocked = best(systems.map((s) => s.legit_blocked), true)
  const saved = best(systems.map((s) => s.rupees_saved))
  const cb = m.circuit_breaker
  const ms = (v: number) => (v < 0.1 ? v.toFixed(3) : v.toFixed(2))

  return (
    <section className="panel" aria-label="Circuit Breaker versus rules engines scoreboard">
      <header>
        <h2>Breaker vs Rules</h2>
        <span className="meta">{cb.seen.toLocaleString('en-IN')} payments · {cb.fraud_seen} fraud seen</span>
      </header>
      <div className="score" role="table">
        <div role="columnheader" />
        <div role="columnheader" className="h c-pass">Circuit Breaker</div>
        <RulesHead name="simple" rules={rules?.simple ?? []} />
        <RulesHead name="tight" rules={rules?.tight ?? []} />

        <div className="lbl" role="rowheader">Fraud intercepted<span className="sub">hold or block / fraud seen</span></div>
        {systems.map((s, i) => (
          <div key={i} className={caught[i]}>
            <span className="num">{s.fraud_caught}</span> <span className="muted">/ {s.fraud_seen}</span>
            <span className="sub">{pct(s.fraud_caught, s.fraud_seen)}</span>
            <div className="meter"><b style={{ width: `${rate(s) * 100}%` }} /></div>
          </div>
        ))}

        <div className="lbl" role="rowheader">Legit users wrongly blocked<span className="sub">genuine payments stopped</span></div>
        {systems.map((s, i) => (
          <div key={i} className={blocked[i]}>
            <span className="num">{s.legit_blocked}</span>
            <span className="sub">{i === 0 ? `+${s.legit_held} held · ${s.legit_nudged} nudged` : 'block only'}</span>
          </div>
        ))}

        <div className="lbl" role="rowheader">Rupees saved<span className="sub">fraud amount intercepted</span></div>
        {systems.map((s, i) => (
          <div key={i} className={saved[i]}>
            <span className="num">{inrShort(s.rupees_saved)}</span>
            <span className="sub">of {inrShort(s.fraud_amount)}</span>
          </div>
        ))}

        <div className="lbl" role="rowheader">Decision latency<span className="sub">p50 / p95 ms, measured</span></div>
        {systems.map((s, i) => (
          <div key={i}>
            <span className="num">{ms(s.p50_ms)}</span>
            <span className="sub">p95 {ms(s.p95_ms)}</span>
          </div>
        ))}
      </div>
      <div className="legend">
        <span>Model v{m.model.version} · trained on {m.model.trained_on.toLocaleString('en-IN')} payments · {m.model.features} features</span>
        <span>Base model AUC on held-out days (typologies 1–4): {m.model.base_auc_typologies_1_4.toFixed(4)}</span>
        <span>Hover or focus a rules header to see its exact rules.</span>
      </div>
    </section>
  )
}
