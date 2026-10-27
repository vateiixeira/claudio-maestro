export type WorkStatus = 'backlog' | 'ready' | 'active' | 'waiting' | 'blocked' | 'review' | 'done' | 'cancelled'
export interface WorkItem { id: number; project_id: number; parent_id: number | null; source: string; source_instance: string; source_project: string; external_id: string; source_revision: string | null; title: string; priority: string; status: WorkStatus; phase: string; revision: number; created_at: number; updated_at: number }
export interface WorkAttempt { id: number; work_item_id: number; session_id: string | null; role: string; state: string; work_revision: number; result_kind: string | null; created_at: number; updated_at: number; ended_at: number | null; result: Record<string, unknown> | null }
export interface WorkDecision { id: number; revision: number; status: string; work_item_id: number; attempt_id: number; request: { question: string; action: string; options?: unknown[]; evidence?: unknown; scope?: unknown }; answer?: unknown }
export interface WorkDetail { item: WorkItem; dossier: { objective?: string; acceptance?: string; unavailable?: boolean; reason?: string }; attempts: WorkAttempt[]; events: WorkEvent[]; events_page?: WorkEventCursor; dependencies: number[]; reviews?: Record<string, unknown>[]; pull_requests?: WorkPrPage; decisions?: WorkDecision[] }
export interface WorkIdentity { work_role: string; project_id: number; work_item_id: number | null; work_attempt_id: number | null }
export interface WorkPage { items: WorkItem[]; total: number; limit: number; offset: number }
export interface WorkFilter { project_id?: number; status?: string; source?: string; limit?: number; offset?: number }
export interface WorkMode { enabled: boolean; paused: boolean; deleting?: boolean; fence_id?: string; reason?: string }
export interface WorkNotice { id: number; project_id: number; work_item_id: number; attempt_id: number | null; summary: string; kind: string; dispatch_state: string; created_at: number; seen_at: number | null }
export const workStatus: Record<string, string> = { backlog: 'Planejada', ready: 'Pronta', active: 'Em andamento', waiting: 'Aguardando', blocked: 'Bloqueada', review: 'Em revisão', done: 'Concluída', cancelled: 'Cancelada', reserved: 'Reservada', running: 'Em execução', uncertain: 'Envio incerto', queued: 'Na fila', starting: 'Iniciando', dispatching: 'Enviando', succeeded: 'Encerrada', completed: 'Encerrada', failed: 'Falhou', sent: 'Enviada', unsent: 'Não enviada', accepted: 'Aceita', investigator: 'Investigador', implementer: 'Implementador', reviewer: 'Revisor', coordinator: 'CTO' }
export const label = (value: string) => workStatus[value] ?? value
export const activeAttempt = (a: WorkAttempt) => !a.ended_at && ['starting', 'dispatching', 'running', 'waiting', 'uncertain'].includes(a.state)

export interface WorkPr { url: string; origin_attempt_id: number; last_attempt_id: number; origin_session_id: string; last_session_id: string; created_at: number; polled_at: number | null; closed: boolean; head_sha: string | null; comments: { queued: number; dispatching: number; delivered: number; uncertain: number }; latest_feedback_attempt_id: number | null }
export interface WorkPrPage { items: WorkPr[]; total: number; limit: number }

export interface WorkEvent { id: number; kind: string; actor: string; created_at: number; data: Record<string, unknown> }
export interface WorkEventCursor { before: number | null; has_more: boolean; limit: number }
export interface WorkEventPage extends WorkEventCursor { items: WorkEvent[] }
