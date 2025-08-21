from importlib import import_module
from pathlib import Path

def load_jobs():
    """Discover job modules in this package and return list of job classes (must expose meta() and run())."""
    job_classes = []
    pkg_path = Path(__file__).parent
    for py in pkg_path.glob("*.py"):
        if py.name.startswith("_") or py.name == "__init__.py":
            continue
        mod = import_module(f"{__package__}.{py.stem}")
        jobs = getattr(mod, "JOBS", [])
        job_classes.extend(jobs)
    return job_classes
