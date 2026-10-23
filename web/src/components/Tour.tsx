import { useEffect } from 'react'

export interface TourStepView {
  title: string
  caption: string
}

interface Props {
  side: 'left' | 'right'
  step: TourStepView
  index: number
  total: number
  status: string | null
  onNext: () => void
  onExit: () => void
}

export function Tour({ side, step, index, total, status, onNext, onExit }: Props) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null
      if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA')) return
      if (e.key === ' ' || e.key === 'ArrowRight') {
        e.preventDefault()
        e.stopPropagation()
        onNext()
      } else if (e.key === 'Escape') {
        e.preventDefault()
        onExit()
      }
    }
    window.addEventListener('keydown', onKey, true)
    return () => window.removeEventListener('keydown', onKey, true)
  }, [onNext, onExit])

  const last = index === total - 1
  return (
    <div className={`tour ${side}`} role="dialog" aria-modal="false" aria-labelledby="tour-title" aria-describedby="tour-caption">
      <div className="tour-meta">
        <span className="tag c-warn">Demo tour {index + 1} / {total}</span>
        <span className="muted">Space: next · Esc: exit</span>
      </div>
      <h2 id="tour-title">{step.title}</h2>
      <p id="tour-caption" aria-live="polite">{step.caption}</p>
      {status && <p className="tour-status" aria-live="polite">{status}</p>}
      <div className="tour-actions">
        <button className="btn" onClick={onExit}>Exit</button>
        <button className="btn pass" onClick={last ? onExit : onNext} autoFocus>{last ? 'Finish' : 'Next'}</button>
      </div>
    </div>
  )
}
