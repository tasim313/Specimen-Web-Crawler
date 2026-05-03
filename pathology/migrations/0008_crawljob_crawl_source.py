from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("pathology", "0007_specimen_site_laterality_source"),
    ]

    operations = [
        migrations.AddField(
            model_name="crawljob",
            name="crawl_source",
            field=models.CharField(
                choices=[
                    ("cap.org", "CAP"),
                    ("pathologyoutlines.com", "Pathology Outlines"),
                    ("both", "Both Sources"),
                ],
                default="cap.org",
                max_length=64,
            ),
        ),
    ]
