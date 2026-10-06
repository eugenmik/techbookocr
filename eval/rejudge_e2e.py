"""Re-check the arbiter answers in the e2e results with the current judge code (no models), so that variants
computed before and after the arbiter safeguard fixes are compared on the same code. Then: techbookocr run --redo postproc."""
import sys
from pathlib import Path

from techbookocr.config import load_config
from techbookocr.eval.cascade import replay
from techbookocr.pipeline.state import BookState

p = load_config(None).pipeline
for d in sys.argv[1:]:
    with BookState(Path(d) / "work" / "state.sqlite") as st:
        replay(st, p.tau_text, p.tau_halluc, "fast", p.halluc_abs_chars, "ru")
    print("rejudged", d)
