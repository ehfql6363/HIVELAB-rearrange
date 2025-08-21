import time
from pathlib import Path
from typing import Callable, Dict, Any
from threading import Event

class SampleJob:
    """
    Example job that "processes" files in the input folder and reports progress.
    """
    @staticmethod
    def meta():
        return {"name": "Sample Job", "description": "Iterate files and simulate work."}

    def run(self, context: Dict[str, Any],
            progress_cb: Callable[[int, str], None],
            cancel_event: Event):
        input_dir = Path(context.get("input_dir", ""))
        files = [p for p in input_dir.glob("**/*") if p.is_file()]
        total = max(len(files), 1)
        for idx, f in enumerate(files, start=1):
            if cancel_event.is_set():
                progress_cb(0, "Cancelled")
                return
            time.sleep(0.02)
            pct = int(idx * 100 / total)
            progress_cb(pct, f"Processing: {f.name} ({idx}/{total})")

JOBS = [SampleJob]
