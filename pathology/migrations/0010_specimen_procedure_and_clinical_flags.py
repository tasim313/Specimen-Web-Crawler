from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("pathology", "0009_rename_pathology_s_source__18d9cb_idx_pathology_s_source__b4a9b5_idx"),
    ]

    operations = [
        migrations.AddField(
            model_name="specimen",
            name="procedure_name",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="specimen",
            name="is_biopsy",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="specimen",
            name="is_resection",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="specimen",
            name="is_cytology",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="specimen",
            name="is_histopathology",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="specimen",
            name="is_ihc_applicable",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="specimen",
            name="is_molecular_applicable",
            field=models.BooleanField(default=False),
        ),
    ]
