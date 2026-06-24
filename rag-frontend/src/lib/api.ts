// Single source of truth for the backend base URL + auth header.
export const API_BASE = import.meta.env.VITE_API_URL ?? "http://localhost:8002"
const API_KEY = import.meta.env.VITE_API_KEY ?? ""

/** Auth headers shared by request() and the SSE stream helper. */
export function authHeaders(): Record<string, string> {
  return API_KEY ? { "X-API-Key": API_KEY } : {}
}

export function apiUrl(path: string): string {
  return `${API_BASE}${path}`
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {
    ...authHeaders(),
    ...(init?.headers as Record<string, string> | undefined),
  }

  const res = await fetch(apiUrl(path), { ...init, headers })
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText)
    throw new Error(text || res.statusText)
  }
  return res.json() as Promise<T>
}

export interface Document {
  id: string
  file_path: string
  title: string | null
  author: string | null
  category: string | null
  tags: string[] | null
  doc_date: string | null
  updated_at: string | null
}

export interface ChunkInfo {
  id: string
  chunk_index: number
  heading: string | null
  content: string
  token_count: number | null
}

export interface DocumentDetail extends Document {
  file_hash: string
  source_url: string | null
  created_at: string | null
  raw_content: string | null
  chunks: ChunkInfo[]
}

export interface IngestTextPayload {
  content: string
  file_path?: string
  title?: string
  author?: string
  category?: string
  tags?: string[]
  date?: string
  source_url?: string
}

export interface SearchResult {
  id: string
  content: string
  heading: string | null
  document_id: string
  title: string | null
  source_url: string | null
  file_path: string | null
  tags: string[] | null
  category: string | null
  rerank_score: number | null
}

export interface EnqueueResponse {
  job_id: string
  status: string
}

export interface Job {
  id: string
  kind: string
  status: string
  total: number
  processed: number
  added: number
  updated: number
  skipped: number
  errors: number
  error: string | null
  payload: Record<string, unknown>
  result: Record<string, unknown> | null
  created_at: string | null
  updated_at: string | null
}

export interface JobLog {
  id: string
  job_id: string
  level: string
  message: string
  file: string | null
  created_at: string | null
}

export interface JobDetail extends Job {
  logs: JobLog[]
}

export const api = {
  health: () => request<{ status: string }>("/health"),
  listDocuments: (skip = 0, limit = 20) => request<Document[]>(`/documents/?skip=${skip}&limit=${limit}`),
  getDocument: (id: string) => request<DocumentDetail>(`/documents/${id}`),
  deleteDocument: (id: string) => request<{ status: string }>(`/documents/${id}`, { method: "DELETE" }),
  uploadDocument: (file: File) => {
    const fd = new FormData()
    fd.append("file", file)
    return request<EnqueueResponse>("/documents/upload", { method: "POST", body: fd })
  },
  ingestText: (payload: IngestTextPayload) => request<EnqueueResponse>("/documents/text", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  }),
  ingestFolder: (folderPath: string) => {
    const fd = new FormData()
    fd.append("folder_path", folderPath)
    return request<EnqueueResponse>("/documents/folder", { method: "POST", body: fd })
  },
  search: (query: string, top_k = 5, filters?: Record<string, unknown>) =>
    request<{ query: string; results: SearchResult[] }>("/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, top_k, rerank: true, filters }),
    }),
  listJobs: (skip = 0, limit = 50) => request<Job[]>(`/jobs/?skip=${skip}&limit=${limit}`),
  getJob: (id: string) => request<JobDetail>(`/jobs/${id}`),
  getJobLogs: (id: string) => request<JobLog[]>(`/jobs/${id}/logs`),
}
