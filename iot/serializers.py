from datetime import datetime, timezone as dt_timezone
import re

from django.utils import timezone
from rest_framework import serializers
from .models import (
    Device, SensorData, Alert, ActuatorState, AutomationRule, ActuationLog,
    SensorReading, SensorReadingSummary,
)


class DeviceMeasurementTimeField(serializers.DateTimeField):
    """Accept modern ISO timestamps while tolerating legacy uptime counters.

    Several archived ESP32 sketches send ``millis()/1000`` under ``timestamp``.
    That value is not a date and was historically ignored. Treat it as absent
    so those devices continue using the safe backend-arrival fallback.
    """

    def to_internal_value(self, value):
        if value in (None, ""):
            return None
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return None
        return super().to_internal_value(value)


class DeviceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Device
        fields = '__all__'


class SensorReadingSerializer(serializers.ModelSerializer):
    device_id = serializers.CharField(write_only=True, required=False)
    device_name = serializers.CharField(write_only=True, required=False)
    # Optional for backwards compatibility. New firmware supplies an explicit
    # UTC ISO-8601 value so delayed uploads retain their measurement time.
    timestamp = DeviceMeasurementTimeField(required=False, allow_null=True)
    
    class Meta:
        model = SensorReading
        fields = ['id', 'device', 'device_id', 'device_name', 'temperature', 'humidity', 
                  'soil_moisture', 'light_intensity', 'light_raw', 'light_level_percentage',
                  'air_quality_raw', 'air_quality_voltage', 'air_quality_ppm',
                  'air_quality_calibrated', 'rain_detected', 'feeder_level',
                  'timestamp', 'received_at']
        read_only_fields = ['id', 'received_at']
        extra_kwargs = {
            'device': {'required': False, 'allow_null': True}
        }
    
    def validate(self, attrs):
        raw_timestamp = self.initial_data.get('timestamp')
        if raw_timestamp in (None, ''):
            attrs.pop('timestamp', None)
        elif isinstance(raw_timestamp, (int, float)) and not isinstance(raw_timestamp, bool):
            attrs.pop('timestamp', None)
        else:
            # Never guess whether a device wall-clock value is UTC or Manila.
            # Requiring Z/+HH:MM prevents the classic double-UTC+8 defect.
            if not isinstance(raw_timestamp, str) or not re.search(
                r'(?:Z|[+-]\d{2}:?\d{2})$', raw_timestamp, re.IGNORECASE
            ):
                raise serializers.ValidationError({
                    'timestamp': 'Use ISO 8601 with an explicit timezone, for example 2026-10-02T04:30:00Z.'
                })

            measured_at = attrs.get('timestamp')
            if measured_at:
                measured_utc = measured_at.astimezone(dt_timezone.utc)
                if measured_utc < datetime(2020, 1, 1, tzinfo=dt_timezone.utc):
                    raise serializers.ValidationError({'timestamp': 'Device clock is not synchronized.'})
        return attrs

    def create(self, validated_data):
        # Handle device identification
        device_id = validated_data.pop('device_id', None)
        device_name = validated_data.pop('device_name', None)
        
        # If device is not provided, try to find/create by device_id or device_name
        if 'device' not in validated_data or validated_data.get('device') is None:
            if device_id:
                device, created = Device.objects.get_or_create(
                    device_id=device_id,
                    defaults={
                        'name': device_name or device_id,
                        'device_type': 'environmental_sensor',
                        'is_active': True
                    }
                )
                validated_data['device'] = device
            elif device_name:
                # Try to find device by name
                device = Device.objects.filter(name=device_name).first()
                if not device:
                    # Create new device
                    device = Device.objects.create(
                        device_id=device_name.lower().replace(' ', '_'),
                        name=device_name,
                        device_type='environmental_sensor',
                        is_active=True
                    )
                validated_data['device'] = device
            else:
                raise serializers.ValidationError("Either device, device_id, or device_name must be provided")
        
        # Store the device measurement instant when supplied; otherwise the
        # model default makes server receipt time authoritative.
        reading = super().create(validated_data)
        Device.objects.filter(pk=reading.device_id).update(
            last_sensor_received_at=reading.received_at)
        return reading


class SensorDataSerializer(serializers.ModelSerializer):
    device_name = serializers.CharField(source='device.name', read_only=True)
    
    class Meta:
        model = SensorData
        fields = '__all__'

    def create(self, validated_data):
        reading = super().create(validated_data)
        Device.objects.filter(pk=reading.device_id).update(
            last_sensor_received_at=timezone.now())
        return reading


class SensorReadingSummarySerializer(serializers.ModelSerializer):
    device_name = serializers.CharField(source='device.name', read_only=True)

    class Meta:
        model = SensorReadingSummary
        fields = [
            'id', 'device', 'device_name', 'sensor_type', 'unit',
            'period_start', 'period_end', 'average_value', 'minimum_value',
            'maximum_value', 'sample_count', 'created_at', 'updated_at',
        ]
        read_only_fields = fields


class AlertSerializer(serializers.ModelSerializer):
    device_name = serializers.CharField(source='device.name', read_only=True)
    
    class Meta:
        model = Alert
        fields = '__all__'


class ActuatorStateSerializer(serializers.ModelSerializer):
    device_name = serializers.CharField(source='device.name', read_only=True)
    device_location = serializers.CharField(source='device.location', read_only=True)
    actuator_type_display = serializers.CharField(source='get_actuator_type_display', read_only=True)
    current_state_display = serializers.CharField(source='get_current_state_display', read_only=True)
    mode_display = serializers.CharField(source='get_mode_display', read_only=True)
    device_online = serializers.SerializerMethodField()
    device_last_seen = serializers.SerializerMethodField()
    controller_role = serializers.SerializerMethodField()

    def get_device_online(self, obj):
        from .status_utils import is_device_online
        return is_device_online(obj.device)

    def get_device_last_seen(self, obj):
        from .status_utils import device_last_seen
        return device_last_seen(obj.device)

    def get_controller_role(self, obj):
        return 'feeder' if obj.actuator_type == 'feeder' else 'main'
    
    class Meta:
        model = ActuatorState
        fields = '__all__'


class AutomationRuleSerializer(serializers.ModelSerializer):
    actuator_name = serializers.CharField(source='actuator.name', read_only=True)
    rule_type_display = serializers.CharField(source='get_rule_type_display', read_only=True)
    action_display = serializers.CharField(source='get_action_display', read_only=True)
    
    class Meta:
        model = AutomationRule
        fields = '__all__'


class ActuationLogSerializer(serializers.ModelSerializer):
    device_name = serializers.CharField(source='device.name', read_only=True)
    action_display = serializers.CharField(source='get_action_display', read_only=True)
    source_display = serializers.CharField(source='get_source_display', read_only=True)
    rule_name = serializers.CharField(source='rule.name', read_only=True, allow_null=True)
    
    class Meta:
        model = ActuationLog
        fields = '__all__'
