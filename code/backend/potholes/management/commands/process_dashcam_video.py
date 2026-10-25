"""
Django management command to process dashcam videos and sync to database
"""
import os
import csv
import tempfile
from potholes.frame_storage import save_frame_base64
from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
from potholes.models import Pothole
from dashcam_processor.main import main as process_video
from datetime import datetime
import base64
from django.core.files.base import ContentFile
from road_observations.dashcam_ingest import (
    ingest_per_detection_records,
    read_per_detection_csv,
)


class Command(BaseCommand):
    help = 'Process dashcam video and GPS files to detect potholes and sync to database'

    def add_arguments(self, parser):
        parser.add_argument('--video-path', type=str, required=True,
                          help='Path to the video file')
        parser.add_argument('--gps-directory', type=str, required=True,
                          help='Directory containing GPS .git files')
        parser.add_argument('--distance-threshold', type=float, default=2.5,
                          help='Minimum distance in meters between stored potholes')
        parser.add_argument('--owner-id', type=int, default=None,
                          help='Authenticated owner ID for modern per-detection ingestion')
        parser.add_argument('--source-identifier', type=str, default=None,
                          help='Generated video upload identifier for idempotent ingestion')

    def handle(self, *args, **options):
        video_path = options['video_path']
        gps_directory = options['gps_directory']
        distance_threshold = options['distance_threshold']
        owner_id = options.get('owner_id')
        source_identifier = options.get('source_identifier') or os.path.splitext(os.path.basename(video_path))[0]

        self.stdout.write(
            self.style.SUCCESS(f'Starting video processing: {video_path}')
        )

        # Create temporary directory for output
        with tempfile.TemporaryDirectory() as temp_dir:
            output_video_path = os.path.join(temp_dir, "output_with_detections.mp4")

            try:
                # Process video using the dashcam pipeline
                process_video(
                    video_path=video_path,
                    git_directory=gps_directory,
                    output_video_path=output_video_path,
                    output_dir=temp_dir,
                    distance_threshold_m=distance_threshold,
                    source_identifier=source_identifier,
                )

                # Validate modern rows completely before either record table is changed.
                csv_path = os.path.join(temp_dir, "pothole_gps_merged.csv")
                if not os.path.exists(csv_path):
                    raise CommandError('The dashcam processor did not produce its expected results file.')
                per_detection_path = os.path.join(temp_dir, "routiq_per_detection.csv")
                if owner_id is not None:
                    if not os.path.exists(per_detection_path):
                        raise CommandError('The dashcam processor did not produce its per-detection results file.')
                    records = read_per_detection_csv(per_detection_path)

                # Preserve the existing aggregate legacy workflow.
                self.sync_csv_to_database(csv_path)
                if owner_id is not None:
                    result = ingest_per_detection_records(
                        owner_id=owner_id,
                        source_identifier=source_identifier,
                        records=records,
                    )
                    self.stdout.write(self.style.SUCCESS(
                        f"Modern observations: {result['created']} created, {result['duplicates']} duplicates skipped."
                    ))
                self.stdout.write(self.style.SUCCESS('Dashcam results were synced to the legacy pothole records.'))

            except CommandError:
                raise
            except Exception as exc:
                raise CommandError('Dashcam processing failed. Review the server logs for details.') from exc

    def sync_csv_to_database(self, csv_path):
        """Sync CSV data to Django database"""
        created_count = 0
        updated_count = 0

        with open(csv_path, 'r', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile)

            for row in reader:
                try:
                    # Parse data from CSV
                    latitude = float(row['Latitude'])
                    longitude = float(row['Longitude'])
                    pothole_count = int(row['Pothole_Count'])
                    grade = row['Pothole_Grade']
                    frame_data = row.get('Frame_Data', '')
                    frame_number = int(row['Frame']) if row['Frame'] else None

                    # Parse datetime
                    date_str = row['Date']
                    time_str = row['Time']
                    datetime_str = f"{date_str} {time_str}"
                    timestamp = datetime.strptime(datetime_str, "%m/%d/%Y %I:%M:%S %p")

                    # Map grade to severity
                    severity_mapping = {
                        'LOW': 'low',
                        'MEDIUM': 'medium',
                        'HIGH': 'high',
                        'CRITICAL': 'critical'
                    }
                    severity = severity_mapping.get(grade.upper(), 'medium')

                    # Check if pothole already exists at this location and time
                    existing_pothole = Pothole.objects.filter(
                        latitude=latitude,
                        longitude=longitude,
                        timestamp=timestamp
                    ).first()

                    if existing_pothole:
                        # Update existing pothole
                        existing_pothole.num_potholes = pothole_count
                        existing_pothole.severity = severity
                        existing_pothole.frame_number = frame_number
                        if frame_data:
                            save_frame_base64(
                                existing_pothole, frame_data, frame_number, save=False,
                            )
                        existing_pothole.save()
                        updated_count += 1
                    else:
                        # Create new pothole
                        pothole = Pothole(
                            latitude=latitude,
                            longitude=longitude,
                            num_potholes=pothole_count,
                            severity=severity,
                            timestamp=timestamp,
                            frame_number=frame_number,
                            status='reported',
                            description=f"Detected by dashcam processing - Grade: {grade}"
                        )

                        pothole.save()
                        if frame_data:
                            save_frame_base64(pothole, frame_data, frame_number)

                        created_count += 1

                except Exception as e:
                    self.stdout.write(
                        self.style.WARNING(f'Error processing row: {str(e)}')
                    )
                    continue

        self.stdout.write(
            self.style.SUCCESS(
                f'Database sync complete: {created_count} created, {updated_count} updated'
            )
        )
