# Third-party components

The code in this repository is MIT licensed (see `LICENSE`). It does not include any third-party code, model weights, dictionaries or binaries. Everything below is installed or downloaded on your machine, under its own license. This list was checked on 2026-10-06 and is not legal advice; check the upstream terms before you redistribute anything.

## Libraries with copyleft terms

**PyMuPDF** is dual licensed: AGPL-3.0 or a commercial license from Artifex. pip installs it as a dependency. If you redistribute a build that contains PyMuPDF, or run the combination as a network service, you have to follow the AGPL-3.0 (including the source offer) or buy Artifex's commercial license.

**DjVuLibre** (`libdjvulibre`) is GPL-2.0-or-later. techbookocr loads it from the system through `ctypes`; it is not shipped with this repository. Install it with your package manager, for example `apt install libdjvulibre21`.

## Other Python dependencies

Pillow (MIT-CMU), NumPy (BSD-3-Clause), OpenAI Python (Apache-2.0), HTTPX (BSD-3-Clause), Typer and Rich (MIT), RapidFuzz (MIT), APTED (MIT), lxml (BSD-3-Clause), spylls (check upstream). certifi, pulled in transitively, is MPL-2.0.

The table-sketch detector runs in a separate environment that `uv` creates on first use: PaddlePaddle and PaddleOCR (Apache-2.0).

## Terminal panel

`@opentui/core`, `@opentui/solid` and `solid-js` are MIT. The rest of `panel/node_modules` is MIT, ISC, Apache-2.0, BSD or BlueOak-1.0.0; `caniuse-lite` (build-time data only) is CC-BY-4.0. `bun build --compile` embeds the Bun runtime, which includes JavaScriptCore under the LGPL. That matters only if you distribute the compiled `techbookocr-tui` binary, in which case ship Bun's license notices with it.

## Models and container images

techbookocr pulls these at runtime. They are not part of this repository.

| Component | Used in | License |
|---|---|---|
| `vllm/vllm-openai` image | all vLLM models | Apache-2.0 |
| `ghcr.io/ggml-org/llama.cpp` image | arbiter | MIT |
| dots.mocr (`dots-studio/dots.mocr`) | layout, both modes | MIT |
| Qwen3.5-9B (GGUF) | arbiter, both modes | Apache-2.0 |
| PP-DocLayoutV3 | sketches in tables | Apache-2.0 |
| HunyuanOCR (`tencent/HunyuanOCR`) | text drafts, `cascade` mode only | Tencent Hunyuan Community License |
| Chandra OCR 2 (`datalab-to/chandra-ocr-2` and its FP8 quant) | table drafts, `cascade` mode only | OpenRAIL-M with Datalab's commercial limits |

Two of these restrict how you may use them. The Tencent Hunyuan Community License does not cover the European Union, the United Kingdom or South Korea, needs a separate license above 100 million monthly users, and forbids using the outputs to improve other AI models. Chandra's terms allow research, personal use and companies under 2 million USD in revenue, and exclude competing with Datalab's hosted API. The default `fast` mode uses neither model.

The configuration also lists optional models that the pipeline does not use by default (DeepSeek-OCR-2, PaddleOCR-VL-1.6, an AWQ quant of Chandra). Check their licenses before you switch to them.

## Spell-check dictionaries

The post-processing step downloads Hunspell dictionaries (`ru_RU`, `en_US`, `de_DE_frami`) from the LibreOffice dictionaries repository into `~/.cache/techbookocr/hunspell`. They carry their own licenses (LGPL and GPL family for the Russian and German ones). Do not commit them to this repository.

## Example page

`examples/nbs-rp2560/` contains page 17 of T. B. Douglas and J. L. Dever, "Enthalpy and Specific Heat of Four Corrosion-Resistant Alloys at High Temperatures," Journal of Research of the National Bureau of Standards 54(1), 1955, RP2560. Both authors were NBS employees, so the paper is a work of the U.S. Government and is not subject to copyright in the United States (17 U.S.C. § 105). It may be protected in other countries. Source: https://nvlpubs.nist.gov/nistpubs/jres/54/jresv54n1p15_A1b.pdf
