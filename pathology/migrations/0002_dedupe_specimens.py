from django.db import migrations, models


def dedupe_specimens(apps, schema_editor):
    Specimen = apps.get_model("pathology", "Specimen")
    grouped = {}

    for specimen in Specimen.objects.all().order_by("id"):
        key = (specimen.organ_id, specimen.specimen_name)
        grouped.setdefault(key, []).append(specimen)

    for duplicates in grouped.values():
        if len(duplicates) < 2:
            continue

        keeper = duplicates[0]
        for candidate in duplicates[1:]:
            if keeper.specimen_type == "Unknown" and candidate.specimen_type != "Unknown":
                keeper.specimen_type = candidate.specimen_type
            if not keeper.specimen_size and candidate.specimen_size:
                keeper.specimen_size = candidate.specimen_size
            if keeper.source_file.lower().endswith(".pdf") and candidate.source_file.lower().endswith(".docx"):
                keeper.source_file = candidate.source_file
            candidate.delete()
        keeper.save(update_fields=["specimen_type", "specimen_size", "source_file"])


class Migration(migrations.Migration):
    dependencies = [
        ("pathology", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(dedupe_specimens, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="specimen",
            name="source_file",
            field=models.CharField(max_length=255),
        ),
        migrations.AddConstraint(
            model_name="specimen",
            constraint=models.UniqueConstraint(
                fields=("organ", "specimen_name"),
                name="unique_specimen_per_organ",
            ),
        ),
    ]
