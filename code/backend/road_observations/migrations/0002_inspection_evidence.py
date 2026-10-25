from django.db import migrations, models
import road_observations.storage


class Migration(migrations.Migration):

    dependencies = [
        ("road_observations", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="inspectionsession",
            name="image_evidence",
            field=models.ImageField(
                blank=True,
                storage=road_observations.storage.PrivateEvidenceStorage(),
                upload_to="sessions/",
            ),
        ),
        migrations.AddField(
            model_name="inspectionsession",
            name="evidence_expires_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
