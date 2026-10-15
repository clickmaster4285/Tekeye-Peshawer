from django.urls import path

from city_sync.sites_api import (
    SyncSiteDetailView,
    SyncSiteFullHistoryView,
    SyncSiteRotateKeyView,
    SyncSitesView,
    SyncSiteTestView,
)

from city_sync.views import (
    CityStatusListView,
    MediaChunkView,
    MediaCompleteView,
    MediaInitView,
    NodeIdentityView,
    ReferencePullView,
    SyncCursorView,
    SyncEventsView,
    SyncHeartbeatView,
)

urlpatterns = [
    path("sync/v1/identity/", NodeIdentityView.as_view(), name="sync-identity"),
    path("sync/v1/events", SyncEventsView.as_view(), name="sync-events"),
    path("sync/v1/events/", SyncEventsView.as_view(), name="sync-events-slash"),
    path("sync/v1/heartbeat", SyncHeartbeatView.as_view(), name="sync-heartbeat"),
    path("sync/v1/heartbeat/", SyncHeartbeatView.as_view(), name="sync-heartbeat-slash"),
    path("sync/v1/cursor", SyncCursorView.as_view(), name="sync-cursor"),
    path("sync/v1/cursor/", SyncCursorView.as_view(), name="sync-cursor-slash"),
    path("sync/v1/reference", ReferencePullView.as_view(), name="sync-reference"),
    path("sync/v1/reference/", ReferencePullView.as_view(), name="sync-reference-slash"),
    path("sync/v1/media/init", MediaInitView.as_view(), name="sync-media-init"),
    path("sync/v1/media/init/", MediaInitView.as_view(), name="sync-media-init-slash"),
    path("sync/v1/media/<uuid:media_id>/chunk", MediaChunkView.as_view(), name="sync-media-chunk"),
    path("sync/v1/media/<uuid:media_id>/chunk/", MediaChunkView.as_view(), name="sync-media-chunk-slash"),
    path(
        "sync/v1/media/<uuid:media_id>/complete",
        MediaCompleteView.as_view(),
        name="sync-media-complete",
    ),
    path(
        "sync/v1/media/<uuid:media_id>/complete/",
        MediaCompleteView.as_view(),
        name="sync-media-complete-slash",
    ),
    path("sync/v1/cities/", CityStatusListView.as_view(), name="sync-cities"),
    # HQ Locations admin page (Stage 2)
    path("sync/v1/sites/", SyncSitesView.as_view(), name="sync-sites"),
    path("sync/v1/sites/<str:code>/", SyncSiteDetailView.as_view(), name="sync-site-detail"),
    path("sync/v1/sites/<str:code>/rotate-key/", SyncSiteRotateKeyView.as_view(), name="sync-site-rotate-key"),
    path("sync/v1/sites/<str:code>/test/", SyncSiteTestView.as_view(), name="sync-site-test"),
    path(
        "sync/v1/sites/<str:code>/full-history/",
        SyncSiteFullHistoryView.as_view(),
        name="sync-site-full-history",
    ),
]
