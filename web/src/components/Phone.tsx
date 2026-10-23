import { AnimatePresence, motion, useReducedMotion } from 'framer-motion'
import { useEffect, useState } from 'react'
import { inr, type Copy, type Lang, type Txn } from '../api'
import { Elapsed } from './Rail'

type Answer = null | 'yes' | 'no' | 'cancel' | 'continue'

const LANG_LABEL: Record<Lang, string> = { en: 'EN', ta: 'தமிழ்', hi: 'हिन्दी' }

interface Props {
  txn: Txn | null
  lang: Lang
  setLang: (l: Lang) => void
  copy: Copy | null
  holdMinutes: number
  pendingSince?: number
  onInvestigate: (id: string, lang: Lang) => Promise<void>
}

function fill(s: string, t: Txn, minutes: number) {
  return s.replace('{amount}', Math.round(t.amount).toLocaleString('en-IN')).replace('{payee}', t.receiver_vpa).replace('{minutes}', String(minutes))
}

export function Phone({ txn, lang, setLang, copy, holdMinutes, pendingSince, onInvestigate }: Props) {
  const reduce = useReducedMotion()
  const [answer, setAnswer] = useState<Answer>(null)
  const [remaining, setRemaining] = useState(holdMinutes * 60)
  const [err, setErr] = useState<string | null>(null)
  const id = txn?.txn_id

  useEffect(() => {
    setAnswer(null)
    setErr(null)
    setRemaining(holdMinutes * 60)
  }, [id, holdMinutes])

  useEffect(() => {
    if (txn?.action !== 'hold' || answer) return
    const t = setInterval(() => setRemaining((r) => Math.max(0, r - 1)), 1000)
    return () => clearInterval(t)
  }, [txn?.action, answer, id])

  const c = copy?.[lang]
  const inv = txn?.investigations?.[lang]
  const flagged = txn && (txn.action === 'hold' || txn.action === 'block' || txn.action === 'nudge')

  const askGemma = async () => {
    if (!txn) return
    setErr(null)
    try {
      await onInvestigate(txn.txn_id, lang)
    } catch (e) {
      setErr((e as Error).message)
    }
  }

  const showContact = txn && (txn.action === 'block' || (txn.action === 'hold' && answer === 'yes'))

  return (
    <section className="panel" aria-label="Customer phone view">
      <header>
        <h2>Customer view</h2>
        <div className="seg" role="group" aria-label="Language" style={{ marginLeft: 'auto' }}>
          {(['en', 'ta', 'hi'] as Lang[]).map((l) => (
            <button key={l} className="btn" aria-pressed={lang === l} onClick={() => setLang(l)} lang={l}>{LANG_LABEL[l]}</button>
          ))}
        </div>
      </header>
      <div className="phone-wrap">
        <div className="phone">
          <div className="screen">
            <div className="notch"><i /></div>
            {!txn || !c ? (
              <div className="content lang-en"><div className="empty">Waiting for a payment to show.</div></div>
            ) : (
              <AnimatePresence mode="wait">
                <motion.div
                  key={`${txn.txn_id}-${lang}`}
                  className={`content lang-${lang}`}
                  lang={lang}
                  initial={reduce ? false : { opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0 }}
                  transition={{ duration: 0.2 }}
                >
                  <div className="payto">{c.to}: {txn.receiver_vpa}</div>
                  <div className="big">{inr(txn.amount)}</div>
                  <div className={`alert ${txn.action}`} role={txn.action === 'block' ? 'alert' : 'status'}>
                    <h3>{c[`title_${txn.action}`]}</h3>
                    {fill(c[txn.action], txn, holdMinutes)}
                    {txn.action === 'hold' && !answer && (
                      <div className="countdown" aria-live="off">{String(Math.floor(remaining / 60)).padStart(2, '0')}:{String(remaining % 60).padStart(2, '0')}</div>
                    )}
                  </div>

                  {txn.action === 'nudge' && !answer && (
                    <>
                      <button className="pbtn primary" onClick={() => setAnswer('cancel')}>{c.cancel}</button>
                      <button className="pbtn" onClick={() => setAnswer('continue')}>{c.continue}</button>
                    </>
                  )}
                  {txn.action === 'hold' && !answer && (
                    <>
                      <div>{c.question}</div>
                      <button className="pbtn danger" onClick={() => setAnswer('yes')}>{c.yes}</button>
                      <button className="pbtn" onClick={() => setAnswer('no')}>{c.no}</button>
                    </>
                  )}
                  {answer === 'yes' && <div className="alert block">{c.yes_outcome}</div>}
                  {answer === 'no' && <div className="alert hold">{c.no_outcome}</div>}
                  {answer === 'cancel' && <div className="alert allow">{c.cancelled}</div>}
                  {answer === 'continue' && <div className="alert allow">{c.continued}</div>}

                  {showContact && (
                    <div className="contact">
                      <span className="tag c-trip">{c.simulated}</span> {c.contact}
                    </div>
                  )}

                  {flagged && txn.action !== 'nudge' && (
                    inv ? (
                      <div className="stack" style={{ gap: 4 }}>
                        <div>{inv.customer_message}</div>
                        <div className="gemma-line">
                          {inv.message_source === 'model' ? inv.label : inv.source === 'model' ? `Template message (model reply was not in ${LANG_LABEL[lang]})` : inv.label}
                        </div>
                      </div>
                    ) : (
                      pendingSince ? (
                        <div className="gemma-line">Gemma is writing a message… <Elapsed since={pendingSince} /></div>
                      ) : (
                        <button className="pbtn" onClick={askGemma}>{`Gemma explanation · ${LANG_LABEL[lang]}`}</button>
                      )
                    )
                  )}
                  {err && <div className="err">{err}</div>}
                </motion.div>
              </AnimatePresence>
            )}
          </div>
        </div>
      </div>
    </section>
  )
}
