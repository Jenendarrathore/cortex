# Cortex — Admin UI

React + TypeScript frontend for **Cortex**, the self-hosted private knowledge base.

**Tech:** React 19, Vite 8, TypeScript (strict), Tailwind CSS, shadcn/ui, TanStack Query v5, react-router-dom v7, sonner

**URL:** `http://localhost:5173` (dev server)

---

## Prerequisites

The RAG backend must be running before starting the UI:

```bash
# From the cortex/ root
make rag
```

---

## Start

```bash
# From the cortex/ root
make rag-ui

# Or directly from this directory
npm run dev
```

---

## Pages

| Route | Description |
|-------|-------------|
| `/documents` | Paginated document table. Click a row for detail (raw content + chunks). Delete from the row action. |
| `/ingest` | Three tabs: **Upload File** (.md / .txt), **Folder** (server-side path), **Paste Text** with metadata form. All submit as background jobs → redirect to `/jobs`. |
| `/search` | Hybrid search with tag / category / date filters. Results show chunk text, heading, score, and document metadata. |
| `/jobs` | Background ingestion jobs table. Status badges, progress bar, result counts. Click a row to expand the per-file log table. Auto-refetches every 2 s while any job is active. |

---

## Data layer

All API calls go through `src/lib/api.ts` (single source: `VITE_API_URL`, auth header).
Server state managed with TanStack Query (`src/hooks/queries.ts`):

| Hook | Description |
|------|-------------|
| `useDocuments(page)` | Paginated document list |
| `useDocument(id)` | Single document with chunks |
| `useDeleteDocument()` | Mutation — invalidates `["documents"]` on success |
| `useSearch()` | Search mutation |
| `useUploadFile()` | Mutation — returns `EnqueueResponse {job_id}` |
| `useIngestText()` | Mutation — returns `EnqueueResponse {job_id}` |
| `useIngestFolder()` | Mutation — returns `EnqueueResponse {job_id}` |
| `useJobs()` | Job list — auto-refetch every 2 s while any job active |
| `useJob(id)` | Single job with logs — auto-refetch every 1.5 s while running |

---

## Environment

Create `rag-frontend/.env.local` to override defaults:

```dotenv
VITE_API_URL=http://localhost:8002   # backend base URL
VITE_API_KEY=                        # leave empty if API_KEY not set in backend .env
```

---

## Build

```bash
npm run build   # tsc -b then vite build; zero TS errors required
```

TypeScript strict mode is enabled (`tsconfig.app.json`).
