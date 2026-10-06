import type { BookDetail, BookItem, Snapshot } from "../../src/bridge/types"

export const book = (name: string, over: Partial<BookItem> = {}): BookItem => ({
  name, status: "queued", stage: null, priority: 0, error: null, progress: null, scans: 100, ...over,
})

export function snap(books: BookItem[], over: Partial<Snapshot> = {}): Snapshot {
  return {
    daemon: { alive: true, state: "running", heartbeat_age_s: 2, run_until: null },
    root: "/home/u/out",
    counts: { queued: books.filter((b) => b.status === "queued").length },
    books,
    current: null,
    forecast: { queued_books: 0, scans: 0, unknown_scans: 0, seconds: null, s_per_scan: null, basis_books: 0,
                done_today: { books: 0, scans: 0 } },
    gpu: { util: 97, used_mib: 11161, total_mib: 12288 },
    model: { key: "qwen9b_arbiter", container: "techbookocr-qwen9b_arbiter", up_s: 7860 },
    events: [{ ts: "2026-10-04T23:55:09", book: "Гиршович", level: "info", message: "consensus: accept 5281" }],
    ...over,
  }
}

export const LIBRARY = [
  book("Гиршович_Справочник по чугунному литью_1978", { status: "processing", stage: "arbiter",
    progress: [412, 560], scans: 377 }),
  book("Сафронов - Справочник по литейному оборудованию", { priority: 5, scans: 160 }),
  book("Шишляев.Железоуглеродистые литейные сплавы", { status: "done", scans: 163 }),
  book("asm-probe", { status: "failed", stage: "layout", error: "StageAborted: 3 consecutive transport failures" }),
]

export const DETAIL: BookDetail = {
  info: { name: LIBRARY[0].name, source: "/b/g.djvu", kind: "djvu", lang: "ru", mode: "fast", scans: 377,
          pages: 753, added_at: "2026-10-04T14:58:00", updated_at: "2026-10-04T23:55:00", status: "processing",
          error: null },
  stages: [
    { stage: "layout", status: "done", seconds: 20220, s_per_page: 26.9, progress: [753, 753], eta_s: null },
    { stage: "sketches", status: "done", seconds: 3656, s_per_page: 4.9, progress: [560, 560], eta_s: null },
    { stage: "arbiter", status: "running", seconds: 7860, s_per_page: 10.4, progress: [412, 560], eta_s: 4140 },
    { stage: "postproc", status: "pending", seconds: null, s_per_page: null, progress: null, eta_s: null },
  ],
  issues: ["0004L (p. 8), block 2 (table): rejected, cer 0.629 → fallback_a"],
  quality_md: "# Quality report\n\n## Time per stage\n\n- layout 5h37m\n",
  out_dir: "/home/u/out/g",
}
