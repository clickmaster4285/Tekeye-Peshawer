from django.urls import path

from .views import (
    CallMetadataBatchView,
    CallsView,
    ConsentView,
    DataCategoriesView,
    MeView,
    PolicyCurrentView,
    RecordingPlaybackView,
    RecordingStreamView,
    RecordingUploadCompleteView,
    RecordingUploadRequestView,
    RecordingsView,
)

# Mounted under /api/v1/employee-monitor/
urlpatterns = [
    path("me/", MeView.as_view(), name="monitor-me"),
    path("policy/current/", PolicyCurrentView.as_view(), name="monitor-policy-current"),
    path("consents/", ConsentView.as_view(), name="monitor-consents"),
    path("consents/current/", ConsentView.as_view(), name="monitor-consents-current"),
    path("privacy/data-categories/", DataCategoriesView.as_view(), name="monitor-data-categories"),
    path("calls/", CallsView.as_view(), name="monitor-calls"),
    path("calls/metadata/batch/", CallMetadataBatchView.as_view(), name="monitor-calls-ingest"),
    path("recordings/", RecordingsView.as_view(), name="monitor-recordings"),
    path("recordings/uploads/", RecordingUploadRequestView.as_view(), name="monitor-recording-upload"),
    path("recordings/uploads/<uuid:recording_id>/complete/", RecordingUploadCompleteView.as_view(), name="monitor-recording-upload-complete"),
    path("recordings/stream/", RecordingStreamView.as_view(), name="monitor-recording-stream"),
    path("recordings/<uuid:recording_id>/playback/", RecordingPlaybackView.as_view(), name="monitor-recording-playback"),
]
