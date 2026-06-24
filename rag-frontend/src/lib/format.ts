export function formatDate(str: string | null | undefined): string {
  if (!str) return "—"
  return new Date(str).toLocaleDateString()
}

export function formatDateTime(str: string | null | undefined): string | null {
  if (!str) return null
  return new Date(str).toLocaleString()
}
