import { AnimatePresence, motion, useAnimationControls, useReducedMotion } from 'framer-motion'
import { useEffect, useState } from 'react'
import { inr, shortVpa, type Lang, type Txn } from '../api'

interface Props {
  txns: Txn[]
  selectedId: string | null
  onSelect: (t: Txn) => void
  lang: Lang
  tripSignal: number
  frozen: boolean
  onFreeze: (frozen: boolean) => void
  pending: Record<string, number>
  onInvestigate: (id: string, lang: Lang) => Promise<void>
}

const ACTION_LABEL = { allow: 'Pass', nudge: 'Nudge', hold: 'Hold', block: 'Trip' } as const

export function Rail({ txns, selectedId, onSelect, lang, tripSignal, frozen, onFreeze, pending, onInvestigate }: Props) {
  const reduce = useReducedMotion()
  const lever = useAnimationControls()
  const panel = useAnimationControls()
  const [expanded, setExpanded] = useState<string | null>(null)
  const [hovering, setHovering] = useState(false)

  useEffect(() => {
    onFreeze(hovering || expanded !== null)
  }, [hovering, expanded, onFreeze])

  useEffect(() => {
    if (!tripSignal || reduce) return
    lever.start({ rotate: [0, 0, 180], backgroundColor: ['#8cff9e', '#ff4d2e', '#ff4d2e'], transition: { duration: 0.28, times: [0, 0.2, 1], ease: 'easeIn' } })
      .then(() => lever.start({ rotate: 0, backgroundColor: '#8cff9e', transition: { delay: 0.9, duration: 0.4 } }))
    panel.start({ x: [0, -5, 5, -3, 2, 0], transition: { duration: 0.32 } })
  }, [tripSignal, reduce, lever, panel])

  return (
    <motion.section className="panel rail" animate={panel} aria-label="Live transaction rail">
      <header>
        <div className="rail-head">
          <div className="mainbreaker" aria-hidden="true">
            <motion.div className="lever" animate={lever} />
          </div>
          <h2>Live rail</h2>
        </div>
        <span className="meta">
          {frozen ? (
            <>
              <span className="c-warn">frozen while you inspect</span>
              {expanded && <button className="btn" style={{ marginLeft: 8, minHeight: 26, padding: '2px 8px' }} onClick={() => setExpanded(null)}>Unfreeze</button>}
            </>
          ) : 'newest first · tap a row'}
        </span>
      </header>
      <div className="rail-cols" aria-hidden="true">
        <span>Time</span><span>Payer → Payee</span><span style={{ textAlign: 'right' }}>Amount</span><span /><span>Action</span>
      </div>
      <ul className="rail-list" onMouseEnter={() => setHovering(true)} onMouseLeave={() => setHovering(false)}>
        <AnimatePresence initial={false}>
          {txns.map((t) => (
            <Row
              key={t.txn_id}
              t={t}
              selected={t.txn_id === selectedId}
              open={expanded === t.txn_id}
              reduce={!!reduce}
              lang={lang}
              onToggle={() => {
                onSelect(t)
                setExpanded(expanded === t.txn_id ? null : t.txn_id)
              }}
              pendingSince={pending[`${t.txn_id}|${lang}`] ?? pending[`${t.txn_id}|en`]}
              onInvestigate={onInvestigate}
            />
          ))}
        </AnimatePresence>
      </ul>
    </motion.section>
  )
}

function Row({ t, selected, open, reduce, lang, onToggle, pendingSince, onInvestigate }: {
  t: Txn; selected: boolean; open: boolean; reduce: boolean; lang: Lang
  onToggle: () => void; pendingSince?: number; onInvestigate: Props['onInvestigate']
}) {
  const flagged = t.action !== 'allow'
  return (
    <motion.li
      layout={!reduce}
      className={`row ${t.action}${selected ? ' sel' : ''}`}
      initial={reduce ? false : { opacity: 0, x: -40 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.35, ease: 'easeOut' }}
    >
      <button className="row-main" onClick={onToggle} aria-expanded={open} aria-label={`${t.action} ${inr(t.amount)} from ${t.sender_vpa} to ${t.receiver_vpa}, risk ${t.risk.toFixed(2)}`}>
        <span className="time">{t.clock.slice(-5)}</span>
        <span className="who">
          {shortVpa(t.sender_vpa)} <em>→</em> {shortVpa(t.receiver_vpa)}
          {t.injected && <span className="inj">RED-TEAM</span>}
        </span>
        <span className="amt">{inr(t.amount)}</span>
        <span className="switch" aria-hidden="true">
          <motion.i
            initial={reduce ? false : { rotate: 0 }}
            animate={{ rotate: t.action === 'block' ? 180 : t.action === 'hold' ? 90 : t.action === 'nudge' ? 30 : 0 }}
            transition={{ delay: reduce ? 0 : 0.25, type: 'spring', stiffness: 700, damping: 18 }}
          />
        </span>
        <span className={`badge ${t.action}`}>{ACTION_LABEL[t.action]}</span>
      </button>
      <span className="riskbar" style={{ width: `${Math.max(2, t.risk * 100)}%` }} aria-hidden="true" />
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            className="detail"
            initial={reduce ? false : { height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
          >
            <Detail t={t} flagged={flagged} lang={lang} pendingSince={pendingSince} onInvestigate={onInvestigate} />
          </motion.div>
        )}
      </AnimatePresence>
    </motion.li>
  )
}

export function Elapsed({ since }: { since: number }) {
  const [now, setNow] = useState(Date.now())
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [])
  return <>{Math.max(0, Math.round((now - since) / 1000))} s</>
}

function Detail({ t, flagged, lang, pendingSince, onInvestigate }: {
  t: Txn; flagged: boolean; lang: Lang; pendingSince?: number; onInvestigate: Props['onInvestigate']
}) {
  const [err, setErr] = useState<string | null>(null)
  const inv = t.investigations?.[lang] ?? t.investigations?.en
  const max = Math.max(...t.factors.map((f) => f.contribution), 0.01)

  const ask = async () => {
    setErr(null)
    try {
      await onInvestigate(t.txn_id, lang)
    } catch (e) {
      setErr((e as Error).message)
    }
  }

  return (
    <>
      <div className="kv">
        <span>risk <b>{t.risk.toFixed(3)}</b></span>
        <span>scored in <b>{t.cb_ms.toFixed(2)} ms</b></span>
        <span>model <b>v{t.model_version}</b></span>
        <span>rules engine <b className={t.rules_blocked ? 'c-trip' : ''}>{t.rules_blocked ? 'block' : 'pass'}</b></span>
      </div>
      {t.factors.length > 0 ? (
        <div className="stack" style={{ gap: 6 }}>
          <span className="src muted">Top risk factors (XGBoost contributions, log-odds)</span>
          {t.factors.map((f) => (
            <div className="factor" key={f.feature}>
              <span>{f.label}</span>
              <span className="bar"><b style={{ width: `${(100 * f.contribution) / max}%` }} /></span>
              <span className="v">+{f.contribution.toFixed(2)}</span>
            </div>
          ))}
        </div>
      ) : (
        <span className="muted">No factor pushed risk up for this payment.</span>
      )}
      {t.rules_fired.length > 0 && <span className="muted">Rules fired: {t.rules_fired.join('; ')}</span>}
      {flagged && (inv ? (
        <div className={`note ${inv.source}`}>
          <span className={`src ${inv.source === 'model' ? 'c-pass' : 'c-warn'}`}>
            {inv.label}
            {inv.source === 'model' ? ` · ${(inv.latency_ms / 1000).toFixed(1)} s` : inv.error ? ` · ${inv.error}` : ''}
          </span>
          <p><b>Verdict: {inv.verdict}</b> — {inv.reason}</p>
          <p className="muted">Analyst: {inv.analyst_note}</p>
          {inv.tool_calls.length > 0 && <p className="muted">Tools: {inv.tool_calls.map((c) => c.name).join(', ')}</p>}
        </div>
      ) : (
        pendingSince ? (
          <span className="c-warn" aria-live="polite">Investigating with Gemma… <Elapsed since={pendingSince} /></span>
        ) : (
          <button className="btn" onClick={ask}>Investigate with Gemma</button>
        )
      ))}
      {err && <span className="err">{err}</span>}
      <span className="muted">
        Synthetic ground truth: <b className={t.is_fraud ? 'c-trip' : 'c-pass'}>{t.is_fraud ? `fraud · ${t.typology.replace('_', ' ')}` : 'legitimate'}</b>
      </span>
    </>
  )
}
