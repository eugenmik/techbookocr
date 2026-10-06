# Known recognition issues

Checked on two full books (Voronin, 327 pp.; Safronov, 317 pp.) in fast mode with the local Qwen3.5-9B arbiter. Issues are listed by importance.

## 1. A value shared by several columns is assigned to one (main issue)

**What it looks like.** In reference books, a value that is the same for several machine models is printed once, centered between the columns, with no vertical rule. Examples: Safronov, p. 39 (a "height 500" row spanning two columns) and p. 44, table 15 (a "casting weight" row: 1.5—100 spanning two columns, 10—500 spanning two more, across four columns in total).

**What comes out.** Two different defects:

- p. 39: `<td></td><td>500</td>`: the value lands in the last column and the others are empty. It reads as "500 only for model NL453S1" although the value is shared. This is data distortion, not loss.
- p. 44: `1,5—100 | — | 10—500 | —`: the model **draws in dashes** in columns where nothing is printed in the book. This is invented data.

The correct markup in both cases is `<td colspan="N">`.

**How common.** Rows of the form "one value, other cells empty": Safronov 154 of 2639 (5.8%), Voronin 17 of 522. Rows of "value plus dashes": Safronov 108, Voronin 33. These are upper estimates: some of them are genuine single values.

**What was tried (2026-10-03).**

| Attempt | Result |
|---|---|
| A rule in the arbiter prompt ("a value centered across several columns is a `colspan`; do not invent dashes") | Did not help. Qwen3.5-9B copies draft A verbatim; `colspan` did not appear on either of the two tables. |
| Chandra 2 as the second draft (full cascade) | Worse. On p. 39 it returned an answer without a table (parse failure, 82 s); on p. 44 it shifted the row labels by one row and also invented dashes. |

Conclusion: neither a prompt change nor a second draft fixes it. The arbiter is too strongly anchored to the draft: `tau_halluc` rejects an answer that restructures the table.

**Fix approach.** Two layers were implemented (see `eval/table-spans.md`): layer 1 (one value per row) was measured and switched off by threshold (12/15 < 13/15); layer 2 (ruling-line geometry, `span_geometry = true`) is enabled based on a measurement of 5/5 correct, 0 false.

Original proposals:

1. **Cheap and safe.** A postprocessing rule: if a table row has exactly one non-empty data cell and the rest are empty, merge them into `<td colspan="N">`. An empty cell carries no information, so merging loses no data and removes the false attachment of the value to the last column. It needs a test on the minimal example from p. 39 and a check on both books: the number of changed rows and a spot check against the scan.
2. **Expensive and precise.** A geometric check on the image: these books have vertical rules between columns. Find them in the table crop image, determine the column boundaries, then for each value compare its horizontal extent with the boundaries. A value that crosses a rule or is centered between rules is marked `colspan`. This also gives the "dash is invented" signal: nothing is printed in the book at that spot. Estimate: 1–2 days, needs a separate plan and its own set of reference tables.
3. **Minimum.** If not fixed, at least flag such rows in `quality.md` in a "Needs manual review" section.

## 2. Misprints in the book itself are not corrected if they are plausible

Voronin, p. 60: "P₂O₃" is printed, the correct form is P₂O₅. The dots draft silently corrected it, and the arbiter restored it as printed. To the model, P₂O₃ is an existing substance, so it does not treat it as an "obvious" misprint. It can be caught reliably only with domain knowledge (slag composition).

## 3. Group number "I" is read as "1"

Voronin, p. 6 onward: the Roman numeral "I" in a narrow first column is recognized as the digit "1". "II" and "III" on the same pages are recognized correctly. A rule-based fix is dangerous: in neighboring tables "1" in the same kind of column is a genuine digit.

## 4. Three of eight sketches are not placed into cells

Voronin, p. 83: the "Crack classification" table, with color samples in the right column. The arbiter placed 5 of 8 sketches; the rest are output after the table, with a note in `quality.md`. The numbered-marker mechanism `<img n="k">` works, but on complex two-column tables the model does not mark all of them.

## 5. The remote arbiter (Qwen3.8-27B) often breaks down

Of 390 Safronov blocks: 17 answers were truncated (the model starts with reasoning in English), 12 had no table. The local 9B has 4 failures on the same blocks. If you ever return to the remote model, first add a system prompt that forbids a preamble.
