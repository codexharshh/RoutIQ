from django.urls import path
from .location_api import ObservationLocationUpdateView
from .temporal_api import TemporalEvidenceReviewView, SessionEvidenceComparisonView
from .views import (
    ObservationListCreateView,
    SessionListCreateView,
    DetectImageView,
    ObservationAssessmentView,
    RoadDamageMapView,
    RoadDamageStatsView,
    SessionEvidenceView,
    DetectorReadinessView,
)

app_name = "road_observations"
urlpatterns = [
    path("", ObservationListCreateView.as_view(), name="road-observations-list"),
    path("sessions/", SessionListCreateView.as_view(), name="sessions"),
    path("detect/", DetectImageView.as_view(), name="detect-image"),
    path("detector-status/", DetectorReadinessView.as_view(), name="detector-status"),
    path("sessions/<int:pk>/evidence/", SessionEvidenceView.as_view(), name="session-evidence"),
    path("session-evidence-review/", SessionEvidenceComparisonView.as_view(), name="session-evidence-review"),
    path('temporal-review/', TemporalEvidenceReviewView.as_view(), name='temporal-review'),
    path("map/", RoadDamageMapView.as_view(), name="map"),
    path("stats/", RoadDamageStatsView.as_view(), name="stats"),
    path("<int:pk>/location/", ObservationLocationUpdateView.as_view(), name="update-location"),
    path("<int:pk>/assess/", ObservationAssessmentView.as_view(), name="assess"),
]
