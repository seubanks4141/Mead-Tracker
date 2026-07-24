from django.conf import settings


def app_settings(request):
    return {
        "app_name": "Mead Tracker",
        "allow_signups": settings.ALLOW_SIGNUPS,
        "configured_public_base_url": settings.PUBLIC_BASE_URL,
    }
