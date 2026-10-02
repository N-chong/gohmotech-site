from rest_framework import serializers

from iot.goat_models import Goat, GoatImage, GoatWeightMeasurement, IPCamera


class GoatImageSerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()
    angle_display = serializers.CharField(source="get_angle_display", read_only=True)

    class Meta:
        model = GoatImage
        fields = ["id", "image_url", "angle", "angle_display", "image_type", "captured_at", "is_primary"]

    def get_image_url(self, obj):
        request = self.context.get("request")
        if not obj.image:
            return None
        path = f"/api/mobile/goat-images/{obj.pk}/"
        return request.build_absolute_uri(path) if request else path


class GoatWeightSerializer(serializers.ModelSerializer):
    source_display = serializers.CharField(source="get_source_display", read_only=True)

    class Meta:
        model = GoatWeightMeasurement
        fields = ["id", "weight_kg", "source", "source_display", "measured_at", "recorded_at", "device_id"]


class GoatListSerializer(serializers.ModelSerializer):
    age = serializers.CharField(source="age_display", read_only=True)
    breed_display = serializers.CharField(source="get_breed_display", read_only=True)
    gender_display = serializers.CharField(source="get_gender_display", read_only=True)
    cover_image_url = serializers.SerializerMethodField()
    latest_weight = serializers.SerializerMethodField()

    class Meta:
        model = Goat
        fields = [
            "id", "goat_id", "name", "tag_number", "breed", "breed_display",
            "gender", "gender_display", "age", "weight_kg", "latest_weight",
            "health_status", "status", "last_seen", "cover_image_url",
        ]

    def get_cover_image_url(self, obj):
        images = getattr(obj, "mobile_images", [])
        photo = GoatImage.preferred_from(images)
        if not photo:
            return None
        request = self.context.get("request")
        path = f"/api/mobile/goat-images/{photo.pk}/"
        return request.build_absolute_uri(path) if request else path

    def get_latest_weight(self, obj):
        annotated_weight = getattr(obj, "mobile_latest_weight", None)
        if annotated_weight is not None:
            return {
                "weight_kg": str(annotated_weight),
                "measured_at": getattr(obj, "mobile_latest_weight_at", None),
            }
        measurements = getattr(obj, "mobile_weights", [])
        if measurements:
            item = measurements[0]
            return {"weight_kg": str(item.weight_kg), "measured_at": item.measured_at}
        if obj.weight_kg is not None:
            return {"weight_kg": str(obj.weight_kg), "measured_at": obj.last_updated}
        return None


class GoatDetailSerializer(GoatListSerializer):
    images = serializers.SerializerMethodField()
    weight_history = serializers.SerializerMethodField()
    vaccination_status_display = serializers.CharField(source="get_vaccination_status_display", read_only=True)

    class Meta(GoatListSerializer.Meta):
        fields = GoatListSerializer.Meta.fields + [
            "date_of_birth", "color_markings", "health_notes", "notes",
            "vaccination_status", "vaccination_status_display", "vaccine_name",
            "vaccination_date", "next_due_date", "date_added", "last_updated",
            "images", "weight_history",
        ]

    def get_images(self, obj):
        return GoatImageSerializer(
            getattr(obj, "mobile_images", []), many=True, context=self.context
        ).data

    def get_weight_history(self, obj):
        return GoatWeightSerializer(
            getattr(obj, "mobile_weights", []), many=True, context=self.context
        ).data


class CameraSerializer(serializers.ModelSerializer):
    class Meta:
        model = IPCamera
        fields = [
            "id", "camera_id", "name", "camera_type", "location", "status",
            "is_active", "last_connected", "last_error", "updated_at",
        ]
