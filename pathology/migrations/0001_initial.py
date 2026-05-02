from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Organ",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=100, unique=True)),
            ],
            options={"ordering": ["name"]},
        ),
        migrations.CreateModel(
            name="Specimen",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("specimen_name", models.TextField()),
                ("specimen_type", models.CharField(max_length=100)),
                ("specimen_size", models.TextField(blank=True, null=True)),
                ("source_file", models.CharField(max_length=255, unique=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("organ", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="specimens", to="pathology.organ")),
            ],
            options={"ordering": ["specimen_name"]},
        ),
        migrations.AddIndex(
            model_name="specimen",
            index=models.Index(fields=["specimen_type"], name="pathology_s_specime_b2402e_idx"),
        ),
        migrations.AddIndex(
            model_name="specimen",
            index=models.Index(fields=["source_file"], name="pathology_s_source__ee0ad2_idx"),
        ),
    ]
