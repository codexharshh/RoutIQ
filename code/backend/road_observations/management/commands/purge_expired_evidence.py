"""Report or purge expired private image evidence while retaining observations."""
from django.core.management.base import BaseCommand
from django.conf import settings
from django.db.models import Q
from django.utils import timezone
from datetime import timedelta

from road_observations.models import InspectionSession


class Command(BaseCommand):
    help = "Report expired evidence; pass --execute to delete files and clear references."

    def add_arguments(self, parser):
        parser.add_argument(
            "--execute",
            action="store_true",
            help="Delete expired evidence files. Without this flag, only report the count.",
        )

    def handle(self, *args, **options):
        retention_days = max(1, int(getattr(settings, "ROUTIQ_EVIDENCE_RETENTION_DAYS", 30)))
        expiry_cutoff = timezone.now()
        expired = InspectionSession.objects.filter(
            Q(evidence_expires_at__lte=expiry_cutoff)
            | Q(evidence_expires_at__isnull=True, created_at__lte=expiry_cutoff - timedelta(days=retention_days))
        ).exclude(image_evidence="")
        count = expired.count()
        if not options["execute"]:
            self.stdout.write(f"{count} expired evidence file(s) are eligible for deletion; no files changed.")
            return

        deleted = 0
        for session in expired.iterator():
            session.image_evidence.delete(save=False)
            session.evidence_expires_at = None
            session.save(update_fields=["image_evidence", "evidence_expires_at"])
            deleted += 1
        self.stdout.write(f"Deleted {deleted} expired evidence file(s); observation records were retained.")
