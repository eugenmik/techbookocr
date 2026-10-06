// Parses a command line from environment variables ($EDITOR, TECHBOOKOCR_CMD).
/** Words as in a POSIX shell: single and double quotes, backslash. */
export function splitWords(s: string): string[] {
  const words: string[] = []
  let cur = ""
  let has = false
  let quote: "'" | '"' | null = null
  for (let i = 0; i < s.length; i++) {
    const c = s[i]!
    if (quote === "'") {
      if (c === "'") quote = null
      else cur += c
    } else if (quote === '"') {
      if (c === '"') quote = null
      else if (c === "\\" && i + 1 < s.length && '"\\$`'.includes(s[i + 1]!)) cur += s[++i]
      else cur += c
    } else if (c === "'" || c === '"') {
      quote = c
      has = true
    } else if (c === "\\" && i + 1 < s.length) {
      cur += s[++i]
      has = true
    } else if (/\s/.test(c)) {
      if (has || cur) words.push(cur)
      cur = ""
      has = false
    } else {
      cur += c
    }
  }
  if (has || cur) words.push(cur)
  return words
}
