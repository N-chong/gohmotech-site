from django.core.cache import cache
from django.test import TestCase, override_settings

from .models import (
    ActuationLog,
    ActuatorState,
    AutomationRule,
    Device,
    SensorReading,
)
from .tasks import check_and_execute_rules


@override_settings(
    CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "automation-rule-tests",
        }
    }
)
class SensorAutomationRuleTests(TestCase):
    def setUp(self):
        cache.set("automation_enabled", True)
        self.controller = Device.objects.create(
            device_id="gohmotech_esp32_002",
            name="Door Light LDR Controller",
            device_type="environmental_sensor",
        )
        self.environment = Device.objects.create(
            device_id="gohmotech_esp32_001",
            name="Environment Controller",
            device_type="environmental_sensor",
        )
        ActuatorState.objects.create(
            device=self.controller,
            actuator_type="door",
            current_state="closed",
        )
        ActuatorState.objects.create(
            device=self.controller,
            actuator_type="light",
            current_state="off",
        )

    def test_door_rule_updates_door_state_not_light_state(self):
        SensorReading.objects.create(device=self.environment, temperature=35)
        rule = AutomationRule.objects.create(
            name="Open door when hot",
            actuator=self.controller,
            rule_type="sensor_based",
            action="open_door",
            criteria={"temperature": ">30"},
        )

        result = check_and_execute_rules()

        self.assertEqual(result, "Executed 1 rules")
        self.assertEqual(
            ActuatorState.objects.get(
                device=self.controller, actuator_type="door"
            ).current_state,
            "open",
        )
        self.assertEqual(
            ActuatorState.objects.get(
                device=self.controller, actuator_type="light"
            ).current_state,
            "off",
        )
        log = ActuationLog.objects.get(rule=rule)
        self.assertEqual(log.metadata["actuator_type"], "door")

    def test_ldr_rule_uses_reading_from_door_light_controller(self):
        SensorReading.objects.create(
            device=self.environment,
            temperature=28,
            light_level_percentage=None,
        )
        SensorReading.objects.create(
            device=self.controller,
            light_raw=3400,
            light_level_percentage=8,
        )
        AutomationRule.objects.create(
            name="Turn on light when dark",
            actuator=self.controller,
            rule_type="sensor_based",
            action="turn_on_light",
            criteria={"light_level_percentage": "<15"},
        )

        result = check_and_execute_rules()

        self.assertEqual(result, "Executed 1 rules")
        self.assertEqual(
            ActuatorState.objects.get(
                device=self.controller, actuator_type="light"
            ).current_state,
            "on",
        )

    def test_distance_rule_reads_feeder_level_field(self):
        SensorReading.objects.create(device=self.environment, feeder_level=42)
        AutomationRule.objects.create(
            name="Open door for low feed",
            actuator=self.controller,
            rule_type="sensor_based",
            action="open_door",
            criteria={"distance": ">30"},
        )

        result = check_and_execute_rules()

        self.assertEqual(result, "Executed 1 rules")
