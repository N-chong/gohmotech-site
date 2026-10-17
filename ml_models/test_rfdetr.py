import sys
import types
from unittest.mock import patch

import numpy as np
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase

from .ml_utils import RFDETRDetector, get_detector
from .models import MLModel
from .validators import validate_model_upload


class _Predictions:
    xyxy = np.array([[10.0, 20.0, 70.0, 100.0]])
    confidence = np.array([0.91])
    # Some RF-DETR checkpoints expose the sole foreground class as 1 rather
    # than 0; the detector must normalize both conventions.
    class_id = np.array([1])


class _FakeRFDETRModel:
    class_names = ['goat']

    def predict(self, image, threshold=0.5):
        self.last_threshold = threshold
        return _Predictions()


class _FakeRFDETR:
    @classmethod
    def from_checkpoint(cls, path, **kwargs):
        return _FakeRFDETRModel()


class _FakeVariant:
    def __init__(self, **kwargs):
        self.class_names = ['goat']

    def predict(self, image, threshold=0.5):
        return _Predictions()


def _fake_rfdetr_module():
    module = types.ModuleType('rfdetr')
    module.RFDETR = _FakeRFDETR
    module.RFDETRNano = _FakeVariant
    module.RFDETRSmall = _FakeVariant
    module.RFDETRMedium = _FakeVariant
    module.RFDETRLarge = _FakeVariant
    return module


def _fake_torch_module():
    module = types.ModuleType('torch')
    module.cuda = types.SimpleNamespace(is_available=lambda: False)
    return module


class RFDETRSupportTests(SimpleTestCase):
    def test_rfdetr_is_an_upload_model_choice(self):
        self.assertIn('rfdetr', dict(MLModel.MODEL_TYPES))

    def test_ckpt_upload_extension_is_allowed(self):
        upload = SimpleUploadedFile('checkpoint_best.ckpt', b'checkpoint')
        facts = validate_model_upload(upload)
        self.assertEqual(facts['extension'], '.ckpt')

    def test_factory_normalizes_rfdetr_predictions(self):
        with patch.dict(sys.modules, {
            'rfdetr': _fake_rfdetr_module(), 'torch': _fake_torch_module(),
        }):
            detector = get_detector(
                'rfdetr', '/tmp/checkpoint.pth',
                metadata={'rfdetr': {'variant': 'nano'}},
            )
            result = detector.detect(np.zeros((120, 160, 3), dtype=np.uint8))

        self.assertIsInstance(detector, RFDETRDetector)
        self.assertEqual(result['count'], 1)
        self.assertEqual(result['detections'][0]['label'], 'goat')
        self.assertEqual(
            result['detections'][0]['bbox'],
            {'x': 10.0, 'y': 20.0, 'width': 60.0, 'height': 80.0},
        )
        self.assertAlmostEqual(result['confidence'], 0.91, places=5)

    def test_auto_variant_uses_checkpoint_metadata_loader(self):
        with patch.dict(sys.modules, {
            'rfdetr': _fake_rfdetr_module(), 'torch': _fake_torch_module(),
        }):
            detector = RFDETRDetector(
                '/tmp/checkpoint.pth',
                metadata={'rfdetr': {'variant': 'auto'}},
            )
        self.assertEqual(detector.class_names, ['goat'])
