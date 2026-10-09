# Generated for multi-file transaction attachments (1-10 per doc).
from django.conf import settings
from django.db import migrations, models

import apps.core.attachments


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("contenttypes", "0002_remove_content_type_name"),
        ("foundation", "0013_userprofile_avatar_userprofile_theme"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="DocumentAttachment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("is_active", models.BooleanField(db_index=True, default=True)),
                ("object_id", models.PositiveBigIntegerField(db_index=True)),
                ("file", models.FileField(upload_to=apps.core.attachments.attachment_upload_to)),
                ("original_name", models.CharField(max_length=255)),
                ("size", models.PositiveBigIntegerField(default=0)),
                ("mime", models.CharField(blank=True, max_length=128)),
                ("is_deleted", models.BooleanField(db_index=True, default=False)),
                ("deleted_at", models.DateTimeField(blank=True, null=True)),
                ("retain_until", models.DateField(blank=True, db_index=True, null=True)),
                ("company", models.ForeignKey(blank=True, null=True, on_delete=models.SET_NULL, related_name="+", to="foundation.company")),
                ("content_type", models.ForeignKey(on_delete=models.PROTECT, to="contenttypes.contenttype")),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=models.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL)),
                ("deleted_by", models.ForeignKey(blank=True, null=True, on_delete=models.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL)),
                ("segment", models.ForeignKey(blank=True, null=True, on_delete=models.SET_NULL, related_name="+", to="foundation.segment")),
                ("updated_by", models.ForeignKey(blank=True, null=True, on_delete=models.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL)),
                ("uploaded_by", models.ForeignKey(blank=True, null=True, on_delete=models.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["created_at", "id"],
                "indexes": [models.Index(fields=["content_type", "object_id", "is_deleted"], name="core_attach_ct_obj_del_idx")],
            },
        ),
    ]
