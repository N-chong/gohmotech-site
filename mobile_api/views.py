from datetime import timedelta

from django.contrib.auth import authenticate, get_user_model
from django.core import signing
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Avg, Count, OuterRef, Prefetch, Q, Subquery
from django.http import FileResponse, Http404, HttpResponse
from django.utils import timezone
from rest_framework import generics, status
from rest_framework.authtoken.models import Token
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from feeding.models import FeedLevel
from iot.ble_services import build_tracking_snapshot
from iot.forms import GoatForm
from iot.goat_models import Goat, GoatImage, GoatWeightMeasurement, IPCamera
from iot.goat_photos import ANGLE_GUIDANCE, delete_goat_photo, save_standard_photo, validated_goat_image
from iot.models import ActuatorState, Device, SensorReading, SensorReadingSummary
from iot.status_utils import controller_status, device_last_seen, is_device_online
from marketplace.auth import can_manage_farm, get_system_role, has_farm_access
from security.models import Notification, PersonDetection

from .permissions import HasActiveFarmAccess
from .serializers import CameraSerializer, GoatDetailSerializer, GoatListSerializer


TICKET_SALT = "gohmotech.mobile.ticket.v1"


def user_payload(user):
    return {
        "id": user.pk,
        "username": user.get_username(),
        "email": user.email,
        "display_name": user.get_full_name() or user.get_username(),
        "role": get_system_role(user),
        "permissions": {
            "farm_access": has_farm_access(user),
            "manage_farm": get_system_role(user) in {"admin", "farm_owner"},
            "marketplace_access": True,
        },
    }


class LoginThrottle(AnonRateThrottle):
    rate = "10/minute"


class LoginView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [LoginThrottle]

    def post(self, request):
        username = str(request.data.get("username", "")).strip()
        password = str(request.data.get("password", ""))
        if not username or not password:
            return Response({"detail": "Username and password are required."}, status=400)
        user = authenticate(request=request, username=username, password=password)
        if user is None:
            return Response({"detail": "Invalid username or password."}, status=400)
        if not user.is_active:
            return Response({"detail": "This account is inactive."}, status=403)
        if not can_manage_farm(user):
            return Response({'detail': 'Farm owner access is required.'}, status=403)
        token, _ = Token.objects.get_or_create(user=user)
        return Response({"token": token.key, "user": user_payload(user)})


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        Token.objects.filter(user=request.user).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(APIView):
    permission_classes = [HasActiveFarmAccess]

    def get(self, request):
        return Response(user_payload(request.user))


class RealtimeTicketView(APIView):
    permission_classes = [HasActiveFarmAccess]

    def post(self, request):
        purpose = request.data.get("purpose", "websocket")
        if purpose not in {"websocket", "camera"}:
            return Response({"detail": "Unsupported ticket purpose."}, status=400)
        camera_id = request.data.get("camera_id")
        if purpose == "camera":
            if not camera_id or not IPCamera.objects.filter(pk=camera_id, is_active=True).exists():
                return Response({"detail": "Active camera not found."}, status=404)
        value = signing.dumps(
            {"user_id": request.user.pk, "purpose": purpose, "camera_id": camera_id},
            salt=TICKET_SALT,
            compress=True,
        )
        return Response({"ticket": value, "expires_in": 60})


class DashboardView(APIView):
    permission_classes = [HasActiveFarmAccess]

    def get(self, request):
        now = timezone.now()
        controller = controller_status()
        latest = SensorReading.objects.select_related("device").order_by("-timestamp").first()
        environment_online = bool(latest and is_device_online(latest.device, window_seconds=30 * 60))
        environment_last_seen = device_last_seen(latest.device) if latest else None
        feed = FeedLevel.objects.select_related("feeder").order_by("-updated_at").first()
        actuators = list(ActuatorState.objects.select_related("device").all())
        door = next((item for item in actuators if item.actuator_type == "door"), None)
        light = next((item for item in actuators if item.actuator_type == "light"), None)
        active_devices = Device.objects.filter(is_active=True)
        online_devices = sum(1 for device in active_devices if is_device_online(device))
        alerts = (
            Notification.objects.filter(is_resolved=False).order_by("-created_at")[:5]
            if can_manage_farm(request.user) else []
        )
        cameras = IPCamera.objects.filter(is_active=True)
        return Response({
            "generated_at": now,
            "system": {
                "online": controller["online"],
                "controller_online": controller["online"],
                "controller_last_seen": controller["last_seen"],
                "iot_online": online_devices,
                "iot_total": active_devices.count(),
                "cameras_online": cameras.filter(status="active").count(),
                "cameras_total": cameras.count(),
            },
            "environment": {
                "temperature": latest.temperature if latest else None,
                "humidity": latest.humidity if latest else None,
                "light_level": latest.light_level_percentage if latest else None,
                "online": environment_online,
                "last_seen": environment_last_seen,
                "updated_at": latest.timestamp if latest else None,
            },
            "feed": {
                "percentage": (feed.percentage if feed and feed.percentage is not None else (feed.percentage_full if feed else None)),
                "is_low": feed.is_low if feed else None,
                "updated_at": feed.updated_at if feed else None,
            },
            "goats": {"registered": Goat.objects.filter(is_active=True, record_source=Goat.SMART_FARM).count()},
            "automation": {
                "door": {"id": door.pk, "state": door.current_state, "mode": door.mode, "updated_at": door.last_changed_at} if door else None,
                "light": {"id": light.pk, "state": light.current_state, "mode": light.mode, "updated_at": light.last_changed_at} if light else None,
            },
            "alerts": [{
                "id": item.pk, "title": item.title, "severity": item.severity,
                "type": item.notification_type, "created_at": item.created_at,
            } for item in alerts],
        })


class EnvironmentHistoryView(APIView):
    """Bounded, token-authenticated history for the dashboard environment device."""

    permission_classes = [HasActiveFarmAccess]
    HOURS = {24, 168}
    SENSOR_TYPES = ("temperature", "humidity", "light_level_percentage")

    def get(self, request):
        try:
            hours = int(request.query_params.get("hours", 24))
        except (TypeError, ValueError):
            return Response({"detail": "Hours must be 24 or 168."}, status=400)
        if hours not in self.HOURS:
            return Response({"detail": "Hours must be 24 or 168."}, status=400)

        latest = SensorReading.objects.select_related("device").order_by("-timestamp").first()
        generated_at = timezone.now()
        response = {
            "generated_at": generated_at,
            "hours": hours,
            "device": None,
            "series": {sensor_type: [] for sensor_type in self.SENSOR_TYPES},
        }
        if latest is None:
            return Response(response)

        response["device"] = {
            "id": latest.device_id,
            "device_id": latest.device.device_id,
            "name": latest.device.name,
        }
        summaries = SensorReadingSummary.objects.filter(
            device=latest.device,
            sensor_type__in=self.SENSOR_TYPES,
            period_end__gte=generated_at - timedelta(hours=hours),
        ).order_by("period_start", "sensor_type")
        for summary in summaries:
            response["series"][summary.sensor_type].append({
                "id": summary.id,
                "unit": summary.unit,
                "period_start": summary.period_start,
                "period_end": summary.period_end,
                "average": summary.average_value,
                "minimum": summary.minimum_value,
                "maximum": summary.maximum_value,
                "sample_count": summary.sample_count,
            })
        return Response(response)


class ReportSummaryView(APIView):
    """Server-authoritative herd and security aggregates for the owner app."""

    permission_classes = [HasActiveFarmAccess]
    HOURS = {24, 168}

    def get(self, request):
        try:
            hours = int(request.query_params.get("hours", 24))
        except (TypeError, ValueError):
            return Response({"detail": "Hours must be 24 or 168."}, status=400)
        if hours not in self.HOURS:
            return Response({"detail": "Hours must be 24 or 168."}, status=400)

        generated_at = timezone.now()
        herd = Goat.objects.filter(record_source=Goat.SMART_FARM)
        herd_total = herd.count()

        def distribution(field, choices):
            labels = dict(choices)
            rows = herd.values(field).annotate(count=Count("id")).order_by("-count", field)
            return [
                {
                    "key": row[field] or "unspecified",
                    "label": labels.get(row[field], row[field] or "Unspecified"),
                    "count": row["count"],
                    "percent": round(row["count"] / herd_total * 100, 1) if herd_total else 0.0,
                }
                for row in rows
            ]

        detections = PersonDetection.objects.filter(
            detected_at__gte=generated_at - timedelta(hours=hours)
        )
        average_confidence = detections.aggregate(value=Avg("confidence"))["value"]

        return Response({
            "generated_at": generated_at,
            "hours": hours,
            "herd": {
                "total": herd_total,
                "active": herd.filter(status="active").count(),
                "gender": distribution("gender", Goat.GENDER_CHOICES),
                "health": distribution("health_status", Goat.HEALTH_STATUS_CHOICES),
            },
            "security": {
                "total": detections.count(),
                "reviewed": detections.filter(review_state="reviewed").count(),
                "unreviewed": detections.filter(review_state="unreviewed").count(),
                "confirmed": detections.filter(status="confirmed").count(),
                "dismissed": detections.filter(status="dismissed").count(),
                "average_confidence": round(average_confidence * 100, 1) if average_confidence is not None else None,
            },
        })


def goat_queryset(*, detail=False):

    latest_weight = GoatWeightMeasurement.objects.filter(goat=OuterRef("pk")).order_by("-measured_at")
    queryset = Goat.objects.filter(record_source=Goat.SMART_FARM).annotate(
        mobile_latest_weight=Subquery(latest_weight.values("weight_kg")[:1]),
        mobile_latest_weight_at=Subquery(latest_weight.values("measured_at")[:1]),
    )
    image_query = GoatImage.objects.order_by("-uploaded_at")
    if not detail:
        image_query = image_query.filter(Q(angle__isnull=False) | Q(is_primary=True))
    queryset = queryset.prefetch_related(
        Prefetch("images", queryset=image_query, to_attr="mobile_images")
    )
    if detail:
        queryset = queryset.prefetch_related(
            Prefetch("weight_measurements", queryset=GoatWeightMeasurement.objects.order_by("-measured_at"), to_attr="mobile_weights")
        )
    return queryset


def goat_form_errors(form):
    return {
        field: [item["message"] for item in errors]
        for field, errors in form.errors.get_json_data().items()
    }


def serialized_goat(request, goat):
    refreshed = goat_queryset(detail=True).get(pk=goat.pk)
    return GoatDetailSerializer(refreshed, context={"request": request}).data


class GoatOptionsView(APIView):
    permission_classes = [HasActiveFarmAccess]

    def get(self, request):
        def choices(values):
            return [{"value": value, "label": label} for value, label in values]

        return Response({
            "breeds": choices(Goat.BREED_CHOICES),
            "genders": choices(Goat.GENDER_CHOICES),
            "health_statuses": choices(Goat.HEALTH_STATUS_CHOICES),
            "vaccination_statuses": choices(Goat.VACCINATION_STATUS_CHOICES),
            "image_angles": [
                {
                    "value": value,
                    "label": label,
                    "guidance": ANGLE_GUIDANCE[value],
                    "optional": value == GoatImage.FACE,
                }
                for value, label in GoatImage.ANGLE_CHOICES
            ],
        })


class GoatListView(generics.ListAPIView):
    permission_classes = [HasActiveFarmAccess]
    serializer_class = GoatListSerializer

    def post(self, request):
        form = GoatForm(request.data)
        form.fields.pop("captured_photo", None)
        if not form.is_valid():
            return Response(
                {"detail": "Please correct the livestock record.", "errors": goat_form_errors(form)},
                status=400,
            )
        goat = form.save(commit=False)
        goat.owner = request.user
        goat.record_source = Goat.SMART_FARM
        goat.save()
        return Response(serialized_goat(request, goat), status=status.HTTP_201_CREATED)

    def search_queryset(self, queryset):
        query = self.request.query_params.get("search", "").strip()
        if query:
            queryset = queryset.filter(
                Q(goat_id__icontains=query)
                | Q(name__icontains=query)
                | Q(tag_number__icontains=query)
            )
        return queryset

    def get_queryset(self):
        queryset = self.search_queryset(goat_queryset())
        gender = self.request.query_params.get("gender", "").strip()
        status_value = self.request.query_params.get("status", "").strip()
        if gender in dict(Goat.GENDER_CHOICES):
            queryset = queryset.filter(gender=gender)
        if status_value in dict(Goat.STATUS_CHOICES):
            queryset = queryset.filter(status=status_value)
        return queryset

    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)
        herd = self.search_queryset(
            Goat.objects.filter(record_source=Goat.SMART_FARM)
        )
        response.data["facets"] = herd.aggregate(
            all=Count("id"),
            male=Count("id", filter=Q(gender="male")),
            female=Count("id", filter=Q(gender="female")),
            active=Count("id", filter=Q(status="active")),
            missing=Count("id", filter=Q(status="missing")),
            detected=Count("id", filter=Q(last_seen__isnull=False)),
            attention=Count(
                "id",
                filter=Q(status="missing")
                | ~Q(health_status__in=["healthy", "good", "normal"]),
            ),
        )
        return response


class GoatDetailView(generics.RetrieveAPIView):
    permission_classes = [HasActiveFarmAccess]
    serializer_class = GoatDetailSerializer
    lookup_field = "goat_id"
    queryset = goat_queryset(detail=True)

    def put(self, request, *args, **kwargs):
        goat = self.get_object()
        form = GoatForm(request.data, instance=goat)
        form.fields.pop("captured_photo", None)
        form.fields.pop("weight_kg", None)
        if not form.is_valid():
            return Response(
                {"detail": "Please correct the livestock record.", "errors": goat_form_errors(form)},
                status=400,
            )
        updated = form.save()
        return Response(serialized_goat(request, updated))


class GoatPhotoManageView(APIView):
    permission_classes = [HasActiveFarmAccess]

    def post(self, request, goat_id):
        goat = Goat.objects.filter(goat_id=goat_id, record_source=Goat.SMART_FARM).first()
        if not goat:
            return Response({"detail": "Goat not found."}, status=404)
        upload = request.FILES.get("image")
        angle = str(request.data.get("angle", "")).strip()
        description = str(request.data.get("description", "")).strip()
        if angle not in dict(GoatImage.ANGLE_CHOICES):
            return Response({"detail": "Choose a valid standard photo angle."}, status=400)
        try:
            normalized = validated_goat_image(upload, check_quality=True)
            save_standard_photo(goat, angle, normalized, description=description)
        except ValidationError as exc:
            return Response({"detail": exc.messages[0]}, status=400)
        return Response(serialized_goat(request, goat), status=status.HTTP_201_CREATED)


class GoatPhotoActionView(APIView):
    permission_classes = [HasActiveFarmAccess]

    def post(self, request, goat_id, image_pk):
        goat = Goat.objects.filter(goat_id=goat_id, record_source=Goat.SMART_FARM).first()
        if not goat:
            return Response({"detail": "Goat not found."}, status=404)
        photo = GoatImage.objects.filter(pk=image_pk, goat=goat).first()
        if not photo:
            return Response({"detail": "Photo not found for this goat."}, status=404)
        action = str(request.data.get("action", "")).strip()
        if action == "set_primary":
            with transaction.atomic():
                GoatImage.objects.filter(goat=goat, is_primary=True).update(is_primary=False)
                photo.is_primary = True
                photo.save(update_fields=["is_primary"])
        elif action == "delete":
            delete_goat_photo(photo)
        else:
            return Response({"detail": "Use set_primary or delete."}, status=400)
        return Response(serialized_goat(request, goat))


class GoatImageView(APIView):
    permission_classes = [HasActiveFarmAccess]

    def get(self, request, pk):
        image = GoatImage.objects.filter(pk=pk, goat__record_source=Goat.SMART_FARM).first()
        if not image or not image.image:
            raise Http404
        try:
            handle = image.image.open("rb")
        except (FileNotFoundError, ValueError):
            raise Http404
        response = FileResponse(handle)
        response["Cache-Control"] = "private, max-age=300"
        response["X-Content-Type-Options"] = "nosniff"
        return response


class CameraListView(generics.ListAPIView):
    permission_classes = [HasActiveFarmAccess]
    serializer_class = CameraSerializer
    queryset = IPCamera.objects.all()


class LiveDetectionView(APIView):
    """Token-authenticated adapter for the shared local inference loop."""

    permission_classes = [HasActiveFarmAccess]

    @staticmethod
    def _camera():
        return IPCamera.objects.filter(is_active=True).first()

    @staticmethod
    def _payload(camera, client):
        from ml_models.live_detection import status as live_status

        payload = live_status(camera.id, client)
        payload["camera"] = {
            "id": camera.id,
            "camera_id": camera.camera_id,
            "name": camera.name,
            "location": camera.location,
            "detection_interval_seconds": camera.detection_interval_seconds,
        }
        return payload

    def get(self, request):
        from ml_models.live_detection import redis_client

        camera = self._camera()
        if camera is None:
            return Response({"detail": "No active camera."}, status=404)
        return Response(self._payload(camera, redis_client()))

    def post(self, request):
        from ml_models.live_detection import key, redis_client, viewer_heartbeat, viewer_leave

        camera = self._camera()
        if camera is None:
            return Response({"detail": "No active camera."}, status=404)

        action = str(request.data.get("action", ""))
        token = str(request.data.get("token", ""))
        client = redis_client()
        try:
            if action == "view":
                viewer_heartbeat(camera.id, token, client)
            elif action == "leave":
                viewer_leave(camera.id, token, client)
            elif action == "manual_start" and can_manage_farm(request.user):
                viewer_heartbeat(camera.id, token, client)
                client.set(key(camera.id, "manual"), token)
            elif action == "manual_stop" and can_manage_farm(request.user):
                client.delete(key(camera.id, "manual"))
            elif action == "set_interval" and can_manage_farm(request.user):
                interval = int(request.data.get("interval"))
                if not 2 <= interval <= 60:
                    return Response({"detail": "Interval must be 2 to 60 seconds."}, status=400)
                camera.detection_interval_seconds = interval
                camera.save(update_fields=["detection_interval_seconds"])
            else:
                return Response({"detail": "Invalid action or permission."}, status=403)
        except (TypeError, ValueError, AttributeError):
            return Response({"detail": "Invalid request."}, status=400)

        return Response(self._payload(camera, client))


def camera_stream(request, camera_id):
    """Bridge an expiring mobile ticket to the existing, proven MJPEG view."""
    raw_ticket = request.GET.get("ticket", "")
    try:
        payload = signing.loads(raw_ticket, salt=TICKET_SALT, max_age=60)
    except signing.BadSignature:
        return HttpResponse("Camera ticket expired or invalid.", status=401)
    if payload.get("purpose") != "camera" or str(payload.get("camera_id")) != str(camera_id):
        return HttpResponse("Camera ticket does not match this stream.", status=403)
    user = get_user_model().objects.filter(pk=payload.get("user_id"), is_active=True).first()
    if not user or not has_farm_access(user):
        return HttpResponse("Farm access required.", status=403)
    request.user = user
    from iot.views import camera_feed
    return camera_feed.__wrapped__(request, camera_id)


class TrackingView(APIView):
    permission_classes = [HasActiveFarmAccess]

    def get(self, request):
        return Response(build_tracking_snapshot(record_source=Goat.SMART_FARM))
