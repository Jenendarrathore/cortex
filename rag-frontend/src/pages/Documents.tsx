import { useState } from "react"
import { Link } from "react-router-dom"
import { Trash2, RefreshCw, ChevronLeft, ChevronRight, Database, Upload } from "lucide-react"
import { toast } from "sonner"
import { type Document } from "@/lib/api"
import { useDocuments, useDeleteDocument } from "@/hooks/queries"
import { formatDate } from "@/lib/format"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import DocumentDetailDialog from "@/components/DocumentDetailDialog"

export default function Documents() {
  const [page, setPage] = useState(0)
  const [selectedDocId, setSelectedDocId] = useState<string | null>(null)

  const { docs, hasMore, isPending, isError, error, refetch, isFetching } = useDocuments(page)
  const del = useDeleteDocument()

  async function handleDelete(doc: Document) {
    const label = doc.title ?? doc.id
    if (!window.confirm(`Delete "${label}"? This cannot be undone.`)) return
    try {
      await del.mutateAsync(doc.id)
      toast.success(`Deleted "${label}"`)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Delete failed")
    }
  }

  return (
    <>
      <Card>
        <CardHeader className="flex flex-row items-start justify-between gap-4">
          <div>
            <CardTitle>Documents</CardTitle>
            <CardDescription>
              {isPending
                ? "Loading..."
                : `${docs.length} document${docs.length !== 1 ? "s" : ""} on this page`}
            </CardDescription>
          </div>
          <Button variant="outline" size="sm" onClick={() => void refetch()} disabled={isFetching}>
            <RefreshCw className={`h-4 w-4 ${isFetching ? "animate-spin" : ""}`} />
            Refresh
          </Button>
        </CardHeader>
        <CardContent>
          {isError && (
            <div className="rounded-md bg-destructive/10 border border-destructive/20 text-destructive px-4 py-3 text-sm mb-4">
              {error instanceof Error ? error.message : "Failed to load documents"}
            </div>
          )}

          {!isPending && !isError && docs.length === 0 && (
            <div className="rounded-xl border border-dashed bg-muted/30 px-6 py-14 text-center">
              <span className="mx-auto mb-3 grid h-12 w-12 place-items-center rounded-xl bg-accent text-accent-foreground">
                <Database className="h-5 w-5" />
              </span>
              <p className="text-sm font-medium text-foreground">No documents yet</p>
              <p className="mt-1 text-sm text-muted-foreground">
                Add files, folders, or pasted text to start building your knowledge base.
              </p>
              <Button asChild className="mt-5">
                <Link to="/ingest">
                  <Upload className="h-4 w-4" />
                  Ingest content
                </Link>
              </Button>
            </div>
          )}

          {!isPending && docs.length > 0 && (
            <>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Title / Path</TableHead>
                  <TableHead>Category</TableHead>
                  <TableHead>Tags</TableHead>
                  <TableHead>Date</TableHead>
                  <TableHead>Updated</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {docs.map((doc) => (
                  <TableRow key={doc.id}>
                    <TableCell className="max-w-xs">
                      <button
                        className="text-left hover:underline focus:outline-none"
                        onClick={() => setSelectedDocId(doc.id)}
                      >
                        <div className="font-medium truncate">{doc.title ?? doc.file_path}</div>
                        {doc.title && (
                          <div className="text-xs text-muted-foreground truncate">{doc.file_path}</div>
                        )}
                        {doc.author && (
                          <div className="text-xs text-muted-foreground">by {doc.author}</div>
                        )}
                      </button>
                    </TableCell>
                    <TableCell>
                      {doc.category ? (
                        <Badge variant="secondary">{doc.category}</Badge>
                      ) : (
                        <span className="text-muted-foreground text-xs">—</span>
                      )}
                    </TableCell>
                    <TableCell>
                      <div className="flex flex-wrap gap-1">
                        {doc.tags && doc.tags.length > 0
                          ? doc.tags.map((tag) => (
                              <Badge key={tag} variant="outline" className="text-xs">
                                {tag}
                              </Badge>
                            ))
                          : <span className="text-muted-foreground text-xs">—</span>}
                      </div>
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground whitespace-nowrap">
                      {formatDate(doc.doc_date)}
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground whitespace-nowrap">
                      {formatDate(doc.updated_at)}
                    </TableCell>
                    <TableCell className="text-right">
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => void handleDelete(doc)}
                        disabled={del.isPending && del.variables === doc.id}
                        className="text-muted-foreground hover:text-destructive"
                      >
                        <Trash2 className="h-4 w-4" />
                        <span className="sr-only">Delete</span>
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            {(page > 0 || hasMore) && (
              <div className="flex items-center justify-between pt-4 border-t">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setPage((p) => Math.max(0, p - 1))}
                  disabled={page === 0 || isFetching}
                >
                  <ChevronLeft className="h-4 w-4" />
                  Previous
                </Button>
                <span className="text-xs text-muted-foreground">Page {page + 1}</span>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setPage((p) => p + 1)}
                  disabled={!hasMore || isFetching}
                >
                  Next
                  <ChevronRight className="h-4 w-4" />
                </Button>
              </div>
            )}
            </>
          )}
        </CardContent>
      </Card>

      <DocumentDetailDialog
        docId={selectedDocId}
        onClose={() => setSelectedDocId(null)}
      />
    </>
  )
}
