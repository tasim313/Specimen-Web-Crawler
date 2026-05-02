from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        (
            "pathology",
            "0004_normalize_duplicate_titles",
        ),
    ]

    operations = [
        migrations.CreateModel(
            name="CrawlJob",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(blank=True, max_length=200)),
                ("status", models.CharField(choices=[("pending", "Pending"), ("running", "Running"), ("stop_requested", "Stop Requested"), ("stopped", "Stopped"), ("completed", "Completed"), ("failed", "Failed")], default="pending", max_length=20)),
                ("limit", models.PositiveIntegerField(blank=True, null=True)),
                ("destination_dir", models.CharField(blank=True, max_length=255)),
                ("stop_requested", models.BooleanField(default=False)),
                ("process_id", models.PositiveIntegerField(blank=True, null=True)),
                ("total_links", models.PositiveIntegerField(default=0)),
                ("files_downloaded", models.PositiveIntegerField(default=0)),
                ("records_created", models.PositiveIntegerField(default=0)),
                ("records_updated", models.PositiveIntegerField(default=0)),
                ("records_skipped", models.PositiveIntegerField(default=0)),
                ("error_message", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={"ordering": ["-created_at"]},
        ),
    ]
