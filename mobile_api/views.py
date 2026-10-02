from django.contrib.auth import authenticate, get_user_model
from django.core import signing
from django.db.models import OuterRef, Prefetch, Q, Subquery
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
from iot.goat_models import Goat, GoatImage, GoatWeightMeasurement, IPCamera
from iot.models import ActuatorState, Device, SensorReading
from iot.status_utils import controller_status, is_device_online
from marketplace.auth import can_manage_farm, get_system_role, has_farm_access
from security.models import Notification

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
        if not has_farm_access(user):
            return Response({"detail": "This account does not have farm access."}, status=403)
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
                "updated_at": latest.timestamp if latest else None,
            },
            "feed": {
                "percentage": (feed.percentage if feed and feed.percentage is not None else (feed.percentage_full if feed else None)),
                "is_low": feed.is_low if feed else None,
                "updated_at": feed.updated_at if feed else None,
            },
            "goats": {"registered": Goat.objects.filter(is_active=True).count()},
            "automation": {
                "door": {"id": door.pk, "state": door.current_state, "mode": door.mode, "updated_at": door.last_changed_at} if door else None,
                "light": {"id": light.pk, "state": light.current_state, "mode": light.mode, "updated_at": light.last_changed_at} if light else None,
            },
            "alerts": [{
                "id": item.pk, "title": item.title, "severity": item.severity,
                "type": item.notification_type, "created_at": item.created_at,
            } for item in alerts],
        })


def goat_queryset(*, detail=False):
    latest_weight = GoatWeightMeasurement.objects.filter(goat=OuterRef("pk")).order_by("-measured_at")
    queryset = Goat.objects.annotate(
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


class GoatListView(generics.ListAPIView):
    permission_classes = [HasActiveFarmAccess]
    serializer_class = GoatListSerializer

    def get_queryset(self):
        queryset = goat_queryset()
        query = self.request.query_params.get("search", "").strip()
        status_value = self.request.query_params.get("status", "").strip()
        if query:
            queryset = queryset.filter(Q(goat_id__icontains=query) | Q(name__icontains=query) | Q(tag_number__icontains=query))
        if status_value:
            queryset = queryset.filter(status=status_value)
        return queryset


class GoatDetailView(generics.RetrieveAPIView):
    permission_classes = [HasActiveFarmAccess]
    serializer_class = GoatDetailSerializer
    lookup_field = "goat_id"
    queryset = goat_queryset(detail=True)


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
        return Response(build_tracking_snapshot())
