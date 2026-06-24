import { NavLink, Navigate, Route, Routes, useLocation, useSearchParams } from "react-router-dom"
import {
  Database,
  Upload,
  Search as SearchIcon,
  ListChecks,
  Moon,
  Sun,
  BookOpen,
  Wifi,
  WifiOff,
} from "lucide-react"
import { cn } from "@/lib/utils"
import { Brand, PRODUCT_NAME } from "@/components/Brand"
import { useTheme } from "@/hooks/useTheme"
import { useHealth } from "@/hooks/queries"
import { API_BASE } from "@/lib/api"
import Documents from "@/pages/Documents"
import Ingest from "@/pages/Ingest"
import SearchPage from "@/pages/Search"
import Jobs from "@/pages/Jobs"

const nav = [
  { to: "/documents", label: "Documents", icon: Database, blurb: "Browse the corpus" },
  { to: "/ingest", label: "Ingest", icon: Upload, blurb: "Add content" },
  { to: "/search", label: "Search", icon: SearchIcon, blurb: "Test retrieval" },
  { to: "/jobs", label: "Jobs", icon: ListChecks, blurb: "Background runs" },
]

function JobsWithHighlight() {
  const [params] = useSearchParams()
  return <Jobs highlightId={params.get("highlight") ?? undefined} />
}

// ── Live backend status ───────────────────────────────────────────────────────

function HealthPill() {
  const { data, isError, isLoading } = useHealth()
  const online = !!data && !isError

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium transition-colors",
        isLoading
          ? "border-border bg-muted text-muted-foreground"
          : online
            ? "border-success/30 bg-success/10 text-success"
            : "border-destructive/30 bg-destructive/10 text-destructive",
      )}
      title={online ? `Connected to ${API_BASE}` : `Cannot reach ${API_BASE}`}
    >
      {online ? <Wifi className="h-3 w-3" /> : <WifiOff className="h-3 w-3" />}
      <span className="hidden sm:inline">
        {isLoading ? "Connecting…" : online ? "Connected" : "Offline"}
      </span>
    </span>
  )
}

function ThemeToggle() {
  const { theme, toggle } = useTheme()
  return (
    <button
      onClick={toggle}
      className="grid h-9 w-9 place-items-center rounded-lg border border-border bg-background text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
      title={theme === "dark" ? "Switch to light" : "Switch to dark"}
      aria-label="Toggle theme"
    >
      {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
    </button>
  )
}

// ── Navigation ────────────────────────────────────────────────────────────────

function NavItem({
  to,
  label,
  blurb,
  icon: Icon,
}: {
  to: string
  label: string
  blurb: string
  icon: typeof Database
}) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) =>
        cn(
          "group flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm transition-all",
          isActive
            ? "bg-accent text-accent-foreground shadow-soft"
            : "text-sidebar-foreground hover:bg-muted hover:text-foreground",
        )
      }
    >
      {({ isActive }) => (
        <>
          <span
            className={cn(
              "grid h-8 w-8 shrink-0 place-items-center rounded-md border transition-colors",
              isActive
                ? "border-primary/30 bg-background text-primary"
                : "border-transparent bg-muted/60 text-muted-foreground group-hover:text-foreground",
            )}
          >
            <Icon className="h-4 w-4" />
          </span>
          <span className="min-w-0">
            <span className="block font-medium leading-tight">{label}</span>
            <span className="block text-xs text-muted-foreground">{blurb}</span>
          </span>
        </>
      )}
    </NavLink>
  )
}

function Sidebar() {
  return (
    <aside className="hidden w-[264px] shrink-0 flex-col border-r border-sidebar-border bg-sidebar md:flex">
      <div className="flex h-16 items-center border-b border-sidebar-border px-5">
        <Brand showTagline />
      </div>

      <nav className="flex-1 space-y-1 overflow-y-auto p-3">
        <p className="px-3 pb-1 pt-2 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
          Workspace
        </p>
        {nav.map((item) => (
          <NavItem key={item.to} {...item} />
        ))}
      </nav>

      <div className="space-y-3 border-t border-sidebar-border p-4">
        <a
          href="http://localhost:3000"
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-2 rounded-lg px-3 py-2 text-sm text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
        >
          <BookOpen className="h-4 w-4" />
          Documentation
        </a>
        <div className="rounded-lg border border-sidebar-border bg-background/60 px-3 py-2.5">
          <p className="text-[11px] font-medium text-muted-foreground">Self-hosted · private</p>
          <p className="mt-0.5 truncate font-mono text-[11px] text-muted-foreground/70" title={API_BASE}>
            {API_BASE.replace(/^https?:\/\//, "")}
          </p>
        </div>
      </div>
    </aside>
  )
}

function MobileNav() {
  return (
    <nav className="flex gap-1 overflow-x-auto border-b border-border bg-background px-2 py-2 md:hidden">
      {nav.map(({ to, label, icon: Icon }) => (
        <NavLink
          key={to}
          to={to}
          className={({ isActive }) =>
            cn(
              "flex shrink-0 items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition-colors",
              isActive ? "bg-accent text-accent-foreground" : "text-muted-foreground hover:bg-muted",
            )
          }
        >
          <Icon className="h-4 w-4" />
          {label}
        </NavLink>
      ))}
    </nav>
  )
}

// ── Topbar ────────────────────────────────────────────────────────────────────

function Topbar() {
  const { pathname } = useLocation()
  const current = nav.find((n) => pathname.startsWith(n.to))

  return (
    <header className="sticky top-0 z-20 flex h-16 items-center justify-between gap-4 border-b border-border bg-background/80 px-4 backdrop-blur-md sm:px-6">
      <div className="flex items-center gap-2 text-sm">
        <span className="font-semibold text-muted-foreground md:hidden">{PRODUCT_NAME}</span>
        <span className="hidden text-muted-foreground md:inline">{PRODUCT_NAME}</span>
        <span className="text-muted-foreground/40">/</span>
        <span className="font-semibold text-foreground">{current?.label ?? "Home"}</span>
      </div>
      <div className="flex items-center gap-2">
        <HealthPill />
        <ThemeToggle />
      </div>
    </header>
  )
}

// ── App ───────────────────────────────────────────────────────────────────────

export default function App() {
  const { pathname } = useLocation()

  return (
    <div className="flex min-h-screen bg-background">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col shell-glow">
        <Topbar />
        <MobileNav />
        <main className="flex-1 px-4 py-6 sm:px-6 lg:px-8">
          <div key={pathname} className="mx-auto max-w-6xl animate-in-up">
            <Routes>
              <Route path="/" element={<Navigate to="/documents" replace />} />
              <Route path="/documents" element={<Documents />} />
              <Route path="/ingest" element={<Ingest />} />
              <Route path="/search" element={<SearchPage />} />
              <Route path="/jobs" element={<JobsWithHighlight />} />
              <Route path="*" element={<Navigate to="/documents" replace />} />
            </Routes>
          </div>
        </main>
      </div>
    </div>
  )
}
