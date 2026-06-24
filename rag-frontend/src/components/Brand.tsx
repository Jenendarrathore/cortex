import { cn } from "@/lib/utils"

export const PRODUCT_NAME = "Cortex"

/** The Cortex glyph (favicon mark), rendered inline so it inherits sizing. */
export function LogoMark({ className }: { className?: string }) {
  return (
    <img
      src="/favicon.svg"
      alt=""
      aria-hidden
      className={cn("select-none", className)}
      draggable={false}
    />
  )
}

/** Full lockup: mark + wordmark. */
export function Brand({
  className,
  showTagline = false,
}: {
  className?: string
  showTagline?: boolean
}) {
  return (
    <div className={cn("flex items-center gap-2.5", className)}>
      <span className="grid h-9 w-9 place-items-center rounded-xl bg-accent shadow-soft ring-1 ring-border">
        <LogoMark className="h-5 w-5" />
      </span>
      <div className="leading-none">
        <div className="text-[15px] font-bold tracking-tight">{PRODUCT_NAME}</div>
        {showTagline && (
          <div className="mt-1 text-[11px] font-medium text-muted-foreground">
            Knowledge base
          </div>
        )}
      </div>
    </div>
  )
}
