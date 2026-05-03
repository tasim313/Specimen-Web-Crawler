import csv
from pathlib import Path

from django.contrib import admin
from django.contrib import messages
from django.http import HttpResponse
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.html import format_html

from .models import CrawlJob, Organ, Specimen
from .services.jobs import CrawlJobService
from .services.pagination import paginate_keyset


@admin.action(description="Export selected specimens to CSV")
def export_specimens_to_csv(modeladmin, request, queryset):
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="specimens.csv"'

    writer = csv.writer(response)
    writer.writerow(
        [
            "Organ Name",
            "Specimen Name",
            "Site Name",
            "Laterality",
            "Specimen Type",
            "Specimen Size",
            "Source Site",
        ]
    )

    for specimen in queryset.select_related("organ"):
        writer.writerow(
            [
                specimen.organ.name,
                specimen.specimen_name,
                specimen.site_name,
                specimen.laterality,
                specimen.specimen_type,
                specimen.specimen_size or "",
                specimen.source_site,
            ]
        )

    return response


@admin.register(Organ)
class OrganAdmin(admin.ModelAdmin):
    list_display = ("name", "specimen_count")
    search_fields = ("name",)

    @admin.display(description="Specimens")
    def specimen_count(self, obj):
        return obj.specimens.count()


@admin.register(Specimen)
class SpecimenAdmin(admin.ModelAdmin):
    list_display = (
        "specimen_name",
        "organ",
        "site_name",
        "laterality",
        "specimen_type",
        "source_site",
        "specimen_size",
        "source_file",
        "created_at",
    )
    search_fields = ("specimen_name", "site_name", "laterality", "organ__name", "source_site")
    list_filter = ("specimen_type", "organ", "source_site")
    autocomplete_fields = ("organ",)
    actions = (export_specimens_to_csv,)
    change_list_template = "admin/pathology/specimen/change_list.html"

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "cursor-browser/",
                self.admin_site.admin_view(self.cursor_browser_view),
                name="pathology_specimen_cursor_browser",
            ),
        ]
        return custom_urls + urls

    def cursor_browser_view(self, request):
        queryset = Specimen.objects.select_related("organ").order_by("id")
        page_size = min(max(int(request.GET.get("page_size", 50)), 1), 200)
        after = request.GET.get("after")
        before = request.GET.get("before")
        page = paginate_keyset(
            queryset,
            page_size=page_size,
            after=after,
            before=before,
        )
        context = {
            **self.admin_site.each_context(request),
            "title": "Specimen Cursor Browser",
            "opts": self.model._meta,
            "page": page,
            "page_size": page_size,
            "has_add_permission": self.has_add_permission(request),
            "changelist_url": reverse("admin:pathology_specimen_changelist"),
        }
        return TemplateResponse(
            request,
            "admin/pathology/specimen/cursor_browser.html",
            context,
        )


@admin.action(description="Start selected crawl jobs")
def start_crawl_jobs(modeladmin, request, queryset):
    service = CrawlJobService()
    started = 0
    for job in queryset:
        if job.status == CrawlJob.Status.RUNNING:
            continue
        service.start_job(job)
        started += 1
    modeladmin.message_user(
        request,
        (
            f"Started {started} crawl job(s). "
            "The crawler runs in the background; refresh the Crawl Jobs list "
            "to see created, updated, and skipped counts."
        ),
        level=messages.INFO,
    )


@admin.action(description="Request stop for selected crawl jobs")
def stop_crawl_jobs(modeladmin, request, queryset):
    service = CrawlJobService()
    updated = 0
    for job in queryset:
        service.request_stop(job)
        updated += 1
    modeladmin.message_user(
        request,
        f"Requested stop for {updated} crawl job(s).",
        level=messages.WARNING,
    )


@admin.register(CrawlJob)
class CrawlJobAdmin(admin.ModelAdmin):
    list_display = (
        "display_name",
        "crawl_source",
        "status",
        "open_monitor",
        "limit",
        "destination_dir",
        "process_id",
        "records_created",
        "records_updated",
        "records_skipped",
        "created_at",
        "started_at",
        "finished_at",
    )
    search_fields = ("name", "crawl_source", "destination_dir", "error_message")
    list_filter = ("crawl_source", "status", "created_at", "started_at", "finished_at")
    change_list_template = "admin/pathology/crawljob/change_list.html"
    readonly_fields = (
        "process_id",
        "total_links",
        "files_downloaded",
        "records_created",
        "records_updated",
        "records_skipped",
        "error_message",
        "created_at",
        "started_at",
        "finished_at",
        "monitor_link",
    )
    actions = (start_crawl_jobs, stop_crawl_jobs)

    fieldsets = (
        (
            "Configuration",
            {
                "fields": (
                    "name",
                    "crawl_source",
                    "status",
                    "limit",
                    "destination_dir",
                    "stop_requested",
                ),
            },
        ),
        (
            "Progress",
            {
                "fields": (
                    "monitor_link",
                    "process_id",
                    "total_links",
                    "files_downloaded",
                    "records_created",
                    "records_updated",
                    "records_skipped",
                    "error_message",
                ),
            },
        ),
        (
            "Timing",
            {
                "fields": ("created_at", "started_at", "finished_at"),
            },
        ),
    )

    @admin.display(description="Job")
    def display_name(self, obj):
        return obj.name or f"Crawl Job #{obj.pk}"

    @admin.display(description="Monitor")
    def open_monitor(self, obj):
        if not obj.pk:
            return "-"
        url = reverse("admin:pathology_crawljob_monitor", args=[obj.pk])
        return format_html('<a href="{}">Open Monitor</a>', url)

    @admin.display(description="Live Monitor")
    def monitor_link(self, obj):
        if not obj.pk:
            return "Save this job to enable monitoring."
        url = reverse("admin:pathology_crawljob_monitor", args=[obj.pk])
        return format_html('<a href="{}">Open live monitor</a>', url)

    def save_model(self, request, obj, form, change):
        if obj.destination_dir:
            obj.destination_dir = str(Path(obj.destination_dir))
        super().save_model(request, obj, form, change)

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "monitor/",
                self.admin_site.admin_view(self.monitor_index_view),
                name="pathology_crawljob_monitor_index",
            ),
            path(
                "monitor/<int:job_id>/",
                self.admin_site.admin_view(self.monitor_detail_view),
                name="pathology_crawljob_monitor",
            ),
        ]
        return custom_urls + urls

    def monitor_index_view(self, request):
        jobs = CrawlJob.objects.all()[:25]
        context = {
            **self.admin_site.each_context(request),
            "title": "Crawl Job Monitor",
            "opts": self.model._meta,
            "jobs": jobs,
        }
        return TemplateResponse(
            request,
            "admin/pathology/crawljob/monitor_index.html",
            context,
        )

    def monitor_detail_view(self, request, job_id: int):
        job = CrawlJob.objects.get(pk=job_id)
        context = {
            **self.admin_site.each_context(request),
            "title": f"Crawl Monitor: {job.name or f'Job #{job.pk}'}",
            "opts": self.model._meta,
            "job": job,
            "changelist_url": reverse("admin:pathology_crawljob_changelist"),
            "change_url": reverse("admin:pathology_crawljob_change", args=[job.pk]),
        }
        return TemplateResponse(
            request,
            "admin/pathology/crawljob/monitor_detail.html",
            context,
        )


admin.site.site_header = "Pathology Data Administration"
admin.site.site_title = "Pathology Admin"
admin.site.index_title = "CAP Protocol Data"

# Register your models here.
