export type Identity = { key: string; token: string; label: string }

// Local demo identities issued by the backend when ROOK_DEMO_TOKENS=1 (the default for local runs).
export const IDENTITIES: Identity[] = [
  { key: 'analyst', token: 'demo-analyst-token', label: 'Sam · IT operations' },
  { key: 'approver', token: 'demo-approver-token', label: 'Priya · IT lead (approver)' },
  { key: 'viewer', token: 'demo-viewer-token', label: 'Lee · read only' },
  { key: 'other', token: 'demo-other-org-token', label: 'Eve · a different company' },
]

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) { super(message); this.status = status }
}

export async function api<T = any>(token: string, path: string, body?: unknown): Promise<T> {
  const init: RequestInit = { headers: { Authorization: `Bearer ${token}` }, cache: 'no-store' }
  if (body !== undefined) {
    init.method = 'POST'
    init.headers = { ...init.headers, 'Content-Type': 'application/json' }
    init.body = JSON.stringify(body)
  }
  let r: Response
  try { r = await fetch('/api' + path, init) } catch { throw new ApiError(0, 'Cannot reach the Rook backend.') }
  const text = await r.text()
  let data: any = null
  try { data = text ? JSON.parse(text) : null } catch { data = null }
  if (!r.ok) {
    const d = data?.detail
    throw new ApiError(r.status, typeof d === 'string' ? d : Array.isArray(d) ? 'The request was not valid.' : `Request failed (${r.status})`)
  }
  return data as T
}

// Is the agent reachable? /api/health needs no token, so this also works before sign-in.
// A free host that sleeps when idle answers with a gateway error until it has woken up.
export async function reachable(): Promise<boolean> {
  try {
    const r = await fetch('/api/health', { cache: 'no-store' })
    return r.ok
  } catch {
    return false
  }
}

// Plain-language names for incident and action states.
export const INCIDENT_STATE: Record<string, { label: string; tone: string; text: string }> = {
  investigating: { label: 'Investigating', tone: 'info', text: 'Rook is gathering evidence.' },
  ready: { label: 'Planned', tone: 'info', text: 'Plan ready. Nothing has been changed yet.' },
  awaiting_approval: { label: 'Needs approval', tone: 'warn', text: 'Paused until a person approves a risky step.' },
  remediating: { label: 'Running', tone: 'info', text: 'Rook is making and checking changes.' },
  escalated: { label: 'Escalated', tone: 'bad', text: 'Rook stopped safely and needs a person.' },
  closed_verified: { label: 'Closed · verified', tone: 'ok', text: 'Every closure check passed on live state.' },
  open: { label: 'Open', tone: 'warn', text: 'Not finished.' },
}

export function actionState(a: any): { label: string; tone: string } {
  if (a.status === 'verified' && a.retries > 0) return { label: 'Recovered · verified', tone: 'ok' }
  return ({
    planned: { label: 'Planned', tone: 'mute' },
    authorized: { label: 'Planned', tone: 'info' },
    needs_approval: { label: 'Needs approval', tone: 'warn' },
    blocked: { label: 'Blocked', tone: 'bad' },
    executing: { label: 'Running', tone: 'info' },
    executed: { label: 'Checking', tone: 'info' },
    unknown: { label: 'Outcome unclear', tone: 'warn' },
    retry_pending: { label: 'Will retry', tone: 'warn' },
    verified: { label: 'Verified', tone: 'ok' },
    failed: { label: 'Failed', tone: 'bad' },
  } as Record<string, { label: string; tone: string }>)[a.status] || { label: a.status, tone: 'mute' }
}

export const ACTION_LABEL: Record<string, string> = {
  disable_account: 'Disable account',
  issue_replacement: 'Issue replacement key',
  update_dependent: 'Move service to new key',
  revoke_credential: 'Revoke old key',
  scrub_exposed_secret: 'Remove leaked key from code',
  pause_pipeline: 'Pause auto-deploy',
  rollback_service: 'Roll back to known-good revision',
  resume_pipeline: 'Resume auto-deploy, bad revision blocked',
  resend_referral: 'Send the referral again, on a live channel',
  book_appointment: 'Book the appointment',
  contact_patient: 'Tell the patient',
  notify_clinician: 'Page the clinician',
  resend_prescription: 'Send the prescription to the pharmacy again',
  close_loop: 'Mark the loop closed in the record',
}

// What each playbook is for, in the buyer's words.
export const PLAYBOOK_COPY: Record<string, { button: string; pitch: string }> = {
  offboarding: { button: 'Investigate offboarding', pitch: 'Someone left, but their accounts and API keys live on.' },
  outage: { button: 'Investigate checkout-api alert', pitch: 'A production service started failing right after a deploy.' },
  leak: { button: 'Investigate scanner finding', pitch: 'A scanner found a live API key hardcoded in a repository.' },
  care: { button: 'Sweep the clinic', pitch: 'A referral, a result and a prescription the record calls done. Nobody checked.' },
}

const EVENT_TEXT: Record<string, (d: any) => string> = {
  investigated: () => 'Investigation finished: relationships and findings recorded',
  closure_conditions_defined: (d) => `Defined ${d.conditions?.length ?? ''} closure checks before changing anything`,
  ticket_opened: (d) => `Opened tracking ticket ${d.ticket}`,
  policy_authorized: (d) => `Policy allowed ${d.action} (${d.rule})`,
  policy_needs_approval: (d) => `Policy requires a person to approve ${d.action}`,
  policy_blocked: (d) => `Policy blocked ${d.action}: ${d.reason}`,
  run_requested: (d) => `Run requested by ${d.by}`,
  executing: (d) => `Running ${d.action} (attempt ${d.attempt})`,
  executed: (d) => `Tool reported success for ${d.action}; now checking independently`,
  verification_verified: (d) => `Verified ${d.action} on live state`,
  verification_failed: (d) => `Independent check failed for ${d.action}`,
  verification_unknown: (d) => `Could not verify ${d.action}`,
  transient_failure: (d) => `${d.action} failed: ${d.error}. Saving a checkpoint and inspecting real state`,
  timeout_failure: (d) => `${d.action} timed out. Saving a checkpoint and inspecting real state`,
  reconciled_not_applied: (d) => `Inspected state: ${d.action} did not take effect, so a retry is safe`,
  reconciled_verified: (d) => `Inspected state: ${d.action} had already taken effect, so no retry`,
  reconciled_but_verification_failed: (d) => `${d.action} took effect but failed its checks`,
  reconcile_inconclusive: (d) => `State of ${d.action} could not be determined; stopping`,
  failed_retries_exhausted: (d) => `Gave up on ${d.action} after ${d.attempts} attempts`,
  permanent_failure: (d) => `${d.action} was refused: ${d.error}`,
  checkpoint_restored: (d) => `Resumed from checkpoint #${d.checkpoint}; in-flight: ${(d.in_flight || []).join(', ')}`,
  approval_granted: (d) => `${d.by} approved ${d.action}`,
  approval_rejected: (d) => `${d.by} rejected ${d.action}`,
  approval_rejected_by_policy: (d) => `Approval by ${d.by} refused by policy`,
  policy_recheck_blocked: (d) => `Re-check before running ${d.action} blocked it: ${d.reason}`,
  blocked_by_dependency: (d) => `${d.action} not run: waiting on ${(d.waiting_on || []).join(', ')}`,
  escalated: (d) => `Escalated ${d.action || ''}: ${d.reason || d.status || ''}`,
  incident_closed_verified: () => 'Incident closed: all checks passed',
  incident_escalated: () => 'Incident escalated to a person',
  incident_awaiting_approval: () => 'Paused for approval',
  ticket_updated: (d) => `Ticket ${d.ticket} updated (${d.status})`,
  cancelled: () => 'Run cancelled',
  rolled_back: (d) => `Rolled ${d.target} back to the previous key so it keeps working`,
  ticket_open_failed: () => 'Could not open a tracking ticket (continuing; tracking never blocks the fix)',
  rollback_skipped: (d) => `No rollback for ${d.action}: ${d.reason}`,
  rollback_failed: (d) => `Rollback of ${d.action} failed: ${d.error}`,
  cancel_requested: (d) => `Cancel requested by ${d.by}`,
}

export function eventText(e: any): string {
  const f = EVENT_TEXT[e.event]
  return f ? f(e.data || {}) : e.event.replace(/_/g, ' ')
}

export function eventTone(name: string): string {
  if (/fail|permanent|inconclusive|escalated|blocked|rejected/.test(name)) return 'bad'
  if (/transient|timeout|reconciled_not|restored|needs_approval|awaiting/.test(name)) return 'warn'
  if (/verified|granted|closed|authorized|rolled_back/.test(name)) return 'ok'
  return 'mute'
}

export const time = (ts: number) => new Date(ts * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
