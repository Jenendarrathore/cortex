import { cn } from "@/lib/utils"
import cortexLogo from "@/assets/cortex-logo.png"

export const PRODUCT_NAME = "Cortex"

export function LogoMark({ className }: { className?: string }) {
  return (
    <img
      src={cortexLogo}
      alt={`${PRODUCT_NAME} logo`}
      className={cn("select-none object-contain", className)}
      draggable={false}
    />
  )
}

export function Brand({
  className,
  showTagline = false,
}: {
  className?: string
  showTagline?: boolean
}) {
  return (
    <div className={cn("flex items-center gap-2.5", className)}>
      <span className="grid h-10 w-10 place-items-center overflow-hidden rounded-xl bg-accent/40 shadow-soft ring-1 ring-border">
        <LogoMark className="h-10 w-10" />
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
