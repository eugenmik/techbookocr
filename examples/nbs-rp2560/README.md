# Example: NBS Research Paper 2560, page 17

`page.pdf` is page 17 (PDF page 3 of 5) of Thomas B. Douglas and James L. Dever, "Enthalpy and Specific Heat of Four Corrosion-Resistant Alloys at High Temperatures," Journal of Research of the National Bureau of Standards, Vol. 54, No. 1, January 1955, Research Paper 2560, pp. 15-19. `page.png` is the same page at 200 dpi.

Source: https://nvlpubs.nist.gov/nistpubs/jres/54/jresv54n1p15_A1b.pdf

Both authors worked at the National Bureau of Standards, and the paper was published by the Bureau, so it is a work of the U.S. Government and is not subject to copyright in the United States (17 U.S.C. § 105). It may be protected in other countries. NIST's statement on reuse: https://www.nist.gov/open/copyright-fair-use-and-licensing-statements-srd-data-software-and-technical-series-publications

The PDF from NIST is a 600 dpi scan with a hidden text layer made by Adobe Paper Capture, and that layer has many OCR errors. To make the pipeline recognize the scan itself, the run used `text_layer = "off"`:

```bash
sed 's/^text_layer = .*/text_layer = "off"/' techbookocr.toml > example.toml
uv run techbookocr run examples/nbs-rp2560/page.pdf --out out/example --config example.toml --lang en
```

`output/` is what the pipeline wrote, unchanged except for the `source` path in `meta.json`. The page anchor reads `page: ?` because the printed page number was not detected on this single page.
