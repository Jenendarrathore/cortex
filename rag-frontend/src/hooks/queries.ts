import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { api, ACTIVE_JOB_STATUSES, type IngestTextPayload } from "@/lib/api"

const ACTIVE_STATUSES = new Set<string>(ACTIVE_JOB_STATUSES)

export const PAGE_SIZE = 20

/** Backend reachability — polled for the live connection indicator. */
export function useHealth() {
  return useQuery({
    queryKey: ["health"],
    queryFn: () => api.health(),
    refetchInterval: 15_000,
    retry: false,
    staleTime: 10_000,
  })
}

/** Paginated documents. Fetches PAGE_SIZE+1 to detect whether a next page exists. */
export function useDocuments(page: number) {
  const query = useQuery({
    queryKey: ["documents", page],
    queryFn: () => api.listDocuments(page * PAGE_SIZE, PAGE_SIZE + 1),
  })
  const all = query.data ?? []
  return {
    ...query,
    docs: all.slice(0, PAGE_SIZE),
    hasMore: all.length > PAGE_SIZE,
  }
}

export function useDocument(id: string | null) {
  return useQuery({
    queryKey: ["document", id],
    queryFn: () => api.getDocument(id as string),
    enabled: !!id,
  })
}

export function useDeleteDocument() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.deleteDocument(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["documents"] }),
  })
}

export function useSearch() {
  return useMutation({
    mutationFn: (vars: { query: string; topK: number; filters?: Record<string, unknown> }) =>
      api.search(vars.query, vars.topK, vars.filters),
  })
}

export function useIngestText() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (payload: IngestTextPayload) => api.ingestText(payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["jobs"] }),
  })
}

export function useUploadFile() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (file: File) => api.uploadDocument(file),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["jobs"] }),
  })
}

export function useIngestFolder() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (folderPath: string) => api.ingestFolder(folderPath),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["jobs"] }),
  })
}

/** Jobs list — auto-refetches every 2s while any job is active. */
export function useJobs() {
  return useQuery({
    queryKey: ["jobs"],
    queryFn: () => api.listJobs(),
    refetchInterval: (query) => {
      const data = query.state.data
      return Array.isArray(data) && data.some((j) => ACTIVE_STATUSES.has(j.status)) ? 2000 : false
    },
  })
}

export function useJob(id: string | null) {
  return useQuery({
    queryKey: ["job", id],
    queryFn: () => api.getJob(id as string),
    enabled: !!id,
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status && ACTIVE_STATUSES.has(status) ? 1500 : false
    },
  })
}

export function useJobLogs(id: string | null) {
  return useQuery({
    queryKey: ["job-logs", id],
    queryFn: () => api.getJobLogs(id as string),
    enabled: !!id,
  })
}
