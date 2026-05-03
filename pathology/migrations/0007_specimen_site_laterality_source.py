from django.db import migrations, models


def populate_source_site(apps, schema_editor):
    Specimen = apps.get_model("pathology", "Specimen")
    Specimen.objects.filter(source_site="").update(source_site="cap.org")


class Migration(migrations.Migration):

    dependencies = [
        ("pathology", "0006_alter_crawljob_limit"),
    ]

    operations = [
        migrations.AddField(
            model_name="specimen",
            name="laterality",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="specimen",
            name="site_name",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="specimen",
            name="source_site",
            field=models.CharField(
                choices=[
                    ("cap.org", "CAP"),
                    ("pathologyoutlines.com", "Pathology Outlines"),
                ],
                default="cap.org",
                max_length=64,
            ),
        ),
        migrations.AddIndex(
            model_name="specimen",
            index=models.Index(fields=["source_site"], name="pathology_s_source__18d9cb_idx"),
        ),
        migrations.RunPython(populate_source_site, migrations.RunPython.noop),
    ]
