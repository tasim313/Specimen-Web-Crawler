from django.db import models


class Organ(models.Model):
    name = models.CharField(max_length=100, unique=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Specimen(models.Model):
    class SourceSite(models.TextChoices):
        CAP = "cap.org", "CAP"
        PATHOLOGY_OUTLINES = "pathologyoutlines.com", "Pathology Outlines"

    organ = models.ForeignKey(
        Organ,
        on_delete=models.CASCADE,
        related_name="specimens",
    )
    specimen_name = models.TextField()
    site_name = models.TextField(blank=True)
    laterality = models.CharField(max_length=255, blank=True)
    specimen_type = models.CharField(max_length=100)
    specimen_size = models.TextField(blank=True, null=True)
    source_site = models.CharField(
        max_length=64,
        choices=SourceSite.choices,
        default=SourceSite.CAP,
    )
    source_file = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["specimen_name"]
        indexes = [
            models.Index(fields=["specimen_type"]),
            models.Index(fields=["source_site"]),
            models.Index(fields=["source_file"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["organ", "specimen_name"],
                name="unique_specimen_per_organ",
            ),
        ]

    def __str__(self) -> str:
        return self.specimen_name


class CrawlJob(models.Model):
    class SourceChoices(models.TextChoices):
        CAP = "cap.org", "CAP"
        PATHOLOGY_OUTLINES = "pathologyoutlines.com", "Pathology Outlines"
        BOTH = "both", "Both Sources"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        STOP_REQUESTED = "stop_requested", "Stop Requested"
        STOPPED = "stopped", "Stopped"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    name = models.CharField(max_length=200, blank=True)
    crawl_source = models.CharField(
        max_length=64,
        choices=SourceChoices.choices,
        default=SourceChoices.CAP,
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    limit = models.PositiveIntegerField(
        blank=True,
        null=True,
        help_text="Leave blank to crawl all available CAP protocol documents.",
    )
    destination_dir = models.CharField(max_length=255, blank=True)
    stop_requested = models.BooleanField(default=False)
    process_id = models.PositiveIntegerField(blank=True, null=True)
    total_links = models.PositiveIntegerField(default=0)
    files_downloaded = models.PositiveIntegerField(default=0)
    records_created = models.PositiveIntegerField(default=0)
    records_updated = models.PositiveIntegerField(default=0)
    records_skipped = models.PositiveIntegerField(default=0)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(blank=True, null=True)
    finished_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.name or f"Crawl Job #{self.pk}"
