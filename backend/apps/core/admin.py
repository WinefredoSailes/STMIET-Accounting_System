from django.contrib import admin

from apps.core.models import DocumentAttachment


@admin.register(DocumentAttachment)
class DocumentAttachmentAdmin(admin.ModelAdmin):
    list_display = ("id", "content_type", "object_id", "original_name", "size", "is_deleted", "created_at")
    list_filter = ("is_deleted", "content_type")
    search_fields = ("original_name",)
    readonly_fields = ("created_at", "updated_at", "size", "mime", "retain_until")
