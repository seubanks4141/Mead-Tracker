"""ASGI config for Mead Tracker."""

import os

from django.core.asgi import get_asgi_application


os.environ.setdefault("DJANGO_SETTINGS_MODULE", "mead_tracker.settings")
application = get_asgi_application()
