from django.urls import path

from . import views


app_name = "tracker"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("health/", views.health, name="health"),
    path("help/", views.help_page, name="help"),
    path("accounts/signup/", views.signup, name="signup"),
    path("users/", views.user_list, name="user_list"),
    path("users/new/", views.user_create, name="user_create"),
    path(
        "users/<int:user_id>/deactivate/",
        views.user_deactivate,
        name="user_deactivate",
    ),
    path(
        "users/<int:user_id>/reactivate/",
        views.user_reactivate,
        name="user_reactivate",
    ),
    path("batches/new/", views.batch_create, name="batch_create"),
    path("batches/<uuid:pk>/", views.batch_detail, name="batch_detail"),
    path("batches/<uuid:pk>/edit/", views.batch_edit, name="batch_edit"),
    path(
        "batches/<uuid:batch_pk>/additions/new/",
        views.addition_add,
        name="addition_add",
    ),
    path(
        "additions/<uuid:pk>/edit/",
        views.addition_edit,
        name="addition_edit",
    ),
    path(
        "batches/<uuid:batch_pk>/gravity/new/",
        views.gravity_add,
        name="gravity_add",
    ),
    path(
        "gravity/<uuid:pk>/edit/",
        views.gravity_edit,
        name="gravity_edit",
    ),
    path(
        "batches/<uuid:batch_pk>/observations/new/",
        views.observation_add,
        name="observation_add",
    ),
    path(
        "observations/<uuid:pk>/edit/",
        views.observation_edit,
        name="observation_edit",
    ),
    path(
        "observations/<uuid:pk>/photo/",
        views.observation_photo,
        name="observation_photo",
    ),
    path(
        "batches/<uuid:batch_pk>/status/",
        views.status_update,
        name="status_update",
    ),
    path(
        "entries/<str:kind>/<uuid:pk>/delete/",
        views.entry_delete,
        name="entry_delete",
    ),
    path(
        "entries/<str:kind>/<uuid:pk>/restore/",
        views.entry_restore,
        name="entry_restore",
    ),
    path("batches/<uuid:pk>/label/", views.label, name="label"),
    path("batches/<uuid:pk>/trash/", views.batch_trash, name="batch_trash"),
    path("batches/<uuid:pk>/label.pdf", views.label_pdf, name="label_pdf"),
    path("batches/<uuid:pk>/qr.svg", views.qr_svg, name="qr_svg"),
    path("batches/<uuid:pk>/export.json", views.batch_export, name="batch_export"),
    path("backups/database/", views.database_backup, name="database_backup"),
    path("q/<str:token>/", views.qr_batch, name="qr_batch"),
]
