from django.conf import settings
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path
from oauth2_provider import views as oauth2_views
from oauth2_provider.urls import metadata_urlpatterns


oauth2_urlpatterns = [
    path("authorize/", oauth2_views.AuthorizationView.as_view(), name="authorize"),
    path("token/", oauth2_views.TokenView.as_view(), name="token"),
    path(
        "revoke_token/",
        oauth2_views.RevokeTokenView.as_view(),
        name="revoke-token",
    ),
]

urlpatterns = []
if settings.CHATGPT_ENABLED:
    urlpatterns += [
        # Strict RFC 8414 and RFC 9728 discovery routes live at the origin root,
        # even though the authorization server itself is under /o/.
        path("", include(metadata_urlpatterns)),
        path(
            "o/",
            include(
                (oauth2_urlpatterns, "oauth2_provider"),
                namespace="oauth2_provider",
            ),
        ),
    ]

urlpatterns += [
    path("admin/", admin.site.urls),
    path(
        "accounts/login/",
        auth_views.LoginView.as_view(template_name="registration/login.html"),
        name="login",
    ),
    path(
        "accounts/logout/",
        auth_views.LogoutView.as_view(),
        name="logout",
    ),
    path("", include("tracker.urls")),
]
