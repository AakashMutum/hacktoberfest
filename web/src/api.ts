export type Action = 'allow' | 'nudge' | 'hold' | 'block'
export type Lang = 'en' | 'ta' | 'hi'

export interface Factor {
  feature: string
  label: string
  value: number
  contribution: number
}

export interface Investigation {
  verdict: Action
  reason: string
  customer_message: string
  analyst_note: string
  source: 'model' | 'fallback'
  provider: string | null
  model: string | null
  mode: 'function_calling' | 'context_injection' | null
  label: string
  message_source: 'model' | 'template'
  latency_ms: number
  replayed?: boolean
  mode_note?: string | null
  tool_calls: { name: string; args: Record<string, unknown> }[]
  error: string | null
}

export interface LlmStatus {
  provider: string | null
  model: string | null
  mode: string | null
  state: 'ready' | 'loading' | 'offline' | 'slow' | 'busy' | 'error'
  error?: string | null
  last_latency_ms: number | null
}

export type InvestigationReply = { status: 'done'; result: Investigation } | { status: 'pending'; since: number }

export interface Txn {
  txn_id: string
  ts: number
  clock: string
  sender_vpa: string
  receiver_vpa: string
  amount: number
  hour: number
  new_payee: number
  new_device: number
  risk: number
  action: Action
  band: string
  factors: Factor[]
  rules_blocked: boolean
  rules_fired: string[]
  tight_blocked: boolean
  tight_fired: string[]
  cb_ms: number
  rules_ms: number
  is_fraud: boolean
  typology: string
  injected: boolean
  attack_id: number | null
  model_version: number
  investigations?: Partial<Record<Lang, Investigation>>
}

export interface SystemStats {
  seen: number
  fraud_seen: number
  fraud_caught: number
  fraud_amount: number
  rupees_saved: number
  legit_blocked: number
  legit_held: number
  legit_nudged: number
  p50_ms: number
  p95_ms: number
}

export interface Metrics {
  circuit_breaker: SystemStats
  rules_engine: SystemStats
  rules_tight: SystemStats
  stream: { cursor: number; total: number; running: boolean; speed: number; clock: string; pending_injected: number }
  model: { version: number; trained_on: number; base_auc_typologies_1_4: number; features: number }
}

export interface Health {
  llm: LlmStatus
  llm_available: boolean
  safe_mode: boolean
  cached_results: number
  rules: { simple: string[]; tight: string[] }
  seed: number
  thresholds: Record<string, number>
  hold_minutes: number
}

export interface GraphNode {
  id: number
  vpa: string
  depth: number
  merchant: boolean
  pass_through: number
  fan_in: number
  age_days: number
  suspect: boolean
  role: '' | 'payer' | 'payee'
}

export interface GraphEdge {
  source: number
  target: number
  amount: number
  count: number
}

export interface EgoGraph {
  txn_id: string
  center: number
  payer: number
  nodes: GraphNode[]
  edges: GraphEdge[]
  suspect_count: number
}

export interface AttackResult {
  attack_id: number
  injected: number
  amount: number
  model_version: number
  cb_detected: number
  cb_rate: number
  rules_detected: number
  rules_rate: number
  tight_detected: number
  tight_rate: number
  nudged: number
}

export interface DetectStats {
  n: number
  detected: number
  rate: number
  rules_detected: number
  rules_rate: number
  tight_detected: number
  tight_rate: number
}

export interface AdaptResult {
  before: DetectStats
  after: DetectStats
  labelled_attack_rows: number
  train_rows: number
  train_seconds: number
  total_seconds: number
  auc_typologies_1_4_before: number
  auc_typologies_1_4_after: number
  model_version: number
  eval_note: string
}

export interface ScanResult {
  payee: string | null
  amount: number | null
  urgency: 'low' | 'medium' | 'high'
  pressure_cues: string[]
  scam_signals: string[]
  risk_contribution: number
  summary: string
  model: string
  provider: string
  label: string
  latency_ms: number
}

export type Copy = Record<Lang, Record<string, string>>

export const SERVER_DOWN = 'The Circuit Breaker server is not reachable. It may be restarting; try again in a moment.'

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  let r: Response
  try {
    r = await fetch(path, { ...init, signal: init?.signal ?? AbortSignal.timeout(90_000) })
  } catch {
    throw new Error(SERVER_DOWN)
  }
  if (!r.ok) {
    let detail = r.status >= 500 && r.status !== 503 && r.status !== 504 ? 'The server hit an error. Try again.' : r.statusText
    try {
      const body = await r.json()
      if (typeof body.detail === 'string') detail = body.detail
    } catch {
      /* body was not JSON */
    }
    throw new Error(detail)
  }
  return r.json() as Promise<T>
}

const post = { method: 'POST' }
const postJson = (body: unknown) => ({ method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })

export const api = {
  health: () => req<Health>('/api/health'),
  copy: () => req<{ copy: Copy; hold_minutes: number }>('/api/copy'),
  control: (action: string, speed?: number) => req('/api/stream/control', postJson({ action, speed })),
  safeMode: (enabled: boolean) => req<{ enabled: boolean; cached_results: number }>('/api/safe-mode', postJson({ enabled })),
  setLang: (lang: Lang) => req(`/api/lang/${lang}`, post),
  investigate: (id: string, lang: Lang) => req<InvestigationReply>(`/api/investigate/${id}?lang=${lang}`, post),
  graph: (id: string) => req<EgoGraph>(`/api/graph/${id}`),
  attack: () => req<AttackResult>('/api/redteam/attack', post),
  adapt: () => req<AdaptResult>('/api/redteam/adapt', post),
  scan: (file: File, lang: Lang) => {
    const fd = new FormData()
    fd.append('file', file)
    fd.append('lang', lang)
    return req<ScanResult>('/api/scan-screenshot', { method: 'POST', body: fd })
  },
}

export const inr = (n: number) => '₹' + Math.round(n).toLocaleString('en-IN')
export const inrShort = (n: number) => {
  if (n >= 1e7) return `₹${(n / 1e7).toFixed(2)} Cr`
  if (n >= 1e5) return `₹${(n / 1e5).toFixed(2)} L`
  return inr(n)
}
export const pct = (a: number, b: number) => (b ? `${((100 * a) / b).toFixed(1)}%` : '—')
export const shortVpa = (v: string) => (v.length > 22 ? v.slice(0, 20) + '…' : v)
