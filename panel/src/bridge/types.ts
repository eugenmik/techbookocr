// Protocol v1 of the techbookocr bridge (src/techbookocr/tui/bridge.py). Fields match Python, snake_case.
export type BookStatus = "queued" | "processing" | "done" | "failed" | "skipped"

export interface BookItem {
  name: string; status: BookStatus; stage: string | null; priority: number; error: string | null
  progress: [number, number] | null; scans: number | null
}
export interface CurrentBook {
  name: string; stage: string | null; progress: [number, number] | null; s_per_unit: number | null; eta_s: number | null
}
export interface Forecast {
  queued_books: number; scans: number; unknown_scans: number; seconds: number | null; s_per_scan: number | null
  basis_books: number; done_today: { books: number; scans: number }
}
export interface EventItem { ts: string; book: string | null; level: string; message: string }
export interface Snapshot {
  daemon: { alive: boolean; state: string; heartbeat_age_s: number | null; run_until: string | null }
  root: string
  counts: Record<string, number>
  books: BookItem[]
  current: CurrentBook | null
  forecast: Forecast
  gpu: { util: number; used_mib: number; total_mib: number } | null
  model: { key: string; container: string; up_s: number | null } | null
  events: EventItem[]
}
export interface StageRow {
  stage: string; status: "done" | "running" | "pending"; seconds: number | null; s_per_page: number | null
  progress: [number, number] | null; eta_s: number | null
}
export interface BookDetail {
  info: {
    name: string; source: string; kind: string; lang: string | null; mode: string | null; scans: number | null
    pages: number | null; added_at: string; updated_at: string; status: BookStatus; error: string | null
  }
  stages: StageRow[]
  issues: string[]
  quality_md: string | null
  out_dir: string
  fixes?: FixSummary | null               // null: quality.md/fixes.json could not be read
}
export type FixState = "applied" | "reverted" | "not_found"
export interface Fix {
  id: string; scan: string; page: string | null; block: number | null; kind: string | null
  was: string; now: string; state: FixState; suggested: boolean; reason: string | null
  decided_by: "model" | "rule" | "user"; before: string; after: string
}
export interface FixCounts { applied: number; reverted: number; suggested: number; not_found: number }
export interface FixesData { fixes: Fix[]; counts: FixCounts; editable: boolean; why_not: string | null }
export interface FixSummary { total: number; suggested: number | null; reviewed: boolean }
export type FieldValue = string | number | boolean | null
export interface SettingField {
  section: string; key: string; kind: "choice" | "path" | "int" | "float" | "bool" | "model"
  choices: string[]; value: FieldValue; comment: string | null
}
export interface SettingsData { path: string; root?: string; fields: SettingField[] }
export interface ActResult { messages: string[] }
export interface AddResult { added: string[]; skipped: [string, string][]; skipped_total?: number; messages: string[] }
