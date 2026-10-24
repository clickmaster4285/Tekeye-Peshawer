from __future__ import annotations

from rest_framework import serializers

from cameras.models import DetectionEvent

from .models import GlobalObject, MotionClip, ObjectCameraTrack, ObjectMovement, ObjectVisit


def _media_url(path: str, request=None) -> str:
    path = (path or "").strip().replace("\\", "/")
    if not path:
        return ""
    if path.startswith("http://") or path.startswith("https://"):
        return path
    if path.startswith("/media/"):
        rel = path
    elif path.startswith("media/"):
        rel = f"/{path}"
    elif path.startswith("/"):
        rel = path
    else:
        rel = f"/media/{path.lstrip('/')}"
    if request is not None:
        return request.build_absolute_uri(rel)
    return rel


def _detection_clip_url(detection_event_id: int | None, request=None) -> str:
    if not detection_event_id:
        return ""
    event = (
        DetectionEvent.objects.filter(pk=detection_event_id)
        .only("clip")
        .first()
    )
    if event is None or not event.clip:
        return ""
    try:
        url = event.clip.url
    except Exception:
        return ""
    if request is not None and url.startswith("/"):
        return request.build_absolute_uri(url)
    return url


class ObjectVisitSerializer(serializers.ModelSerializer):
    camera_name = serializers.CharField(source="camera.name", read_only=True, default="")
    camera_code = serializers.CharField(source="camera.code", read_only=True, default="")
    global_code = serializers.CharField(source="global_object.code", read_only=True)
    global_uuid = serializers.UUIDField(source="global_object.uuid", read_only=True)
    object_type = serializers.CharField(source="global_object.object_type", read_only=True)
    class_name = serializers.CharField(source="global_object.class_name", read_only=True)
    snapshot_url = serializers.SerializerMethodField()

    class Meta:
        model = ObjectVisit
        fields = [
            "id",
            "global_object",
            "global_code",
            "global_uuid",
            "object_type",
            "class_name",
            "camera",
            "camera_name",
            "camera_code",
            "local_track_id",
            "status",
            "entry_at",
            "last_seen_at",
            "exit_at",
            "duration_seconds",
            "detection_event_id",
            "snapshot_path",
            "snapshot_url",
            "bbox",
            "confidence",
            "created_at",
        ]

    def get_snapshot_url(self, obj: ObjectVisit) -> str:
        request = self.context.get("request")
        if obj.snapshot_path:
            return _media_url(obj.snapshot_path, request)
        return _detection_clip_url(obj.detection_event_id, request)


class ObjectCameraTrackSerializer(serializers.ModelSerializer):
    camera_name = serializers.CharField(source="camera.name", read_only=True, default="")

    class Meta:
        model = ObjectCameraTrack
        fields = [
            "id",
            "local_track_id",
            "camera",
            "camera_name",
            "status",
            "started_at",
            "ended_at",
            "last_bbox",
        ]


class GlobalObjectListSerializer(serializers.ModelSerializer):
    latest_camera_name = serializers.CharField(
        source="latest_camera.name", read_only=True, default=""
    )
    latest_camera_code = serializers.CharField(
        source="latest_camera.code", read_only=True, default=""
    )
    visit_count = serializers.IntegerField(read_only=True, required=False)
    active_visit = serializers.SerializerMethodField()
    duration_seconds = serializers.SerializerMethodField()
    snapshot_url = serializers.SerializerMethodField()
    is_present = serializers.SerializerMethodField()

    class Meta:
        model = GlobalObject
        fields = [
            "id",
            "uuid",
            "code",
            "object_type",
            "class_name",
            "label",
            "first_seen_at",
            "last_seen_at",
            "entry_at",
            "exit_at",
            "duration_seconds",
            "latest_camera",
            "latest_camera_name",
            "latest_camera_code",
            "visit_count",
            "active_visit",
            "is_present",
            "snapshot_url",
            "first_detection_event_id",
            "camera_history",
            "created_at",
            "updated_at",
        ]

    def get_duration_seconds(self, obj: GlobalObject) -> float:
        return float(obj.duration_seconds or 0.0)

    def get_is_present(self, obj: GlobalObject) -> bool:
        return obj.exit_at is None

    def get_active_visit(self, obj: GlobalObject) -> dict | None:
        visit = getattr(obj, "_active_visit", None)
        if visit is None:
            visit = (
                obj.visits.filter(status="active").order_by("-entry_at").first()
            )
        if visit is None:
            return None
        return ObjectVisitSerializer(visit, context=self.context).data

    def get_snapshot_url(self, obj: GlobalObject) -> str:
        request = self.context.get("request")
        if obj.snapshot_path:
            return _media_url(obj.snapshot_path, request)
        url = _detection_clip_url(obj.first_detection_event_id, request)
        if url:
            return url
        # Not obj.visits: the detail view prefetches visits with select_related("camera"),
        # which cannot be combined with .only()
        visit = (
            ObjectVisit.objects.filter(global_object=obj)
            .exclude(detection_event_id=None)
            .order_by("-entry_at")
            .only("detection_event_id", "snapshot_path")
            .first()
        )
        if visit is None:
            return ""
        if visit.snapshot_path:
            return _media_url(visit.snapshot_path, request)
        return _detection_clip_url(visit.detection_event_id, request)


def _file_url(field, request=None) -> str:
    if not field:
        return ""
    try:
        url = field.url
    except Exception:
        return ""
    if request is not None and url.startswith("/"):
        return request.build_absolute_uri(url)
    return url


class ObjectMovementSerializer(serializers.ModelSerializer):
    global_code = serializers.CharField(source="global_object.code", read_only=True, default="")
    global_uuid = serializers.UUIDField(source="global_object.uuid", read_only=True, default=None)
    object_type = serializers.CharField(source="global_object.object_type", read_only=True, default="")

    class Meta:
        model = ObjectMovement
        fields = [
            "id",
            "clip",
            "global_object",
            "global_code",
            "global_uuid",
            "object_type",
            "visit",
            "class_name",
            "ml_object_id",
            "local_track_id",
            "started_at",
            "ended_at",
            "still_moving",
            "duration_seconds",
            "from_bbox",
            "to_bbox",
            "distance_px",
            "distance_pct",
            "direction",
        ]


class MotionClipSerializer(serializers.ModelSerializer):
    camera_name = serializers.CharField(source="camera.name", read_only=True, default="")
    video_url = serializers.SerializerMethodField()
    poster_url = serializers.SerializerMethodField()
    end_frame_url = serializers.SerializerMethodField()
    movements = ObjectMovementSerializer(many=True, read_only=True)

    class Meta:
        model = MotionClip
        fields = [
            "id",
            "camera",
            "camera_name",
            "camera_key",
            "part",
            "started_at",
            "ended_at",
            "duration_seconds",
            "video_url",
            "poster_url",
            "end_frame_url",
            "source_width",
            "source_height",
            "clip_width",
            "clip_height",
            "fps",
            "size_bytes",
            "movements",
            "created_at",
        ]

    def get_video_url(self, obj: MotionClip) -> str:
        return _file_url(obj.video, self.context.get("request"))

    def get_poster_url(self, obj: MotionClip) -> str:
        return _file_url(obj.poster, self.context.get("request"))

    def get_end_frame_url(self, obj: MotionClip) -> str:
        return _file_url(obj.end_frame, self.context.get("request"))


class ObjectMovementWithClipSerializer(ObjectMovementSerializer):
    """A movement on the object page, carrying the clip it can be played from."""

    clip_detail = serializers.SerializerMethodField()

    class Meta(ObjectMovementSerializer.Meta):
        fields = ObjectMovementSerializer.Meta.fields + ["clip_detail"]

    def get_clip_detail(self, obj: ObjectMovement) -> dict:
        clip = obj.clip
        request = self.context.get("request")
        return {
            "id": clip.id,
            "camera_name": clip.camera.name if clip.camera_id and clip.camera else "",
            "started_at": clip.started_at,
            "duration_seconds": clip.duration_seconds,
            "part": clip.part,
            "video_url": _file_url(clip.video, request),
            "poster_url": _file_url(clip.poster, request),
            "end_frame_url": _file_url(clip.end_frame, request),
            "source_width": clip.source_width,
            "source_height": clip.source_height,
        }


class GlobalObjectDetailSerializer(GlobalObjectListSerializer):
    visits = ObjectVisitSerializer(many=True, read_only=True)
    tracks = ObjectCameraTrackSerializer(many=True, read_only=True)
    movements = serializers.SerializerMethodField()

    class Meta(GlobalObjectListSerializer.Meta):
        fields = GlobalObjectListSerializer.Meta.fields + [
            "track_history",
            "visits",
            "tracks",
            "movements",
            "metadata",
        ]

    def get_movements(self, obj: GlobalObject) -> list:
        rows = obj.movements.select_related("clip", "clip__camera").order_by("-started_at")[:100]
        return ObjectMovementWithClipSerializer(rows, many=True, context=self.context).data
