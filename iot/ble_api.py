"""Authenticated HTTP endpoints used by standalone BLE scanner services."""

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated

from marketplace.permissions import FarmRolePermission
from rest_framework.response import Response
from rest_framework.views import APIView

from .ble_authentication import BLEReceiverAuthentication
from .ble_services import (
    BeaconIdentityConflictError,
    BeaconNotFoundError,
    build_tracking_snapshot,
    record_observation,
    touch_receiver,
)
from .models import (
    BLEBeacon,
    BLEReceiver,
    BLETrackingSettings,
)
from .goat_models import normalize_ble_mac_address, normalize_ibeacon_uuid


class BLEHeartbeatSerializer(serializers.Serializer):
    scanner_version = serializers.CharField(max_length=50, required=False)
    device_name = serializers.CharField(max_length=200, required=False)
    platform = serializers.ChoiceField(
        choices=BLEReceiver.PLATFORM_CHOICES,
        required=False,
    )
    metadata = serializers.JSONField(required=False)

    def validate_metadata(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError('Metadata must be a JSON object.')
        return value


class BLEObservationSerializer(serializers.Serializer):
    protocol = serializers.CharField(max_length=40, required=False, allow_blank=True)
    address = serializers.CharField(max_length=32, required=False, allow_null=True)
    device_name = serializers.CharField(
        max_length=100,
        required=False,
        allow_blank=True,
        allow_null=True,
    )
    uuid = serializers.CharField(max_length=40, required=False, allow_null=True)
    major = serializers.IntegerField(
        min_value=0,
        max_value=65535,
        required=False,
        allow_null=True,
    )
    minor = serializers.IntegerField(
        min_value=0,
        max_value=65535,
        required=False,
        allow_null=True,
    )
    rssi = serializers.IntegerField(min_value=-127, max_value=20)
    smoothed_rssi = serializers.FloatField(
        min_value=-127,
        max_value=20,
        required=False,
        allow_null=True,
    )
    measured_power = serializers.IntegerField(
        min_value=-127,
        max_value=20,
        required=False,
        allow_null=True,
    )
    advertised_tx_power = serializers.IntegerField(
        min_value=-127,
        max_value=20,
        required=False,
        allow_null=True,
    )
    battery_level = serializers.IntegerField(
        min_value=0,
        max_value=100,
        required=False,
        allow_null=True,
    )
    sample_count = serializers.IntegerField(min_value=1, required=False)
    service_data = serializers.JSONField(required=False)
    seen_at = serializers.DateTimeField(required=False)

    def validate_address(self, value):
        try:
            return normalize_ble_mac_address(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.messages) from exc

    def validate_uuid(self, value):
        if value in (None, ''):
            return None
        try:
            return normalize_ibeacon_uuid(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.messages) from exc

    def validate_service_data(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError('Service data must be a JSON object.')
        return value

    def validate(self, attrs):
        identity_values = [attrs.get(field) for field in ('uuid', 'major', 'minor')]
        identity_supplied = [value is not None for value in identity_values]
        if any(identity_supplied) and not all(identity_supplied):
            raise serializers.ValidationError(
                'uuid, major, and minor must be supplied together.'
            )
        if not all(identity_supplied) and not attrs.get('address'):
            raise serializers.ValidationError(
                'Supply either a complete iBeacon identity or a BLE address.'
            )
        return attrs


def _tracking_config_payload(config):
    return {
        'smoothing_method': config.smoothing_method,
        'smoothing_window_size': config.smoothing_window_size,
        'very_near_min_rssi': config.very_near_min_rssi,
        'near_min_rssi': config.near_min_rssi,
        'medium_min_rssi': config.medium_min_rssi,
        'possibly_lost_timeout_seconds': config.possibly_lost_timeout_seconds,
        'out_of_range_timeout_seconds': config.out_of_range_timeout_seconds,
        'report_interval_seconds': config.report_interval_seconds,
        'heartbeat_interval_seconds': config.heartbeat_interval_seconds,
        'history_snapshot_interval_seconds': (
            config.history_snapshot_interval_seconds
        ),
    }


def _beacon_payload(beacon):
    goat = None
    if beacon.goat_id:
        goat = {
            'id': beacon.goat_id,
            'goat_id': beacon.goat.goat_id,
            'name': beacon.goat.name,
        }
    return {
        'id': beacon.pk,
        'device_name': beacon.device_name,
        'mac_address': beacon.mac_address,
        'uuid': beacon.uuid,
        'major': beacon.major,
        'minor': beacon.minor,
        'calibrated_rssi': beacon.calibrated_rssi,
        'goat': goat,
    }


class BLEReceiverHeartbeatAPIView(APIView):
    authentication_classes = [BLEReceiverAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = BLEHeartbeatSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        receiver = request.user.receiver
        touch_receiver(receiver, **serializer.validated_data)

        config = BLETrackingSettings.get_config()
        beacons = BLEBeacon.objects.filter(enabled=True).select_related('goat')
        return Response({
            'receiver': {
                'receiver_id': receiver.device.device_id,
                'receiver_name': receiver.device.name,
                'device_name': receiver.device_name,
                'location': receiver.device.location,
                'platform': receiver.platform,
                'status': receiver.status,
                'last_online': receiver.last_online,
            },
            'tracking_config': _tracking_config_payload(config),
            'beacons': [_beacon_payload(beacon) for beacon in beacons],
        })


class BLEObservationAPIView(APIView):
    authentication_classes = [BLEReceiverAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = BLEObservationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        receiver = request.user.receiver

        try:
            state, history = record_observation(
                receiver,
                serializer.validated_data,
            )
        except BeaconNotFoundError as exc:
            touch_receiver(receiver)
            return Response(
                {'accepted': False, 'code': 'unknown_beacon', 'detail': str(exc)},
                status=status.HTTP_404_NOT_FOUND,
            )
        except BeaconIdentityConflictError as exc:
            touch_receiver(receiver)
            return Response(
                {
                    'accepted': False,
                    'code': 'beacon_identity_conflict',
                    'detail': str(exc),
                },
                status=status.HTTP_409_CONFLICT,
            )

        beacon = state.beacon
        return Response({
            'accepted': True,
            'history_saved': history is not None,
            'beacon_id': beacon.pk,
            'goat': (
                {
                    'id': beacon.goat_id,
                    'goat_id': beacon.goat.goat_id,
                    'name': beacon.goat.name,
                }
                if beacon.goat_id
                else None
            ),
            'state': {
                'current_rssi': state.current_rssi,
                'smoothed_rssi': state.smoothed_rssi,
                'proximity': state.proximity,
                'status': state.status,
                'last_seen': state.last_seen,
                'sample_count': state.sample_count,
            },
        })


class BLETrackingSnapshotAPIView(APIView):
    """Session-authenticated live data for the tracking list and future radar."""

    permission_classes = [FarmRolePermission]

    def get(self, request):
        return Response(build_tracking_snapshot())
