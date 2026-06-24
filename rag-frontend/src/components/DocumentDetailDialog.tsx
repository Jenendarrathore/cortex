import { FileText, Hash, Tag, Calendar, User, Link, Layers } from "lucide-react"
import { useDocument } from "@/hooks/queries"
import { formatDateTime } from "@/lib/format"
import { Badge } from "@/components/ui/badge"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"

interface Props {
  docId: string | null
  onClose: () => void
}

function MetaRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[140px_1fr] gap-2 py-2 border-b last:border-0">
      <span className="text-sm text-muted-foreground">{label}</span>
      <span className="text-sm break-all">{value ?? <span className="text-muted-foreground">—</span>}</span>
    </div>
  )
}

export default function DocumentDetailDialog({ docId, onClose }: Props) {
  const { data: doc, isFetching, isError, error } = useDocument(docId)
  const loading = isFetching && !doc

  return (
    <Dialog open={!!docId} onOpenChange={(open) => { if (!open) onClose() }}>
      <DialogContent className="max-w-4xl max-h-[90vh] flex flex-col overflow-hidden">
        <DialogHeader className="shrink-0">
          <DialogTitle className="flex items-center gap-2">
            <FileText className="h-5 w-5 text-muted-foreground" />
            {loading ? "Loading…" : (doc?.title ?? doc?.file_path ?? "Document")}
          </DialogTitle>
        </DialogHeader>

        {isError && (
          <div className="rounded-md bg-destructive/10 border border-destructive/20 text-destructive px-4 py-3 text-sm">
            {error instanceof Error ? error.message : "Failed to load"}
          </div>
        )}

        {loading && (
          <div className="flex-1 flex items-center justify-center text-muted-foreground text-sm">
            Loading…
          </div>
        )}

        {!loading && doc && (
          <Tabs defaultValue="overview" className="flex-1 flex flex-col overflow-hidden">
            <TabsList className="shrink-0 w-fit">
              <TabsTrigger value="overview">Overview</TabsTrigger>
              <TabsTrigger value="content">
                Content {doc.raw_content ? `(${doc.raw_content.length} chars)` : ""}
              </TabsTrigger>
              <TabsTrigger value="chunks">
                Chunks ({doc.chunks.length})
              </TabsTrigger>
            </TabsList>

            {/* Overview tab */}
            <TabsContent value="overview" className="flex-1 overflow-auto mt-4">
              <div className="space-y-0 rounded-md border px-4">
                <MetaRow label="File path" value={<code className="text-xs bg-muted px-1 py-0.5 rounded">{doc.file_path}</code>} />
                <MetaRow label="Title" value={doc.title} />
                <MetaRow label="Author" value={doc.author ? (
                  <span className="flex items-center gap-1"><User className="h-3 w-3" />{doc.author}</span>
                ) : null} />
                <MetaRow label="Category" value={doc.category ? <Badge variant="secondary">{doc.category}</Badge> : null} />
                <MetaRow label="Tags" value={doc.tags && doc.tags.length > 0 ? (
                  <div className="flex flex-wrap gap-1">
                    {doc.tags.map((t) => (
                      <Badge key={t} variant="outline" className="text-xs">
                        <Tag className="h-3 w-3 mr-1" />{t}
                      </Badge>
                    ))}
                  </div>
                ) : null} />
                <MetaRow label="Doc date" value={doc.doc_date ? (
                  <span className="flex items-center gap-1"><Calendar className="h-3 w-3" />{doc.doc_date}</span>
                ) : null} />
                <MetaRow label="Source URL" value={doc.source_url ? (
                  <a href={doc.source_url} target="_blank" rel="noreferrer" className="flex items-center gap-1 text-blue-600 hover:underline">
                    <Link className="h-3 w-3" />{doc.source_url}
                  </a>
                ) : null} />
                <MetaRow label="Created" value={formatDateTime(doc.created_at)} />
                <MetaRow label="Updated" value={formatDateTime(doc.updated_at)} />
                <MetaRow label="File hash" value={<code className="text-xs text-muted-foreground">{doc.file_hash}</code>} />
                <MetaRow label="Chunks" value={
                  <span className="flex items-center gap-1"><Layers className="h-3 w-3" />{doc.chunks.length} chunks</span>
                } />
                <MetaRow label="Total tokens" value={
                  doc.chunks.reduce((sum, c) => sum + (c.token_count ?? 0), 0) + " tokens"
                } />
              </div>
            </TabsContent>

            {/* Content tab */}
            <TabsContent value="content" className="flex-1 overflow-auto mt-4">
              {doc.raw_content ? (
                <pre className="text-sm whitespace-pre-wrap break-words bg-muted rounded-md p-4 leading-relaxed font-mono overflow-auto max-h-[55vh]">
                  {doc.raw_content}
                </pre>
              ) : (
                <p className="text-muted-foreground text-sm">No content stored.</p>
              )}
            </TabsContent>

            {/* Chunks tab */}
            <TabsContent value="chunks" className="flex-1 overflow-auto mt-4">
              {doc.chunks.length === 0 ? (
                <p className="text-muted-foreground text-sm">No chunks found.</p>
              ) : (
                <div className="space-y-3 max-h-[55vh] overflow-auto pr-1">
                  {doc.chunks
                    .sort((a, b) => a.chunk_index - b.chunk_index)
                    .map((chunk) => (
                      <div key={chunk.id} className="rounded-md border p-3 space-y-1">
                        <div className="flex items-center justify-between gap-2">
                          <div className="flex items-center gap-2">
                            <span className="text-xs font-mono text-muted-foreground bg-muted px-1.5 py-0.5 rounded">
                              #{chunk.chunk_index}
                            </span>
                            {chunk.heading && (
                              <span className="text-sm font-medium">{chunk.heading}</span>
                            )}
                          </div>
                          {chunk.token_count != null && (
                            <span className="flex items-center gap-1 text-xs text-muted-foreground shrink-0">
                              <Hash className="h-3 w-3" />{chunk.token_count} tokens
                            </span>
                          )}
                        </div>
                        <p className="text-sm text-muted-foreground whitespace-pre-wrap leading-relaxed">
                          {chunk.content}
                        </p>
                      </div>
                    ))}
                </div>
              )}
            </TabsContent>
          </Tabs>
        )}
      </DialogContent>
    </Dialog>
  )
}
