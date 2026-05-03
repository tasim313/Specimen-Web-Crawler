import os
import sys

from django.apps import AppConfig
from django.conf import settings


class PathologyConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'pathology'

    def ready(self):
        if not getattr(settings, "CAP_AUTO_START_ENABLED", False):
            return
        if len(sys.argv) < 2 or sys.argv[1] != "runserver":
            return
        if os.environ.get("RUN_MAIN") not in {"true", "1"}:
            return

        from .services.jobs import start_default_job_if_needed

        start_default_job_if_needed()
