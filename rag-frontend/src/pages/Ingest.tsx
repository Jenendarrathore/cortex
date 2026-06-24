import { useRef, useState } from "react"
import { useNavigate } from "react-router-dom"
import { Upload, FileText, Folder, Loader2 } from "lucide-react"
import { toast } from "sonner"
import { type IngestTextPayload } from "@/lib/api"
import { useIngestText, useUploadFile, useIngestFolder } from "@/hooks/queries"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { Label } from "@/components/ui/label"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"

// ── Upload Tab ────────────────────────────────────────────────────────────────

function UploadTab() {
  const navigate = useNavigate()
  const [file, setFile] = useState<File | null>(null)
  const [dragging, setDragging] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  const upload = useUploadFile()
  const loading = upload.isPending

  function handleFile(f: File | null) {
    if (!f) return
    setFile(f)
  }

  function onDrop(e: React.DragEvent) {
    e.preventDefault()
    setDragging(false)
    handleFile(e.dataTransfer.files[0] ?? null)
  }

  async function handleUpload() {
    if (!file) return
    try {
      const res = await upload.mutateAsync(file)
      toast.success(`Job queued — processing ${file.name}`)
      setFile(null)
      if (inputRef.current) inputRef.current.value = ""
      navigate(`/jobs?highlight=${res.job_id}`)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Upload failed")
    }
  }

  return (
    <div className="space-y-4">
      <div
        className={`border-2 border-dashed rounded-lg p-10 text-center cursor-pointer transition-colors ${
          dragging ? "border-primary bg-primary/5" : "border-input hover:border-primary/50"
        }`}
        onClick={() => inputRef.current?.click()}
        onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
      >
        <Upload className="mx-auto h-8 w-8 text-muted-foreground mb-3" />
        {file ? (
          <div className="flex items-center justify-center gap-2 text-sm">
            <FileText className="h-4 w-4 text-primary" />
            <span className="font-medium">{file.name}</span>
            <span className="text-muted-foreground">({(file.size / 1024).toFixed(1)} KB)</span>
          </div>
        ) : (
          <>
            <p className="text-sm font-medium">Drop a file here or click to browse</p>
            <p className="text-xs text-muted-foreground mt-1">Markdown (.md) and plain text (.txt) supported</p>
          </>
        )}
        <input
          ref={inputRef}
          type="file"
          accept=".md,.txt"
          className="hidden"
          onChange={(e) => handleFile(e.target.files?.[0] ?? null)}
        />
      </div>

      <Button
        onClick={() => void handleUpload()}
        disabled={!file || loading}
        className="w-full"
      >
        {loading && <Loader2 className="h-4 w-4 animate-spin" />}
        {loading ? "Queuing..." : "Upload Document"}
      </Button>
    </div>
  )
}

// ── Folder Tab ────────────────────────────────────────────────────────────────

function FolderTab() {
  const navigate = useNavigate()
  const [folderPath, setFolderPath] = useState("")

  const ingestFolder = useIngestFolder()
  const loading = ingestFolder.isPending

  async function handleSubmit() {
    if (!folderPath.trim()) return
    try {
      const res = await ingestFolder.mutateAsync(folderPath.trim())
      toast.success(`Folder job queued — ${folderPath}`)
      setFolderPath("")
      navigate(`/jobs?highlight=${res.job_id}`)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to queue folder job")
    }
  }

  return (
    <div className="space-y-4">
      <div className="space-y-1.5">
        <Label htmlFor="folder-path">Server-side folder path</Label>
        <div className="flex gap-2">
          <div className="relative flex-1">
            <Folder className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <Input
              id="folder-path"
              className="pl-9"
              placeholder="/absolute/path/to/docs"
              value={folderPath}
              onChange={(e) => setFolderPath(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && void handleSubmit()}
            />
          </div>
          <Button onClick={() => void handleSubmit()} disabled={loading || !folderPath.trim()}>
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Folder className="h-4 w-4" />}
            {loading ? "Queuing..." : "Ingest Folder"}
          </Button>
        </div>
        <p className="text-xs text-muted-foreground">
          Recursively ingests .md and .txt files. Job runs in the background — track progress in the Jobs tab.
        </p>
      </div>
    </div>
  )
}

// ── Text Tab ──────────────────────────────────────────────────────────────────

interface TextForm {
  title: string
  author: string
  category: string
  tags: string
  date: string
  source_url: string
  content: string
}

const emptyForm: TextForm = {
  title: "",
  author: "",
  category: "",
  tags: "",
  date: "",
  source_url: "",
  content: "",
}

function TextTab() {
  const navigate = useNavigate()
  const [form, setForm] = useState<TextForm>(emptyForm)

  const ingest = useIngestText()
  const loading = ingest.isPending

  function set(field: keyof TextForm) {
    return (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
      setForm((prev) => ({ ...prev, [field]: e.target.value }))
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!form.content.trim()) {
      toast.error("Content is required")
      return
    }
    try {
      const payload: IngestTextPayload = {
        content: form.content,
        ...(form.title && { title: form.title }),
        ...(form.author && { author: form.author }),
        ...(form.category && { category: form.category }),
        ...(form.tags && {
          tags: form.tags.split(",").map((t) => t.trim()).filter(Boolean),
        }),
        ...(form.date && { date: form.date }),
        ...(form.source_url && { source_url: form.source_url }),
      }
      const res = await ingest.mutateAsync(payload)
      toast.success(`Job queued — processing ${form.title || "document"}`)
      setForm(emptyForm)
      navigate(`/jobs?highlight=${res.job_id}`)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Ingest failed")
    }
  }

  return (
    <form onSubmit={(e) => void handleSubmit(e)} className="space-y-4">
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div className="space-y-1.5">
          <Label htmlFor="title">Title</Label>
          <Input
            id="title"
            placeholder="My Document"
            value={form.title}
            onChange={set("title")}
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="author">Author</Label>
          <Input
            id="author"
            placeholder="Jane Doe"
            value={form.author}
            onChange={set("author")}
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="category">Category</Label>
          <Input
            id="category"
            placeholder="Engineering"
            value={form.category}
            onChange={set("category")}
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="tags">Tags (comma-separated)</Label>
          <Input
            id="tags"
            placeholder="rag, llm, docs"
            value={form.tags}
            onChange={set("tags")}
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="date">Date</Label>
          <Input
            id="date"
            type="date"
            value={form.date}
            onChange={set("date")}
          />
        </div>
        <div className="space-y-1.5 sm:col-span-2">
          <Label htmlFor="source_url">Source URL</Label>
          <Input
            id="source_url"
            type="url"
            placeholder="https://example.com/doc"
            value={form.source_url}
            onChange={set("source_url")}
          />
        </div>
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="content">
          Content <span className="text-destructive">*</span>
        </Label>
        <Textarea
          id="content"
          placeholder="Paste markdown content..."
          value={form.content}
          onChange={set("content")}
          className="min-h-[240px] font-mono text-xs"
          required
        />
      </div>

      <Button type="submit" disabled={loading} className="w-full">
        {loading && <Loader2 className="h-4 w-4 animate-spin" />}
        {loading ? "Queuing..." : "Ingest Text"}
      </Button>
    </form>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function Ingest() {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Ingest Content</CardTitle>
        <CardDescription>
          Add documents to the knowledge base. Jobs run in the background — track progress in the Jobs tab.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <Tabs defaultValue="upload">
          <TabsList className="mb-6">
            <TabsTrigger value="upload">Upload File</TabsTrigger>
            <TabsTrigger value="folder">Folder</TabsTrigger>
            <TabsTrigger value="text">Paste Text</TabsTrigger>
          </TabsList>
          <TabsContent value="upload">
            <UploadTab />
          </TabsContent>
          <TabsContent value="folder">
            <FolderTab />
          </TabsContent>
          <TabsContent value="text">
            <TextTab />
          </TabsContent>
        </Tabs>
      </CardContent>
    </Card>
  )
}
