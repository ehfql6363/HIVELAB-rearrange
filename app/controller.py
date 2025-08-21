from threading import Event
from typing import Callable, Dict, Any

from .jobs import load_jobs

class AppController:
    """
    Coordinates UI <-> Job execution.
    """
    def __init__(self, settings):
        self.settings = settings
        self.jobs = load_jobs()
        self.current_cancel_event: Event | None = None

    def list_job_names(self):
        return [job_cls.meta()['name'] for job_cls in self.jobs]

    def get_job_by_name(self, name: str):
        for job_cls in self.jobs:
            if job_cls.meta()['name'] == name:
                return job_cls
        raise KeyError(f"Job '{name}' not found")

    def run_job(self, job_name: str, context: Dict[str, Any],
                progress_cb: Callable[[int, str], None],
                done_cb: Callable[[bool, str], None]):
        job_cls = self.get_job_by_name(job_name)
        job = job_cls()
        cancel_event = Event()
        self.current_cancel_event = cancel_event

        def _run():
            ok = False
            err_msg = ""
            try:
                job.run(context=context, progress_cb=progress_cb, cancel_event=cancel_event)
                ok = True
            except Exception as e:
                err_msg = str(e)
            finally:
                self.current_cancel_event = None
                done_cb(ok, err_msg)

        return _run  # caller should submit to a thread

    def cancel(self):
        if self.current_cancel_event and not self.current_cancel_event.is_set():
            self.current_cancel_event.set()
            return True
        return False
