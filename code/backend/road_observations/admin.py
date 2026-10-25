from django.contrib import admin
from .models import (
    InspectionSession, DamageInstance, DamageObservation,
    ObservationMatch, DamageStatusAssessment,
)

admin.site.register(InspectionSession)
admin.site.register(DamageInstance)
admin.site.register(DamageObservation)
admin.site.register(ObservationMatch)
admin.site.register(DamageStatusAssessment)
