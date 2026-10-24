from django.urls import path

from .views import (
    GlobalObjectDetailAPIView,
    GlobalObjectListAPIView,
    MotionClipDetailAPIView,
    MotionClipListAPIView,
    ObjectTrackingLiveAPIView,
    ObjectTrackingSummaryAPIView,
    ObjectVisitListAPIView,
)

urlpatterns = [
    path("object-tracking/summary/", ObjectTrackingSummaryAPIView.as_view(), name="object-tracking-summary"),
    path("object-tracking/live/", ObjectTrackingLiveAPIView.as_view(), name="object-tracking-live"),
    path("object-tracking/objects/", GlobalObjectListAPIView.as_view(), name="object-tracking-objects"),
    path(
        "object-tracking/objects/<uuid:uuid>/",
        GlobalObjectDetailAPIView.as_view(),
        name="object-tracking-object-detail",
    ),
    path("object-tracking/visits/", ObjectVisitListAPIView.as_view(), name="object-tracking-visits"),
    path("object-tracking/motion-clips/", MotionClipListAPIView.as_view(), name="object-tracking-motion-clips"),
    path(
        "object-tracking/motion-clips/<int:pk>/",
        MotionClipDetailAPIView.as_view(),
        name="object-tracking-motion-clip-detail",
    ),
]
