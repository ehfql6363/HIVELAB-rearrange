# app/controller.py
from __future__ import annotations
from threading import Event
from typing import Callable, Dict, Any, List, Type

# 잡 등록: 현재는 Rearrange 하나만
from .jobs.rearrange_job import RearrangeJob

JobType = Type

class AppController:
    def __init__(self, settings: Dict[str, Any]):
        self.settings = settings
        # ✅ 꼭 초기화하세요
        self.jobs: List[JobType] = [RearrangeJob]
        self._cancel_event: Event | None = None

    def list_job_names(self) -> List[str]:
        return [job_cls.meta()["name"] for job_cls in self.jobs]

    def get_job_by_name(self, name: str):
        for job_cls in self.jobs:
            if job_cls.meta().get("name") == name:
                return job_cls
        raise KeyError(f"Job not found: {name}")

    def run_job(
        self,
        name: str,
        context: Dict[str, Any],
        progress_cb: Callable[[int, str], None],
        done_cb: Callable[[bool, str], None],
    ):
        job_cls = self.get_job_by_name(name)
        self._cancel_event = Event()

        def _target():
            try:
                job = job_cls()
                job.run(context, progress_cb, self._cancel_event)
                done_cb(True, "")
            except Exception as e:
                done_cb(False, str(e))

        return _target

    def cancel(self) -> bool:
        if self._cancel_event and not self._cancel_event.is_set():
            self._cancel_event.set()
            return True
        return False
