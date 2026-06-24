import { useState } from "react"
import { Search as SearchIcon, Loader2, ChevronDown, ChevronUp, ExternalLink, FileText } from "lucide-react"
import { toast } from "sonner"
import { type SearchResult } from "@/lib/api"
import { useSearch } from "@/hooks/queries"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"

const SAMPLE_QUERIES = [
  "How does authentication work?",
  "deployment steps",
  "rate limiting policy",
  "database schema overview",
]

function ScoreBadge({ score }: { score: number }) {
  // Rerank scores are roughly 0..1; clamp for the bar width.
  const pct = Math.max(0, Math.min(1, score)) * 100
  return (
    <div className="flex shrink-0 flex-col items-end gap-1" title={`Rerank score: ${score.toFixed(4)}`}>
      <span className="font-mono text-xs font-semibold text-foreground">{score.toFixed(3)}</span>
      <div className="h-1.5 w-16 overflow-hidden rounded-full bg-muted">
        <div className="h-full rounded-full brand-gradient" style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}

function ResultCard({ result, rank }: { result: SearchResult; rank: number }) {
  const [expanded, setExpanded] = useState(false)
  const content = result.content
  const truncated = content.length > 300 && !expanded

  return (
    <div className="group relative rounded-xl border bg-card p-4 pl-12 shadow-soft transition-shadow hover:shadow-card space-y-2">
      <span className="absolute left-3 top-4 grid h-6 w-6 place-items-center rounded-md bg-accent text-[11px] font-bold text-accent-foreground">
        {rank}
      </span>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="font-medium text-sm leading-tight">
            {result.title ?? "Untitled"}
            {result.heading && (
              <>
                <span className="text-muted-foreground font-normal"> › </span>
                {result.heading}
              </>
            )}
          </p>
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 mt-1">
            {result.file_path && (
              <span className="flex items-center gap-1 text-xs text-muted-foreground">
                <FileText className="h-3 w-3" />
                {result.file_path}
              </span>
            )}
            {result.source_url && (
              <a
                href={result.source_url}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center gap-1 text-xs text-primary hover:underline"
              >
                <ExternalLink className="h-3 w-3" />
                source
              </a>
            )}
            {result.category && (
              <Badge variant="secondary" className="text-[10px] h-4 px-1.5">{result.category}</Badge>
            )}
            {result.tags?.map((t) => (
              <Badge key={t} variant="outline" className="text-[10px] h-4 px-1.5">{t}</Badge>
            ))}
          </div>
        </div>
        {result.rerank_score !== null && <ScoreBadge score={result.rerank_score} />}
      </div>

      <p className="text-sm text-muted-foreground leading-relaxed">
        {truncated ? content.slice(0, 300) + "…" : content}
      </p>

      {content.length > 300 && (
        <button
          onClick={() => setExpanded((v) => !v)}
          className="text-xs text-primary flex items-center gap-1 hover:underline"
        >
          {expanded ? (
            <><ChevronUp className="h-3 w-3" /> Show less</>
          ) : (
            <><ChevronDown className="h-3 w-3" /> Show more</>
          )}
        </button>
      )}
    </div>
  )
}

export default function Search() {
  const [query, setQuery] = useState("")
  const [category, setCategory] = useState("")
  const [tags, setTags] = useState("")
  const [topK, setTopK] = useState(5)
  const [showFilters, setShowFilters] = useState(false)
  const [lastQuery, setLastQuery] = useState("")

  const search = useSearch()
  const loading = search.isPending
  const searched = !search.isIdle
  const results: SearchResult[] | null = search.data?.results ?? null

  async function runSearch(raw: string) {
    const q = raw.trim()
    if (!q) return
    const filters: Record<string, unknown> = {}
    if (category.trim()) filters.category = category.trim()
    if (tags.trim()) filters.tags = tags.split(",").map((t) => t.trim()).filter(Boolean)

    setLastQuery(q)
    try {
      await search.mutateAsync({
        query: q,
        topK,
        filters: Object.keys(filters).length ? filters : undefined,
      })
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Search failed")
    }
  }

  function handleSearch(e?: React.FormEvent) {
    e?.preventDefault()
    void runSearch(query)
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Search</CardTitle>
        <CardDescription>Test retrieval from the knowledge base with semantic search and reranking.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <form onSubmit={handleSearch} className="flex gap-2">
          <div className="relative flex-1">
            <SearchIcon className="absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              className="h-11 pl-10 text-base shadow-soft"
              placeholder="Ask a question or enter keywords…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </div>
          <Button type="submit" size="lg" disabled={loading || !query.trim()} className="h-11 shadow-glow">
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <SearchIcon className="h-4 w-4" />}
            Search
          </Button>
        </form>

        <div>
          <button
            type="button"
            onClick={() => setShowFilters((v) => !v)}
            className="text-xs text-muted-foreground flex items-center gap-1 hover:text-foreground transition-colors"
          >
            {showFilters ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
            Filters &amp; options
          </button>

          {showFilters && (
            <div className="mt-3 grid grid-cols-1 sm:grid-cols-3 gap-3 p-3 rounded-md border bg-muted/30">
              <div className="space-y-1.5">
                <Label htmlFor="filter-category" className="text-xs">Category</Label>
                <Input
                  id="filter-category"
                  placeholder="Engineering"
                  value={category}
                  onChange={(e) => setCategory(e.target.value)}
                  className="h-8 text-xs"
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="filter-tags" className="text-xs">Tags (comma-separated)</Label>
                <Input
                  id="filter-tags"
                  placeholder="rag, llm"
                  value={tags}
                  onChange={(e) => setTags(e.target.value)}
                  className="h-8 text-xs"
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="top-k" className="text-xs">Results (top_k)</Label>
                <Input
                  id="top-k"
                  type="number"
                  min={1}
                  max={20}
                  value={topK}
                  onChange={(e) => setTopK(Number(e.target.value))}
                  className="h-8 text-xs"
                />
              </div>
            </div>
          )}
        </div>

        {loading && (
          <div className="flex items-center justify-center py-12 text-muted-foreground">
            <Loader2 className="h-5 w-5 animate-spin mr-2" />
            <span className="text-sm">Searching...</span>
          </div>
        )}

        {!loading && searched && results !== null && (
          <>
            <p className="text-sm text-muted-foreground">
              {results.length} result{results.length !== 1 ? "s" : ""} for{" "}
              <span className="font-medium text-foreground">"{lastQuery}"</span>
            </p>
            {results.length === 0 ? (
              <div className="text-center py-12 text-muted-foreground">
                <p className="text-sm">No results found. Try a different query or adjust filters.</p>
              </div>
            ) : (
              <div className="space-y-3">
                {results.map((r, i) => (
                  <ResultCard key={r.id} result={r} rank={i + 1} />
                ))}
              </div>
            )}
          </>
        )}

        {!loading && !searched && (
          <div className="rounded-xl border border-dashed bg-muted/30 px-6 py-12 text-center">
            <span className="mx-auto mb-3 grid h-12 w-12 place-items-center rounded-xl bg-accent text-accent-foreground">
              <SearchIcon className="h-5 w-5" />
            </span>
            <p className="text-sm font-medium text-foreground">Search your knowledge base</p>
            <p className="mt-1 text-sm text-muted-foreground">
              Hybrid vector + full-text retrieval, reranked for relevance.
            </p>
            <div className="mt-5 flex flex-wrap justify-center gap-2">
              {SAMPLE_QUERIES.map((q) => (
                <button
                  key={q}
                  type="button"
                  onClick={() => {
                    setQuery(q)
                    void runSearch(q)
                  }}
                  className="rounded-full border border-border bg-background px-3 py-1.5 text-xs font-medium text-muted-foreground transition-colors hover:border-primary/40 hover:bg-accent hover:text-accent-foreground"
                >
                  {q}
                </button>
              ))}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
