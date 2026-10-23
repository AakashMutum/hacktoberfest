import { useEffect, useRef, useState } from 'react'
import { useReducedMotion } from 'framer-motion'
import { api, inr, shortVpa, type EgoGraph, type GraphNode, type Txn } from '../api'

interface SimNode extends GraphNode { x: number; y: number; vx: number; vy: number }

const COLORS = { trip: '#ff4d2e', warn: '#ffb020', pass: '#8cff9e', paper: '#efe9df', muted: '#8f877b', line: '#2a2622' }

function seeded(id: number) {
  const s = Math.sin(id * 9301 + 49297) * 233280
  return s - Math.floor(s)
}

function layoutStep(nodes: SimNode[], edges: EgoGraph['edges'], byId: Map<number, SimNode>, w: number, h: number, alpha: number) {
  for (let i = 0; i < nodes.length; i++) {
    for (let j = i + 1; j < nodes.length; j++) {
      const a = nodes[i], b = nodes[j]
      let dx = a.x - b.x, dy = a.y - b.y
      const d2 = Math.max(dx * dx + dy * dy, 25)
      const f = (2600 / d2) * alpha
      const d = Math.sqrt(d2)
      dx /= d; dy /= d
      a.vx += dx * f; a.vy += dy * f; b.vx -= dx * f; b.vy -= dy * f
    }
  }
  for (const e of edges) {
    const a = byId.get(e.source), b = byId.get(e.target)
    if (!a || !b) continue
    const dx = b.x - a.x, dy = b.y - a.y
    const d = Math.sqrt(dx * dx + dy * dy) || 1
    const f = (d - 90) * 0.02 * alpha
    a.vx += (dx / d) * f; a.vy += (dy / d) * f; b.vx -= (dx / d) * f; b.vy -= (dy / d) * f
  }
  for (const n of nodes) {
    n.vx += (w / 2 - n.x) * 0.004 * alpha
    n.vy += (h / 2 - n.y) * 0.004 * alpha
    if (n.role === 'payee') { n.vx += (w / 2 - n.x) * 0.05; n.vy += (h / 2 - n.y) * 0.05 }
    n.vx *= 0.82; n.vy *= 0.82
    n.x = Math.min(w - 20, Math.max(20, n.x + n.vx))
    n.y = Math.min(h - 20, Math.max(20, n.y + n.vy))
  }
}

export function Graph({ txn }: { txn: Txn | null }) {
  const reduce = useReducedMotion()
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const wrapRef = useRef<HTMLDivElement>(null)
  const simRef = useRef<{ nodes: SimNode[]; byId: Map<number, SimNode>; g: EgoGraph } | null>(null)
  const [graph, setGraph] = useState<EgoGraph | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [hover, setHover] = useState<{ n: SimNode; x: number; y: number } | null>(null)
  const txnId = txn?.txn_id

  useEffect(() => {
    if (!txnId) return
    let live = true
    setErr(null)
    api.graph(txnId).then((g) => live && setGraph(g)).catch((e) => live && setErr((e as Error).message))
    return () => { live = false }
  }, [txnId])

  useEffect(() => {
    const canvas = canvasRef.current, wrap = wrapRef.current
    if (!graph || !canvas || !wrap) return
    const dpr = window.devicePixelRatio || 1
    let w = wrap.clientWidth, h = wrap.clientHeight
    const resize = () => {
      w = wrap.clientWidth; h = wrap.clientHeight
      canvas.width = w * dpr; canvas.height = h * dpr
    }
    resize()
    const nodes: SimNode[] = graph.nodes.map((n) => {
      const ang = seeded(n.id) * Math.PI * 2
      const r = n.role === 'payee' ? 0 : 60 + n.depth * 60
      return { ...n, x: w / 2 + Math.cos(ang) * r, y: h / 2 + Math.sin(ang) * r, vx: 0, vy: 0 }
    })
    const byId = new Map(nodes.map((n) => [n.id, n]))
    simRef.current = { nodes, byId, g: graph }
    const maxAmt = Math.max(...graph.edges.map((e) => e.amount), 1)
    const ctx = canvas.getContext('2d')!

    const draw = () => {
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      ctx.clearRect(0, 0, w, h)
      for (const e of graph.edges) {
        const a = byId.get(e.source), b = byId.get(e.target)
        if (!a || !b) continue
        const hot = (a.suspect || a.role === 'payer') && (b.suspect || b.role === 'payee')
        const isTxn = a.role === 'payer' && b.role === 'payee'
        ctx.strokeStyle = isTxn ? COLORS.warn : hot ? 'rgba(255,77,46,0.75)' : 'rgba(143,135,123,0.35)'
        ctx.lineWidth = 0.6 + 3 * Math.sqrt(e.amount / maxAmt)
        ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke()
        const ang = Math.atan2(b.y - a.y, b.x - a.x)
        const tx = b.x - Math.cos(ang) * 10, ty = b.y - Math.sin(ang) * 10
        ctx.fillStyle = ctx.strokeStyle
        ctx.beginPath()
        ctx.moveTo(tx, ty)
        ctx.lineTo(tx - Math.cos(ang - 0.4) * 7, ty - Math.sin(ang - 0.4) * 7)
        ctx.lineTo(tx - Math.cos(ang + 0.4) * 7, ty - Math.sin(ang + 0.4) * 7)
        ctx.fill()
      }
      ctx.font = '11px "IBM Plex Mono", monospace'
      for (const n of nodes) {
        const r = n.role === 'payee' ? 9 : n.role === 'payer' ? 7 : n.suspect ? 6 : 4
        ctx.fillStyle = n.role === 'payer' ? COLORS.warn : n.suspect ? COLORS.trip : n.merchant ? COLORS.muted : COLORS.paper
        if (n.suspect || n.role) { ctx.shadowColor = ctx.fillStyle; ctx.shadowBlur = 10 }
        ctx.beginPath(); ctx.arc(n.x, n.y, r, 0, Math.PI * 2); ctx.fill()
        ctx.shadowBlur = 0
        if (n.role === 'payee') { ctx.strokeStyle = COLORS.paper; ctx.lineWidth = 1.5; ctx.beginPath(); ctx.arc(n.x, n.y, r + 4, 0, Math.PI * 2); ctx.stroke() }
        if (n.role) {
          ctx.fillStyle = COLORS.paper
          ctx.fillText(`${n.role.toUpperCase()} ${shortVpa(n.vpa)}`, n.x + 12, n.y + 4)
        }
      }
    }

    let frame = 0, raf = 0
    if (reduce) {
      for (let i = 0; i < 260; i++) layoutStep(nodes, graph.edges, byId, w, h, 1 - i / 300)
      draw()
    } else {
      const tick = () => {
        layoutStep(nodes, graph.edges, byId, w, h, Math.max(0.05, 1 - frame / 220))
        draw()
        if (++frame < 260) raf = requestAnimationFrame(tick)
      }
      tick()
    }
    const ro = new ResizeObserver(() => { resize(); draw() })
    ro.observe(wrap)
    return () => { cancelAnimationFrame(raf); ro.disconnect() }
  }, [graph, reduce])

  const onMove = (ev: React.MouseEvent) => {
    const sim = simRef.current, canvas = canvasRef.current
    if (!sim || !canvas) return
    const rect = canvas.getBoundingClientRect()
    const x = ev.clientX - rect.left, y = ev.clientY - rect.top
    let best: SimNode | null = null, bd = 196
    for (const n of sim.nodes) {
      const d = (n.x - x) ** 2 + (n.y - y) ** 2
      if (d < bd) { bd = d; best = n }
    }
    setHover(best ? { n: best, x, y } : null)
  }

  const g = graph
  return (
    <section className="panel graph" aria-label="Payment network graph">
      <header>
        <h2>Mule-ring graph</h2>
        <span className="meta">
          {txn ? `${txn.txn_id} · payee neighbourhood${g ? ` · ${g.nodes.length} accounts · ${g.suspect_count} pass-through suspects` : ''}` : 'select a flagged payment'}
        </span>
      </header>
      <div className="canvas-wrap" ref={wrapRef}>
        {!txn && <div className="empty">Flagged payments appear on the rail. Select one to trace where the money goes.</div>}
        {err && <div className="empty err">{err}</div>}
        {txn && (
          <canvas
            ref={canvasRef}
            role="img"
            aria-label={g ? `Network around ${txn.receiver_vpa}: ${g.nodes.length} accounts, ${g.suspect_count} with pass-through above 50 percent` : 'Loading network'}
            onMouseMove={onMove}
            onMouseLeave={() => setHover(null)}
          />
        )}
        {hover && (
          <div className="tip" style={{ left: Math.min(hover.x + 12, (wrapRef.current?.clientWidth ?? 300) - 250), top: hover.y + 12 }}>
            <b>{hover.n.vpa}</b><br />
            {hover.n.merchant ? 'merchant' : `account age ${hover.n.age_days} d`}<br />
            distinct senders {hover.n.fan_in} · pass-through {(hover.n.pass_through * 100).toFixed(0)}%
          </div>
        )}
      </div>
      <div className="legend">
        <span><i style={{ background: COLORS.warn }} />payer</span>
        <span><i style={{ background: COLORS.paper, outline: '1.5px solid #efe9df', outlineOffset: 2 }} />payee</span>
        <span><i style={{ background: COLORS.trip }} />pass-through ≥ 50% (forwards what it receives)</span>
        <span><i style={{ background: COLORS.muted }} />merchant</span>
        {txn && <span>this payment: {inr(txn.amount)}</span>}
      </div>
    </section>
  )
}
