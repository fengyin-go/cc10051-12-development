/** 取证申请、明细出包、更正与复算导入的接口封装。 */

const API_BASE = import.meta.env.VITE_API_BASE ?? ''

export function apiUrl(path: string): string {
  return path.startsWith('http') ? path : `${API_BASE}${path}`
}

export type ScoreBox = {
  total?: number
  hits?: number
  score?: string
  score_percent?: number
  评分结果?: string
}

export type RecheckResult = {
  ok?: boolean
  message?: string
  duplicate?: boolean
  idempotent?: boolean
  batch_no?: string
  recheck_no?: string
  复算批次?: string
  report_no?: string
  报告编号?: string
  report_version?: string
  报告版本?: string
  execution_id?: number
  execution_no?: string
  execution_round?: string
  执行轮?: string
  consistent?: boolean
  check_count?: number
  检查数?: number
  total?: number
  hits?: number
  score?: string
  original?: ScoreBox
  原结果?: ScoreBox
  recalculated?: ScoreBox
  重算?: ScoreBox
  batch?: { checks?: ForensicCheck[] } & Record<string, unknown>
  checks?: ForensicCheck[]
}

export type ForensicCheck = {
  check_id?: string
  检查记录编号?: string
  记录编号?: string
  检查维度?: string
  检查值?: string
  value?: string
  hit?: boolean
  是否命中?: string
  recalculated_hit?: boolean
  重算是否命中?: string
}

export type ForensicApplication = {
  id: number
  evidence_no?: string
  取证编号?: string
  report_no?: string
  报告编号?: string
  报告批次?: string
  report_version?: string
  报告版本?: string
  execution_id?: number
  execution_no?: string
  execution_round?: string
  执行轮?: string
  status?: string
  申请状态?: string
  basis_total?: number
  basis_hits?: number
  basis_score?: string
  所依据的报告结果?: string
  download_status?: string
  download_count?: number
  [key: string]: unknown
}

export type ExecutionRow = {
  id: number
  execution_no?: string
  执行批次?: string
  execution_round?: string
  执行轮?: string
  报告编号?: string
  report_no?: string
  检查总数?: number
  命中数?: number
  status?: string
  更正状态?: string
  corrected?: boolean
  规则名称?: string
  检查维度?: string
}

async function parseJsonOrThrow(response: Response): Promise<any> {
  const text = await response.text()
  let data: any = null
  try {
    data = text ? JSON.parse(text) : null
  } catch {
    throw new Error(`服务返回无法解析（HTTP ${response.status}）`)
  }
  if (!response.ok) {
    const message =
      data?.message || data?.detail || `请求被拒绝（HTTP ${response.status}）`
    const error = new Error(message) as Error & { rejected?: boolean; payload?: unknown }
    error.rejected = true
    error.payload = data
    throw error
  }
  // 平台约定：业务拒绝也可能是 HTTP 200 + { ok:false }
  if (data && typeof data === 'object' && data.ok === false) {
    const error = new Error(data.message || '操作被拒绝') as Error & {
      rejected?: boolean
      payload?: unknown
    }
    error.rejected = true
    error.payload = data
    throw error
  }
  return data
}

export async function listApplications(): Promise<ForensicApplication[]> {
  const response = await fetch(apiUrl('/api/forensic/applications'))
  const data = await parseJsonOrThrow(response)
  return (data.items ?? []) as ForensicApplication[]
}

export async function createApplication(values: Record<string, unknown>): Promise<any> {
  const response = await fetch(apiUrl('/api/forensic/applications'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(values),
  })
  return parseJsonOrThrow(response)
}

export async function listExecutions(): Promise<ExecutionRow[]> {
  const response = await fetch(apiUrl('/api/forensic/executions'))
  const data = await parseJsonOrThrow(response)
  return (data.items ?? []) as ExecutionRow[]
}

export async function correctExecution(
  id: number | string,
  payload: Record<string, unknown> = { hits: 2 },
): Promise<any> {
  const response = await fetch(apiUrl(`/api/forensic/executions/${id}/correct`), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return parseJsonOrThrow(response)
}

export async function importForensicPackage(
  packageObject: unknown,
  scope: { reportNo?: string; executionId?: string } = {},
): Promise<RecheckResult> {
  const params = new URLSearchParams()
  if (scope.reportNo) params.set('report_no', scope.reportNo)
  if (scope.executionId) params.set('execution_id', scope.executionId)
  const query = params.toString()
  const response = await fetch(
    apiUrl(`/api/forensic/recheck/import${query ? `?${query}` : ''}`),
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(packageObject),
    },
  )
  return parseJsonOrThrow(response)
}

export function forensicDownloadUrl(idOrNo: number | string): string {
  return apiUrl(`/api/forensic/applications/${idOrNo}/download`)
}

export function summaryDownloadUrl(reportIdOrNo: number | string, version?: string): string {
  const base = apiUrl(`/api/quality_result/${reportIdOrNo}/summary`)
  return version ? `${base}?version=${encodeURIComponent(version)}` : base
}

export function detailsExportUrl(executionIdOrNo: number | string): string {
  return apiUrl(`/api/forensic/executions/${executionIdOrNo}/export`)
}
