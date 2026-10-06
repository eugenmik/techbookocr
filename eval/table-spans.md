# Measuring the "one value per row" → colspan rule

Command (no models needed, recomputed from state.sqlite):

```bash
uv run techbookocr run "test_books/<book>.djvu" --out out/v1-fast-9b --redo postproc
```

## Coverage

| Book | Merged rows (layer 1) | Suspicious rows (dashes) |
|---|---|---|
| Safronov | 154 | 6 |
| Voronin | 17 | 11 |

Coverage matched the estimate in `docs/known-issues.md` no. 1: "one value, the rest empty" is 154 and 17 rows.
The suspicious-dash rule reports but does not edit: a row with a range value surrounded by runs of
dashes (>= 2 adjacent) goes into "Needs manual review". The main case from known-issues is caught:
Safronov p. 44, "Casting weight, kg": "10—500" + 2 dashes.

## Check against scans: 15 random merged rows (seed 1)

| # | Book | Page | Value | Verdict |
|---|---|---|---|---|
| 1 | Safronov | 0018R (p. 39) | 6 workers | correct: printed centered across two columns, the original defect case |
| 2 | Safronov | 0132R (p. 269) | length 1840 | correct |
| 3 | Voronin | 0308 (p. 309) | Appendix: 310 | **wrong**: a table-of-contents page number, belongs to the last column |
| 4 | Safronov | 0066L (p. 134) | "80": 100 | **wrong**: the value is for model 99914 only, the neighboring cells are legitimately empty |
| 5 | Safronov | 0016R (p. 35) | 10 | correct |
| 6 | Safronov | 0121L (p. 244) | wire diameter 16 | correct |
| 7 | Safronov | 0115L (p. 232) | 180—270 | correct |
| 8 | Safronov | 0119R (p. 241) | 45—50 | correct |
| 9 | Safronov | 0150R (p. 305) | 25 | correct |
| 10 | Safronov | 0089L (p. 180) | 160 | correct |
| 11 | Safronov | 0026L (p. 54) | "Hydraulic cylinders:" | correct in the end: a table section subheading |
| 12 | Safronov | 0007L (p. 16) | 0,08—0,12 (0,8—1,2) | correct |
| 13 | Safronov | 0121L (p. 244) | outer diameter 90 | correct |
| 14 | Voronin | 0229 (p. 230) | zircon concentrate: 90 | **wrong**: a sparse composition matrix, 90 belongs to composition 1 only |
| 15 | Safronov | 0089L (p. 180) | width 1 800 | correct |

**Result: 12/15 correct, below the 13/15 threshold.**

## Errors

All three wrong merges are tables where empty cells are legitimate:

1. **Table of contents** (Voronin 0308): "Material ... 300" is a page number in the last column, with leader dots in the
   middle one. The merge assigns the number a width of 2 columns.
2. **Sparse matrices** (Voronin 0229, Safronov 0066L): the value belongs to one composition/model,
   and the other cells are empty by meaning. The merge declares the value shared, which **distorts the data**
   and is worse than the original state.

## An Attempt at a Cheap Filter

The share of rows with empty cells in a table does not separate the cases: wrong tables have 6–93 % (table of
contents: 6 %, the dot-leader column is filled with text), correct ones 24–100 %. The position of the value in the cell
(first/last) does not separate them either: OCR puts both shared and single values into the outermost cell. The ambiguity
is fundamental and cannot be resolved without the ink coordinates on the scan.

## Conclusion

- The merge rule moves behind the `[pipeline] span_single_value` key and is **off by default**.
- The "suspicious dashes" report stays on: it does not edit text but flags rows for
  manual review in `quality.md`.
- The original defect (a value assigned to a single column) remains in `book.md`; a real fix needs the
  plan's second layer, geometry from vertical rules (Tasks 4–6), which sees that the value
  crosses the column boundary.

# Layer 2: Geometry (`span_geometry`)

Column separators are the vertical rules of the header band ∪ the full-height ones; rows are the ink bands of
text lines below the header rule (full grids are almost absent on the scans: 252 of 390 Safronov tables
have no rules at all). A run of ink that crosses a column boundary merges the cells of the candidate row
(exactly one non-dash value) if the band-to-row matching is unambiguous.

Safeguards against false merges, developed on full books:

- a run shorter than 6 rows is a dash or a rule fragment, not a value;
- a run with solid fill >= 0.6 of the box is a rule fragment;
- column-boundary bands are subtracted from the ink mask before searching for runs (dashed separators
  would otherwise produce false "crossing" runs);
- the merged columns must contain no ink >= 8 px outside the crossing runs: a printed
  dash inside a cell or the tail of a neighboring row blocks the merge;
- a dash in a cell is removed only if there is no ink in its box (the removal is recorded separately).

## Measurement on Full Books

| Book | Merges | Dash removals | Checked by eye | False |
|---|---|---|---|---|
| Safronov | 5 | 0 | 5/5 | 0 |
| Voronin | 0 | 0 | — | 0 |

All 5 Safronov merges are correct: "height 500", "Mixture consumption 480" (shared by A82M+A120M,
the printed "—" in A96 is preserved), "8 200" (99913+99914), "45—50", "0,3—0,35" (21423+21424).

False cases filtered out during debugging (they fired wrongly before the safeguards above): "Air receiver 400"
(a 4-pixel rule fragment), "Hydraulic cylinders:"/"Rollers:" (a dashed separator in the table body),
"depth 1 475" (the tail of a neighboring row's value crossed the boundary and was matched to the wrong row).

Misses (value centered but not merged): "Average mass 300", "Amplitude 0,1—1" and others:
ink bands stick to neighboring rows, so the candidate is ambiguous. The error direction is safe:
the value stays in one column, as before layer 2.

## Layer 2 Conclusion

- `span_geometry = true` is kept as the default: on two books 5/5 merges are correct, there are no false ones,
  and printed dashes are not removed.
- Coverage is modest: the geometry applies to tables with enough rules; the remaining rows
  still end up in "Needs manual review" through the dash report.
