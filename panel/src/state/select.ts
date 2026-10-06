import type { BookItem, SettingField } from "../bridge/types"
import type { AppState } from "./store"

export function visibleBooks(s: AppState): BookItem[] {
  const books = s.snap?.books ?? []
  const f = s.filter.text.toLocaleLowerCase()
  return f ? books.filter((b) => b.name.toLocaleLowerCase().includes(f)) : books
}

export const selectedName = (s: AppState): string | null => visibleBooks(s)[s.cursor]?.name ?? null

/** Action targets: marked visible books (the filter hides the rest), otherwise the book under the cursor. */
export function targets(s: AppState): string[] {
  const visible = new Set(visibleBooks(s).map((b) => b.name))
  const marked = s.marks.filter((m) => visible.has(m))
  if (marked.length) return marked
  const n = selectedName(s)
  return n ? [n] : []
}

export const fieldId = (f: SettingField) => `${f.section}.${f.key}`
