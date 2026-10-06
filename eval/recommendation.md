# Stage 0: Model Recommendation

Sources: `eval/report.md` (metrics on the 31 reference pages), a qualitative review, and the 2026-10-02 run on an RTX 3060 12 GB, vLLM 0.30 / llama.cpp.

## Summary

| Model | CER↓ | Numbers F1↑ | TEDS↑ | TEDS-page↑ | Formulas CER↓ | Standalone figures | Sketches in cells | s/page |
|---|---|---|---|---|---|---|---|---|
| dots.mocr | 0,150 | 0,882 | **0,824** | **0,915** | **0,412** | 18/18 | 0/29 | **26** |
| HunyuanOCR 1.5 | **0,082** | **0,918** | 0,653 | 0,807 | 0,698 | no bbox | no bbox | 51 |
| Chandra 2 (FP8) | 0,180 | 0,874 | 0,752 | 0,792 | 0,521 | 18/18 | **9/29** | 38 |
| PaddleOCR-VL-1.6 | 0,195 | 0,866 | 0,738 | 0,781 | 0,687 | 18/18 | 2/29 | ~8 |
| Qwen3.5-9B (whole page) | 0,221 | 0,892 | 0,569 | 0,726 | 0,856 | no bbox | no bbox | 53 |

All models with layout output have a figure-box precision of 1.00: there are no spurious figures.

## Recommendation

1. **Layout + draft A: dots.mocr.**
   - Best table structure and formulas, best text in the text category (CER 0.023).
   - The fastest model.
   - Finds all standalone figures, photos and charts with accurate boxes; separates running headers and footers correctly.
   - Weak spots that the cascade will cover: Latin "M" in designations ("173M1"), lost colspan, "I"→"1" in figure numbers, occasional errors in numbers.
2. **Draft B (on block crops): HunyuanOCR 1.5.**
   - Best text and number accuracy; its architecture differs from dots, so the errors are only weakly correlated.
   - Limitations: it breaks tables (invents header rows) and does not join hyphenated line breaks. So for tables, draft B comes from Chandra 2, and Hunyuan is kept for text and formulas.
3. **Draft B for tables: Chandra 2.**
   - Best at holding colspan/thead, and the only one that partially finds sketches in cells.
   - It paraphrases text (replaces words with near-synonyms of a different form), so it is not used for prose.
4. **Arbiter: Qwen3.5-9B (Q5_K_M, llama.cpp).**
   - As a standalone OCR it is the weakest, as expected from the video.
   - Its role is to choose between drafts while looking at the block crop. Arbiter quality is measured in Plan 2.
   - Known risks to address in the prompt: translating the Russian word for "Table" into English, the Cyrillic subscript "g"→`\Gamma`, looping.
5. **Not adopted:** PaddleOCR-VL (truncates blocks, Latin letters in formulas, garbage characters), DeepSeek-OCR 2 and dots.ocr (excluded because of download speed; can be added if needed).

## New Requirement for Plan 2

**No model finds sketches inside table cells (29 of the 47 reference figures).** A custom extractor is needed: inside the table bbox, look for graphics regions (connected components not covered by text), crop them into `images/` and insert them as `<img>` into the corresponding cell. The metric already exists ("Figures P/R").

## Memory and Launch Constraints (reflected in `techbookocr.toml`)

- dots.mocr: the server limits the image to 4 MP (`--mm-processor-kwargs`), otherwise there is not enough memory for the KV cache.
- HunyuanOCR on vLLM 0.30: `--enforce-eager` (CUDA graph capture fails).
- Chandra 2 runs on vLLM 0.30 (instead of the pinned 0.17), so no separate image is needed.
- All models fit into 12 GB one at a time; peak VRAM is 9-11.9 GB.

## Expected Cascade Speed (estimate)

dots ~26 s/page. Draft B only on block crops, the arbiter only on disagreements, tables and formulas. Estimate: 60-90 s/page, i.e. 100 thousand pages ≈ 70-100 days of running. The figure will be refined on the reference set in Plan 2. If it turns out too slow, there is a fast mode: dots plus the arbiter on tables only.

## Note on the Figure Columns in report.md

The columns "Figures outside tables P/R" and "Sketches in tables R" split the reference figures by the tables that the model itself predicted, so the denominators differ between models and cannot be compared directly (outside tables all have 1.00/1.00). A fair comparison uses a fixed reference split (all figures on pages gir-0135L/R and gir-0150L/R are sketches in cells, 29 of them; the other 18 are standalone figures): standalone figures 18/18 for dots.mocr, Chandra 2 and PaddleOCR-VL; sketches in cells: dots 0/29, Chandra 9/29, Paddle 2/29. Fixing the metric (a reference `in_table` flag) is the first task of Plan 2.
