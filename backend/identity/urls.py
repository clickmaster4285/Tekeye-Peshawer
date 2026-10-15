from django.urls import path

from identity.views import (
    ClusterAssignView,
    ClusterDetailView,
    ClusterDismissView,
    ClusterListView,
    ClusterRunView,
    DecisionApproveView,
    DecisionDetailView,
    DecisionListView,
    DecisionRejectView,
    GalleryEntryView,
    IdentityProfileListView,
    StaffIdentityView,
    StaffModeView,
)

urlpatterns = [
    path("profiles/", IdentityProfileListView.as_view(), name="identity-profiles"),
    path("staff/<int:staff_id>/", StaffIdentityView.as_view(), name="identity-staff"),
    path("staff/<int:staff_id>/mode/", StaffModeView.as_view(), name="identity-staff-mode"),
    path("gallery/<int:entry_id>/", GalleryEntryView.as_view(), name="identity-gallery-entry"),
    path("decisions/", DecisionListView.as_view(), name="identity-decisions"),
    path("decisions/<int:decision_id>/", DecisionDetailView.as_view(), name="identity-decision"),
    path("decisions/<int:decision_id>/approve/", DecisionApproveView.as_view(), name="identity-decision-approve"),
    path("decisions/<int:decision_id>/reject/", DecisionRejectView.as_view(), name="identity-decision-reject"),
    path("clusters/", ClusterListView.as_view(), name="identity-clusters"),
    path("clusters/run/", ClusterRunView.as_view(), name="identity-clusters-run"),
    path("clusters/<int:cluster_id>/", ClusterDetailView.as_view(), name="identity-cluster"),
    path("clusters/<int:cluster_id>/assign/", ClusterAssignView.as_view(), name="identity-cluster-assign"),
    path("clusters/<int:cluster_id>/dismiss/", ClusterDismissView.as_view(), name="identity-cluster-dismiss"),
]
