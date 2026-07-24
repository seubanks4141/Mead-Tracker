"""Django admin configuration for the Mead Tracker domain."""

from django.contrib import admin

from .models import (
    Addition,
    AuditLog,
    Batch,
    BatchStatusHistory,
    GravityReading,
    LabelPrintLog,
    Observation,
    QRLink,
)


class ActiveRecordAdminMixin:
    """Allow administrators to inspect and restore soft-deleted records."""

    def get_queryset(self, request):
        return self.model.all_objects.get_queryset()


class AdditionInline(admin.TabularInline):
    model = Addition
    extra = 0
    fields = ("kind", "name", "quantity", "unit", "added_at", "phase")
    show_change_link = True


class GravityReadingInline(admin.TabularInline):
    model = GravityReading
    extra = 0
    fields = ("specific_gravity", "reading_type", "measured_at", "method")
    show_change_link = True


class ObservationInline(admin.TabularInline):
    model = Observation
    extra = 0
    fields = ("observed_at", "category", "text")
    show_change_link = True


class BatchStatusHistoryInline(admin.TabularInline):
    model = BatchStatusHistory
    extra = 0
    fields = ("status", "changed_at", "changed_by", "notes")
    show_change_link = True


@admin.register(Batch)
class BatchAdmin(ActiveRecordAdminMixin, admin.ModelAdmin):
    list_display = (
        "name",
        "batch_number",
        "owner",
        "status",
        "start_date",
        "volume",
        "volume_unit",
        "deleted_at",
    )
    list_filter = ("status", "start_date", "deleted_at")
    search_fields = ("name", "batch_number", "style", "vessel", "owner__username")
    autocomplete_fields = ("owner",)
    readonly_fields = ("id", "created_at", "updated_at", "deleted_at")
    date_hierarchy = "start_date"
    inlines = (
        AdditionInline,
        GravityReadingInline,
        ObservationInline,
        BatchStatusHistoryInline,
    )


@admin.register(Addition)
class AdditionAdmin(ActiveRecordAdminMixin, admin.ModelAdmin):
    list_display = ("name", "batch", "kind", "quantity", "unit", "phase", "added_at")
    list_filter = ("kind", "phase", "unit", "deleted_at")
    search_fields = ("name", "batch__name", "batch__batch_number", "notes")
    autocomplete_fields = ("batch", "recorded_by")
    readonly_fields = ("id", "recorded_at", "updated_at", "deleted_at")
    date_hierarchy = "added_at"


@admin.register(GravityReading)
class GravityReadingAdmin(ActiveRecordAdminMixin, admin.ModelAdmin):
    list_display = (
        "specific_gravity",
        "batch",
        "reading_type",
        "measured_at",
        "method",
        "deleted_at",
    )
    list_filter = ("reading_type", "method", "deleted_at")
    search_fields = ("batch__name", "batch__batch_number", "notes")
    autocomplete_fields = ("batch", "recorded_by")
    readonly_fields = ("id", "recorded_at", "updated_at", "deleted_at")
    date_hierarchy = "measured_at"


@admin.register(Observation)
class ObservationAdmin(ActiveRecordAdminMixin, admin.ModelAdmin):
    list_display = ("batch", "category", "observed_at", "recorded_by", "deleted_at")
    list_filter = ("category", "deleted_at")
    search_fields = ("batch__name", "batch__batch_number", "text")
    autocomplete_fields = ("batch", "recorded_by")
    readonly_fields = ("id", "recorded_at", "updated_at", "deleted_at")
    date_hierarchy = "observed_at"


@admin.register(BatchStatusHistory)
class BatchStatusHistoryAdmin(admin.ModelAdmin):
    list_display = ("batch", "status", "changed_at", "changed_by", "recorded_at")
    list_filter = ("status",)
    search_fields = ("batch__name", "batch__batch_number", "notes")
    autocomplete_fields = ("batch", "changed_by")
    readonly_fields = ("id", "recorded_at")
    date_hierarchy = "changed_at"


@admin.register(QRLink)
class QRLinkAdmin(admin.ModelAdmin):
    list_display = (
        "batch",
        "token_preview",
        "label",
        "is_active",
        "scan_count",
        "created_at",
        "revoked_at",
    )
    list_filter = ("is_active", "created_at")
    search_fields = ("batch__name", "batch__batch_number", "label")
    autocomplete_fields = ("batch", "created_by")
    readonly_fields = (
        "id",
        "token",
        "created_at",
        "revoked_at",
        "last_scanned_at",
        "scan_count",
    )

    @admin.display(description="Token")
    def token_preview(self, obj):
        return f"{obj.token[:8]}…"


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("recorded_at", "actor", "action", "model_name", "object_repr", "batch")
    list_filter = ("action", "model_name", "recorded_at")
    search_fields = ("object_repr", "model_name", "batch__name", "actor__username")
    autocomplete_fields = ("batch", "actor")
    date_hierarchy = "recorded_at"

    def get_readonly_fields(self, request, obj=None):
        return tuple(field.name for field in self.model._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(LabelPrintLog)
class LabelPrintLogAdmin(admin.ModelAdmin):
    list_display = (
        "batch",
        "width",
        "height",
        "dimension_unit",
        "output_mode",
        "copies",
        "printed_by",
        "printed_at",
    )
    list_filter = ("dimension_unit", "output_mode", "printed_at")
    search_fields = ("batch__name", "batch__batch_number", "label_preset")
    autocomplete_fields = ("batch", "qr_link", "printed_by")
    readonly_fields = (
        "id",
        "batch",
        "qr_link",
        "printed_by",
        "label_preset",
        "width",
        "height",
        "dimension_unit",
        "output_mode",
        "copies",
        "printed_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
