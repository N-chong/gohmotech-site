from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse

from marketplace.auth import FARM_OWNER_GROUP_NAME

from .models import ActuatorState, AutomationRule, Device, SensorReading


class MonitoringSensorReadingDisplayTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(
            "monitoring-owner", password="test-password"
        )
        owner_group, _ = Group.objects.get_or_create(name=FARM_OWNER_GROUP_NAME)
        self.owner.groups.add(owner_group)
        self.client.force_login(self.owner)

    @patch("iot.views.get_farm_weather", return_value={"available": False})
    def test_monitoring_uses_current_aggregated_sensor_readings(self, _weather):
        environment = Device.objects.create(
            device_id="environment-board",
            name="Environment board",
            device_type="environmental_sensor",
        )
        lighting = Device.objects.create(
            device_id="door-light-board",
            name="Door and light board",
            device_type="environmental_sensor",
        )
        SensorReading.objects.create(
            device=environment,
            temperature=31.5,
            humidity=72.0,
            air_quality_raw=612,
            rain_detected=False,
        )
        SensorReading.objects.create(
            device=lighting,
            light_raw=2048,
            light_level_percentage=50.0,
        )

        response = self.client.get(reverse("iot:monitoring_dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["latest_sensor_reading"].device, environment)
        self.assertEqual(response.context["latest_conditions"]["temperature"]["value"], 31.5)
        self.assertEqual(response.context["latest_conditions"]["light_level"]["value"], 50.0)
        self.assertContains(response, "31.5°C")
        self.assertContains(response, "50.0%")
        self.assertNotContains(response, "No environmental data available")


class AutomationScheduleTimeDisplayTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(
            "schedule-owner", password="test-password"
        )
        owner_group, _ = Group.objects.get_or_create(name=FARM_OWNER_GROUP_NAME)
        self.owner.groups.add(owner_group)
        self.client.force_login(self.owner)
        self.device = Device.objects.create(
            device_id="door-controller",
            name="Door controller",
            device_type="actuator",
        )
        ActuatorState.objects.create(device=self.device, actuator_type="door")

    def _rule(self, name, criteria):
        return AutomationRule.objects.create(
            name=name,
            actuator=self.device,
            rule_type="time_based",
            action="open_door",
            criteria=criteria,
        )

    def test_schedule_page_displays_current_and_legacy_time_formats(self):
        self._rule(
            "Morning opening",
            {"time": "06:30", "action": "open", "days_of_week": [1, 2]},
        )
        self._rule(
            "Legacy opening",
            {"schedule_time": "19:45", "action": "open", "days_of_week": []},
        )
        self._rule("Schedule: Door controller open at 21:10", {})

        response = self.client.get(reverse("iot:automation_schedule"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "06:30")
        self.assertContains(response, "19:45")
        self.assertContains(response, "21:10")
        self.assertNotContains(response, "Time not set")

