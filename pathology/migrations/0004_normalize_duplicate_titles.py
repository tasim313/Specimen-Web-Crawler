from django.db import migrations


def dedupe_normalized_titles(apps, schema_editor):
    Specimen = apps.get_model("pathology", "Specimen")
    grouped = {}

    for specimen in Specimen.objects.all().order_by("id"):
        normalized_name = "".join(
            char for char in specimen.specimen_name.lower() if char.isalnum()
        )
        key = (specimen.organ_id, normalized_name)
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
                keeper.specimen_name = candidate.specimen_name
                keeper.source_file = candidate.source_file
            candidate.delete()
        keeper.save(
            update_fields=[
                "specimen_name",
                "specimen_type",
                "specimen_size",
                "source_file",
            ]
        )


class Migration(migrations.Migration):
    dependencies = [
        (
            "pathology",
            "0003_rename_pathology_s_specime_b2402e_idx_pathology_s_specime_43187c_idx_and_more",
        ),
    ]

    operations = [
        migrations.RunPython(dedupe_normalized_titles, migrations.RunPython.noop),
    ]
