import { useState } from 'react'
import { api, inr, type AdaptResult, type AttackResult } from '../api'

function Bar({ label, rate, color }: { label: string; rate: number; color: string }) {
  return (
    <div className="ba">
      <span className="muted">{label}</span>
      <span className="bar"><b style={{ width: `${rate * 100}%`, background: color }} /></span>
      <span style={{ textAlign: 'right' }}>{(rate * 100).toFixed(1)}%</span>
    </div>
  )
}

export function RedTeam() {
  const [attacks, setAttacks] = useState<AttackResult[]>([])
  const [adapt, setAdapt] = useState<AdaptResult | null>(null)
  const [busy, setBusy] = useState<'attack' | 'adapt' | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const last = attacks[attacks.length - 1]

  const run = async (kind: 'attack' | 'adapt') => {
    setBusy(kind)
    setErr(null)
    try {
      if (kind === 'attack') {
        const r = await api.attack()
        setAttacks((a) => [...a, r])
      } else {
        setAdapt(await api.adapt())
      }
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setBusy(null)
    }
  }

  return (
    <section className="panel" aria-label="Red team">
      <header>
        <h2>Red team</h2>
        <span className="meta">unseen typology: smurfing</span>
      </header>
      <div className="body stack">
        <p className="muted" style={{ margin: 0 }}>
          Structured transfers just under ₹10,000 routed through aged sleeper accounts. This pattern was held out of training.
        </p>
        <div className="rt-row">
          <button className="btn trip" onClick={() => run('attack')} disabled={busy !== null}>
            {busy === 'attack' ? 'Injecting…' : attacks.length ? 'Attack again' : '1 · Launch attack'}
          </button>
          <button className="btn pass" onClick={() => run('adapt')} disabled={busy !== null || !attacks.length}>
            {busy === 'adapt' ? 'Retraining…' : '2 · Adapt model'}
          </button>
        </div>
        {last && (
          <div className="stack" style={{ gap: 6 }} aria-live="polite">
            <span className="src muted">Attack #{last.attack_id} · {last.injected} payments · {inr(last.amount)} · model v{last.model_version}</span>
            <Bar label="Breaker" rate={last.cb_rate} color="var(--pass)" />
            <Bar label="Rules" rate={last.rules_rate} color="var(--muted)" />
            <span className="muted">Intercepted {last.cb_detected} of {last.injected} (hold or block); {last.nudged} nudged. Rules blocked {last.rules_detected}.</span>
          </div>
        )}
        {adapt && (
          <div className="stack" style={{ gap: 6 }} aria-live="polite">
            <span className="src c-pass">Adapted → model v{adapt.model_version} in {adapt.train_seconds.toFixed(1)} s</span>
            <Bar label="Before" rate={adapt.before.rate} color="var(--trip)" />
            <Bar label="After" rate={adapt.after.rate} color="var(--pass)" />
            <span className="muted">
              Detection on {adapt.after.n} payments from held-out smurfing campaigns, after training on {adapt.labelled_attack_rows} labelled attack payments.
              AUC on typologies 1–4: {adapt.auc_typologies_1_4_before.toFixed(4)} → {adapt.auc_typologies_1_4_after.toFixed(4)}.
            </span>
          </div>
        )}
        {err && <span className="err">{err}</span>}
      </div>
    </section>
  )
}
