import { AnimatePresence, motion, useReducedMotion } from 'framer-motion'
import { useCallback, useEffect, useRef, useState } from 'react'
import { api, type Copy, type Health, type Investigation, type Lang, type LlmStatus, type Metrics, type Txn } from './api'
import { Graph } from './components/Graph'
import { Phone } from './components/Phone'
import { Rail } from './components/Rail'
import { RedTeam } from './components/RedTeam'
import { Scan } from './components/Scan'
import { Scoreboard } from './components/Scoreboard'

type Tab = 'stream' | 'graph' | 'phone' | 'score'
const RAIL_SIZE = 40

export default function App() {
  const reduce = useReducedMotion()
  const [health, setHealth] = useState<Health | null>(null)
  const [copy, setCopy] = useState<{ copy: Copy; hold_minutes: number } | null>(null)
  const [metrics, setMetrics] = useState<Metrics | null>(null)
  const [txns, setTxns] = useState<Txn[]>([])
  const [selected, setSelected] = useState<Txn | null>(null)
  const [pinned, setPinned] = useState(false)
  const [lang, setLangState] = useState<Lang>('en')
  const [tab, setTab] = useState<Tab>('stream')
  const [connected, setConnected] = useState(false)
  const [tripSignal, setTripSignal] = useState(0)
  const [flash, setFlash] = useState(0)
  const [llm, setLlm] = useState<LlmStatus | null>(null)
  const [pending, setPending] = useState<Record<string, number>>({})
  const [safe, setSafe] = useState<{ enabled: boolean; cached_results: number }>({ enabled: false, cached_results: 0 })
  const lastTrip = useRef(0)
  const pinnedRef = useRef(pinned)
  pinnedRef.current = pinned
  const [frozen, setFrozen] = useState(false)
  const frozenRef = useRef(false)
  const onFreeze = useCallback((f: boolean) => {
    frozenRef.current = f
    setFrozen(f)
  }, [])

  useEffect(() => {
    api.health().then((h) => { setHealth(h); setLlm(h.llm); setSafe({ enabled: h.safe_mode, cached_results: h.cached_results }) }).catch(() => setHealth(null))
    api.copy().then(setCopy).catch(() => setCopy(null))
  }, [])

  const applyInvestigation = useCallback((id: string, l: Lang, inv: Investigation) => {
    const patch = (t: Txn) => (t.txn_id === id ? { ...t, investigations: { ...t.investigations, [l]: inv } } : t)
    setTxns((list) => list.map(patch))
    setSelected((s) => (s ? patch(s) : s))
    setPending((p) => {
      const next = { ...p }
      delete next[`${id}|${l}`]
      return next
    })
  }, [])

  const requestInvestigation = useCallback(async (id: string, l: Lang) => {
    const reply = await api.investigate(id, l)
    if (reply.status === 'done') applyInvestigation(id, l, reply.result)
    else setPending((p) => ({ ...p, [`${id}|${l}`]: reply.since * 1000 }))
  }, [applyInvestigation])

  useEffect(() => {
    let ws: WebSocket | null = null
    let retry: number | undefined
    let closed = false
    const connect = () => {
      ws = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws`)
      ws.onopen = () => setConnected(true)
      ws.onclose = () => {
        setConnected(false)
        if (!closed) retry = window.setTimeout(connect, 1000)
      }
      ws.onmessage = (ev) => {
        const msg = JSON.parse(ev.data)
        if (msg.metrics) setMetrics(msg.metrics)
        if (msg.type === 'batch') {
          const batch: Txn[] = msg.txns
          if (!batch.length) return
          if (frozenRef.current) return
          setTxns((list) => [...batch.slice().reverse(), ...list].slice(0, RAIL_SIZE))
          const flagged = batch.filter((t) => t.action === 'hold' || t.action === 'block')
          if (flagged.length && !pinnedRef.current) setSelected(flagged[flagged.length - 1])
          if (batch.some((t) => t.action === 'block') && Date.now() - lastTrip.current > 1500) {
            lastTrip.current = Date.now()
            setTripSignal((n) => n + 1)
            setFlash((n) => n + 1)
          }
        } else if (msg.type === 'investigation') {
          applyInvestigation(msg.txn_id, msg.lang, msg.result)
          if (msg.status) setLlm(msg.status)
        } else if (msg.type === 'llm_status') {
          setLlm(msg.status)
        } else if (msg.type === 'safe_mode') {
          setSafe({ enabled: msg.enabled, cached_results: msg.cached_results })
        }
      }
    }
    connect()
    return () => {
      closed = true
      window.clearTimeout(retry)
      ws?.close()
    }
  }, [applyInvestigation])

  const setLang = (l: Lang) => {
    setLangState(l)
    api.setLang(l).catch(() => undefined)
  }

  const control = async (action: string, speed?: number) => {
    await api.control(action, speed)
    if (action === 'reset') {
      setTxns([])
      setSelected(null)
      setPinned(false)
    }
    setMetrics(await fetch('/api/metrics').then((r) => r.json()))
  }

  const select = (t: Txn) => {
    setSelected(t)
    setPinned(true)
  }

  const stream = metrics?.stream
  const item = {
    hidden: { opacity: 0, y: reduce ? 0 : 18 },
    show: { opacity: 1, y: 0, transition: { duration: 0.5, ease: 'easeOut' as const } },
  }

  return (
    <div className="app">
      <div className="atmos" aria-hidden="true" />
      <AnimatePresence>
        {flash > 0 && !reduce && (
          <motion.div key={flash} className="flash" initial={{ opacity: 1 }} animate={{ opacity: 0 }} transition={{ duration: 0.5 }} aria-hidden="true" />
        )}
      </AnimatePresence>

      <motion.header className="top" initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.4 }}>
        <div className="brand">
          <h1>Circuit<span>/</span>Breaker</h1>
          <small>UPI fraud protection</small>
        </div>
        <div className="lamps" aria-live="polite">
          <span className={`lamp ${connected && stream?.running ? 'on' : 'amber'}`}><i />
            {connected ? (stream?.running ? 'live' : 'paused') : 'connecting'} <b>{stream?.clock ?? '—'}</b>
          </span>
          <span className={`lamp ${llm?.state === 'ready' ? 'on' : 'amber'}`} title="Investigator provider, model, mode and last latency"><i />
            gemma <b>{!llm ? '—' : llm.state === 'loading' ? 'loading…' : llm.provider
              ? `${llm.model} · ${llm.provider}${llm.mode ? ` · ${llm.mode.replace('_', ' ')}` : ''}${llm.last_latency_ms != null ? ` · ${(llm.last_latency_ms / 1000).toFixed(1)} s` : ''} · ${llm.state}`
              : 'offline · templates'}</b>
          </span>
          {stream && <span className="lamp"><i />replay <b>{stream.cursor.toLocaleString('en-IN')} / {stream.total.toLocaleString('en-IN')}</b></span>}
        </div>
        <div className="controls">
          <button className="btn" onClick={() => control(stream?.running ? 'pause' : 'resume')} disabled={!stream}>
            {stream?.running ? 'Pause' : 'Resume'}
          </button>
          <div className="seg" role="group" aria-label="Replay speed">
            {[1, 4, 16].map((s) => (
              <button key={s} className="btn" aria-pressed={stream?.speed === s} onClick={() => control('speed', s)}>{s}×</button>
            ))}
          </div>
          <button className="btn" onClick={() => control('reset')}>Reset</button>
          <button
            className="btn"
            aria-pressed={safe.enabled}
            title="Replays cached real model outputs (labels kept) and never waits on the model. Payments without a cached output get the labelled template."
            onClick={() => api.safeMode(!safe.enabled).then(setSafe).catch(() => undefined)}
          >
            Safe mode {safe.enabled ? `on · ${safe.cached_results} cached` : 'off'}
          </button>
          {pinned && <button className="btn" onClick={() => setPinned(false)}>Follow live</button>}
        </div>
      </motion.header>

      <motion.main
        className="grid"
        initial="hidden"
        animate="show"
        variants={{ hidden: {}, show: { transition: { staggerChildren: reduce ? 0 : 0.12, delayChildren: 0.1 } } }}
      >
        <motion.div variants={item} className={`col ${tab === 'stream' ? 'active' : ''}`} id="panel-stream" role="tabpanel">
          <Rail txns={txns} selectedId={selected?.txn_id ?? null} onSelect={select} lang={lang} tripSignal={tripSignal} frozen={frozen} onFreeze={onFreeze} pending={pending} onInvestigate={requestInvestigation} />
        </motion.div>
        <motion.div variants={item} className={`col center ${tab === 'graph' || tab === 'score' ? 'active' : ''}`} data-tab={tab}>
          <div className={`slot slot-graph ${tab === 'score' ? 'hide-mobile' : ''}`}>
            <Graph txn={selected} />
          </div>
          <div className={tab === 'graph' ? 'hide-mobile' : ''}>
            <Scoreboard m={metrics} rules={health?.rules ?? null} />
          </div>
        </motion.div>
        <motion.div variants={item} className={`col scroll ${tab === 'phone' || tab === 'score' ? 'active' : ''}`} data-tab={tab}>
          <div className={tab === 'score' ? 'hide-mobile' : ''}>
            <Phone txn={selected} lang={lang} setLang={setLang} copy={copy?.copy ?? null} holdMinutes={copy?.hold_minutes ?? 30} pendingSince={selected ? pending[`${selected.txn_id}|${lang}`] : undefined} onInvestigate={requestInvestigation} />
          </div>
          <div className={tab === 'phone' ? 'hide-mobile' : ''}>
            <RedTeam />
          </div>
          <div className={tab === 'phone' ? 'hide-mobile' : ''}>
            <Scan lang={lang} llmAvailable={llm?.state === 'ready'} />
          </div>
        </motion.div>
      </motion.main>

      <footer className="foot">
        All transactions, accounts and VPAs are synthetic (seed {health?.seed ?? 42}); no real customer data is used. Trusted-contact alerts are simulated. Metrics are computed live from the replayed stream.
      </footer>

      <nav className="tabs" role="tablist" aria-label="Sections">
        {(['stream', 'graph', 'phone', 'score'] as Tab[]).map((t) => (
          <button key={t} role="tab" aria-selected={tab === t} onClick={() => setTab(t)}>{t}</button>
        ))}
      </nav>
    </div>
  )
}
