from django.test import TestCase

from .models import Device, SensorReading
from .status_utils import MAIN_CONTROLLER_DEVICE_ID, controller_status


class MainControllerStatusTests(TestCase):
    def test_door_light_controller_status_uses_registered_device_id(self):
        Device.objects.create(
            device_id="kamotech_esp32_001",
            name="Environment feeder",
            device_type="environmental_sensor",
        )
        controller = Device.objects.create(
            device_id="gohmotech_esp32_002",
            name="Door light LDR controller",
            device_type="main esp32",
        )

        status = controller_status()

        self.assertEqual(MAIN_CONTROLLER_DEVICE_ID, "gohmotech_esp32_002")
        self.assertEqual(status["device"], controller)
        self.assertFalse(status["online"])

        SensorReading.objects.create(
            device=controller,
            light_raw=900,
            light_level_percentage=80,
        )

        self.assertTrue(controller_status()["online"])
