import solidPlugin from "@opentui/solid/bun-plugin"

const result = await Bun.build({
  entrypoints: ["./src/main.tsx"],
  target: "bun",
  minify: true,
  plugins: [solidPlugin],
  define: { "process.env.OPENTUI_LIBC": JSON.stringify("glibc") },
  compile: { target: "bun-linux-x64", outfile: "dist/techbookocr-tui" },
})
if (!result.success) {
  for (const m of result.logs) console.error(m)
  process.exitCode = 1
} else {
  console.log("built dist/techbookocr-tui")
}
