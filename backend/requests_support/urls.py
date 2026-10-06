from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    SupportDashboardView,
    SupportMeView,
    SupportTicketViewSet,
    assignable_users,
)

router = DefaultRouter()
router.register(r"support/tickets", SupportTicketViewSet, basename="support-ticket")

urlpatterns = [
    path("support/me/", SupportMeView.as_view(), name="support-me"),
    path("support/dashboard/", SupportDashboardView.as_view(), name="support-dashboard"),
    path("support/assignable-users/", assignable_users, name="support-assignable-users"),
    path("", include(router.urls)),
]
