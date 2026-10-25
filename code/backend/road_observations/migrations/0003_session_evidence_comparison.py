# Generated as an additive migration for the private image-comparison review workflow.
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("road_observations", "0002_inspection_evidence"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="SessionEvidenceComparison",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("method", models.CharField(default="orb_homography_ssim_v1", max_length=80)),
                ("status", models.CharField(default="insufficient_evidence", max_length=40)),
                ("evidence", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("owner", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="session_evidence_comparisons", to=settings.AUTH_USER_MODEL)),
                ("session_a", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="visual_comparisons_as_a", to="road_observations.inspectionsession")),
                ("session_b", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="visual_comparisons_as_b", to="road_observations.inspectionsession")),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.AddConstraint(
            model_name="sessionevidencecomparison",
            constraint=models.UniqueConstraint(fields=("session_a", "session_b", "method"), name="uniq_routiq_session_visual_pair"),
        ),
    ]
