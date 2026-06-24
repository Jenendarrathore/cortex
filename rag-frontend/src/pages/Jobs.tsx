import { useState } from "react"
import { formatDateTime } from "@/lib/format"
import { useJobs, useJob } from "@/hooks/queries"
import { type Job, type JobStatus, type LogLevel } from "@/lib/api"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { ChevronDown, ChevronRight, Loader2, AlertCircle } from "lucide-react"
import { cn } from "@/lib/utils"

// ── Helpers ───────────────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: JobStatus }) {
  const variants: Record<JobStatus, string> = {
    queued: "bg-yellow-100 text-yellow-800 border-yellow-200",
    running: "bg-blue-100 text-blue-800 border-blue-200",
    done: "bg-green-100 text-green-800 border-green-200",
    failed: "bg-red-100 text-red-800 border-red-200",
  }
  return (
    <span className={cn("inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium", variants[status] ?? "bg-muted text-muted-foreground")}>
      {status === "running" && <Loader2 className="h-3 w-3 animate-spin" />}
      {status}
    </span>
  )
}

function LevelBadge({ level }: { level: LogLevel }) {
  if (level === "error") return <Badge variant="destructive" className="text-[10px]">error</Badge>
  if (level === "warn") return <Badge variant="outline" className="text-[10px] border-yellow-400 text-yellow-700">warn</Badge>
  return <Badge variant="outline" className="text-[10px]">info</Badge>
}

function ProgressBar({ processed, total }: { processed: number; total: number }) {
  const pct = total > 0 ? Math.round((processed / total) * 100) : 0
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 rounded-full bg-muted overflow-hidden min-w-[60px]">
        <div className="h-full rounded-full bg-primary transition-all" style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs text-muted-foreground tabular-nums shrink-0">
        {processed}/{total}
      </span>
    </div>
  )
}

// ── Job Detail (inline expanded row) ─────────────────────────────────────────

function JsonPanel({ label, data }: { label: string; data: unknown }) {
  if (!data || (typeof data === "object" && Object.keys(data as object).length === 0)) return null
  return (
    <div className="space-y-1">
      <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">{label}</p>
      <pre className="text-xs bg-muted rounded-md p-3 overflow-auto max-h-48 font-mono leading-relaxed">
        {JSON.stringify(data, null, 2)}
      </pre>
    </div>
  )
}

function JobDetail({ jobId }: { jobId: string }) {
  const { data: job, isLoading } = useJob(jobId)

  if (isLoading || !job) {
    return (
      <TableRow>
        <TableCell colSpan={7} className="py-4 text-center">
          <Loader2 className="h-4 w-4 animate-spin mx-auto text-muted-foreground" />
        </TableCell>
      </TableRow>
    )
  }

  return (
    <TableRow>
      <TableCell colSpan={7} className="p-0 bg-muted/20">
        <div className="px-6 py-4 space-y-4">
          {/* Error banner */}
          {job.error && (
            <div className="flex items-start gap-2 rounded-md bg-destructive/10 border border-destructive/20 px-3 py-2 text-sm text-destructive">
              <AlertCircle className="h-4 w-4 mt-0.5 shrink-0" />
              {job.error}
            </div>
          )}

          {/* Payload + Result panels */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <JsonPanel label="Payload" data={job.payload} />
            <JsonPanel label="Result" data={job.result} />
          </div>

          {/* Logs table */}
          {job.logs.length > 0 ? (
            <div className="rounded-md border overflow-hidden">
              <div className="max-h-72 overflow-y-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="w-16">Level</TableHead>
                      <TableHead>Message</TableHead>
                      <TableHead className="hidden md:table-cell w-48">File</TableHead>
                      <TableHead className="w-36 text-right">Time</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {job.logs.map((log) => (
                      <TableRow
                        key={log.id}
                        className={log.level === "error" ? "bg-destructive/5" : undefined}
                      >
                        <TableCell className="py-1.5"><LevelBadge level={log.level} /></TableCell>
                        <TableCell className="py-1.5 text-xs">{log.message}</TableCell>
                        <TableCell className="py-1.5 hidden md:table-cell">
                          <span className="text-xs font-mono text-muted-foreground truncate block max-w-[180px]">
                            {log.file ?? "—"}
                          </span>
                        </TableCell>
                        <TableCell className="py-1.5 text-right text-xs text-muted-foreground tabular-nums">
                          {log.created_at ? formatDateTime(log.created_at) : "—"}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            </div>
          ) : (
            <p className="text-xs text-muted-foreground py-2">No log entries yet.</p>
          )}
        </div>
      </TableCell>
    </TableRow>
  )
}

// ── Jobs List ─────────────────────────────────────────────────────────────────

function JobRow({ job, expanded, onToggle }: { job: Job; expanded: boolean; onToggle: () => void }) {
  return (
    <>
      <TableRow
        className="cursor-pointer hover:bg-muted/50"
        onClick={onToggle}
      >
        <TableCell className="w-8 pl-4">
          {expanded
            ? <ChevronDown className="h-4 w-4 text-muted-foreground" />
            : <ChevronRight className="h-4 w-4 text-muted-foreground" />
          }
        </TableCell>
        <TableCell>
          <Badge variant="outline" className="capitalize text-xs">{job.kind}</Badge>
        </TableCell>
        <TableCell><StatusBadge status={job.status} /></TableCell>
        <TableCell>
          <ProgressBar processed={job.processed} total={job.total} />
        </TableCell>
        <TableCell className="text-xs tabular-nums">
          <span className="text-green-700">{job.added}↑</span>
          {" "}
          <span className="text-blue-700">{job.updated}~</span>
          {" "}
          <span className="text-muted-foreground">{job.skipped}–</span>
          {job.errors > 0 && <span className="text-destructive"> {job.errors}!</span>}
        </TableCell>
        <TableCell className="text-xs text-muted-foreground tabular-nums">
          {job.created_at ? formatDateTime(job.created_at) : "—"}
        </TableCell>
        <TableCell className="text-xs text-muted-foreground tabular-nums">
          {job.updated_at ? formatDateTime(job.updated_at) : "—"}
        </TableCell>
      </TableRow>
      {expanded && <JobDetail jobId={job.id} />}
    </>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function Jobs({ highlightId }: { highlightId?: string }) {
  const { data: jobs = [], isLoading, error } = useJobs()
  const [expandedId, setExpandedId] = useState<string | null>(highlightId ?? null)

  function toggleJob(id: string) {
    setExpandedId((prev) => (prev === id ? null : id))
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Ingestion Jobs</CardTitle>
        <CardDescription>
          Background jobs processing uploaded documents, folders, and text.
          {jobs.some((j) => j.status === "queued" || j.status === "running") && (
            <span className="ml-2 inline-flex items-center gap-1 text-xs text-blue-600">
              <Loader2 className="h-3 w-3 animate-spin" />
              Refreshing…
            </span>
          )}
        </CardDescription>
      </CardHeader>
      <CardContent>
        {isLoading && (
          <div className="py-12 flex justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
          </div>
        )}

        {error && (
          <div className="flex items-center gap-2 rounded-md bg-destructive/10 border border-destructive/20 px-4 py-3 text-sm text-destructive">
            <AlertCircle className="h-4 w-4 shrink-0" />
            {error instanceof Error ? error.message : "Failed to load jobs"}
          </div>
        )}

        {!isLoading && !error && jobs.length === 0 && (
          <p className="py-12 text-center text-sm text-muted-foreground">
            No jobs yet — ingest a file, folder, or text to get started.
          </p>
        )}

        {jobs.length > 0 && (
          <div className="rounded-md border overflow-hidden">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-8 pl-4" />
                  <TableHead>Kind</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Progress</TableHead>
                  <TableHead>Results</TableHead>
                  <TableHead>Created</TableHead>
                  <TableHead>Updated</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {jobs.map((job) => (
                  <JobRow
                    key={job.id}
                    job={job}
                    expanded={expandedId === job.id}
                    onToggle={() => toggleJob(job.id)}
                  />
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
