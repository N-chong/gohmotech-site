from unittest.mock import patch

from django.contrib.auth.models import User
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from .models import MLModel
from .validators import MAX_MODEL_FILE_SIZE


class ModelUploadFlowTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            "model-upload-admin", password="testpass123", is_staff=True
        )
        self.client.force_login(self.admin)

    def test_management_page_uses_real_xhr_upload_progress(self):
        response = self.client.get(reverse("ml_models:model_management"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Model Upload")
        self.assertContains(response, "xhr.upload.addEventListener('progress'")
        self.assertContains(response, "upload-chunk/")
        self.assertContains(response, "Remaining")

    def test_live_detection_page_renders_csrf_token_and_box_overlay(self):
        response = self.client.get(reverse("ml_models:detection_feed"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="detection-overlay"')
        self.assertContains(response, 'id="detection-csrf-token"')
        self.assertContains(response, "drawDetectionBoxes(data.detections || [])")
        self.assertContains(response, "ctx.strokeRect(x, y, width, height)")

    def test_security_dashboard_uses_chunked_upload_progress(self):
        response = self.client.get(reverse("security:dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "securityUploadProgress")
        self.assertContains(response, "upload-chunk/")
        self.assertContains(response, "xhr.upload.addEventListener('progress'")

    def test_large_upload_limit_uses_disk_spooling_threshold(self):
        self.assertGreater(settings.DATA_UPLOAD_MAX_MEMORY_SIZE, MAX_MODEL_FILE_SIZE)
        self.assertLess(settings.FILE_UPLOAD_MAX_MEMORY_SIZE, MAX_MODEL_FILE_SIZE)

    def test_preflight_rejects_oversized_file_before_upload(self):
        response = self.client.post(
            reverse("ml_models:mlmodel-upload-preflight"),
            {"filename": "too-large.pt", "size": MAX_MODEL_FILE_SIZE + 1},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error_code"], "invalid_file")

    @patch("ml_models.views._model_storage_has_capacity", return_value=False)
    def test_preflight_reports_insufficient_storage(self, _capacity):
        response = self.client.post(
            reverse("ml_models:mlmodel-upload-preflight"),
            {"filename": "best.pt", "size": 1024},
        )

        self.assertEqual(response.status_code, 507)
        self.assertEqual(response.json()["error_code"], "storage_unavailable")

    def test_upload_is_stored_but_never_automatically_activated(self):
        upload = SimpleUploadedFile(
            "best.pt", b"checkpoint-bytes", content_type="application/octet-stream"
        )
        response = self.client.post(
            reverse("ml_models:mlmodel-upload"),
            {
                "name": "Uploaded Goat Model",
                "version": "1.0",
                "category": "goat",
                "model_type": "yolov8",
                "model_file": upload,
            },
        )

        self.assertEqual(response.status_code, 201)
        model = MLModel.objects.get(name="Uploaded Goat Model")
        self.assertTrue(model.model_file.storage.exists(model.model_file.name))
        self.assertEqual(model.file_size, len(b"checkpoint-bytes"))
        self.assertEqual(model.status, "uploaded")
        self.assertFalse(model.is_active)

    def test_chunked_upload_is_assembled_and_registered_inactive(self):
        content = b"chunked-checkpoint-bytes"
        session_response = self.client.post(
            reverse("ml_models:mlmodel-upload-session"),
            {"filename": "chunked.pt", "size": len(content)},
        )
        self.assertEqual(session_response.status_code, 200)
        upload_id = session_response.json()["upload_id"]

        chunk_response = self.client.post(
            reverse("ml_models:mlmodel-upload-chunk"),
            {
                "upload_id": upload_id,
                "chunk_index": "0",
                "chunk": SimpleUploadedFile("chunk.part", content),
            },
        )
        self.assertEqual(chunk_response.status_code, 200)
        self.assertTrue(chunk_response.json()["complete"])

        completion_response = self.client.post(
            reverse("ml_models:mlmodel-complete-upload"),
            {
                "upload_id": upload_id,
                "name": "Chunked Goat Model",
                "version": "1.0",
                "category": "goat",
                "model_type": "yolov8",
            },
        )
        self.assertEqual(completion_response.status_code, 201)
        model = MLModel.objects.get(name="Chunked Goat Model")
        self.assertEqual(model.file_size, len(content))
        self.assertEqual(model.status, "uploaded")
        self.assertFalse(model.is_active)

    @patch("ml_models.views.get_detector", side_effect=ValueError("internal loader detail"))
    def test_failed_candidate_load_keeps_previous_active_model(self, _get_detector):
        current = MLModel.objects.create(
            name="Current Model", version="1.0", category="goat",
            model_type="yolov8", status="active", is_active=True,
        )
        candidate = MLModel.objects.create(
            name="Candidate Model", version="1.0", category="goat",
            model_type="yolov8", status="validated", is_active=False,
            model_file=SimpleUploadedFile("candidate.pt", b"candidate"),
        )

        response = self.client.post(
            reverse("ml_models:mlmodel-activate", args=[candidate.pk])
        )

        self.assertEqual(response.status_code, 400)
        self.assertNotContains(response, "internal loader detail", status_code=400)
        current.refresh_from_db()
        candidate.refresh_from_db()
        self.assertTrue(current.is_active)
        self.assertFalse(candidate.is_active)
        self.assertEqual(candidate.status, "validated")

    @patch("ml_models.views.get_detector")
    def test_archived_model_can_be_revalidated_and_activated(self, _get_detector):
        model = MLModel.objects.create(
            name="Archived", version="1", model_type="rfdetr", status="archived",
            model_file=SimpleUploadedFile("archived.pt", b"checkpoint"),
        )
        page = self.client.get(reverse("ml_models:model_management"))
        self.assertContains(page, 'data-action="validate"')
        response = self.client.post(reverse("ml_models:mlmodel-validate-model", args=[model.pk]))
        self.assertEqual(response.status_code, 200)
        response = self.client.post(reverse("ml_models:mlmodel-activate", args=[model.pk]))
        self.assertEqual(response.status_code, 200)
        model.refresh_from_db()
        self.assertTrue(model.is_active)

    def test_missing_file_validation_returns_actionable_error(self):
        model = MLModel.objects.create(
            name="Missing", version="1", model_type="rfdetr", status="archived",
            model_file="missing.pt",
        )
        response = self.client.post(reverse("ml_models:mlmodel-validate-model", args=[model.pk]))
        self.assertEqual(response.status_code, 400)
        self.assertIn("missing or unavailable", response.json()["error"])

    @patch("ml_models.views.get_detector", side_effect=ValueError("unsafe loader detail"))
    def test_validation_rejects_checkpoint_that_cannot_be_loaded(self, _get_detector):
        candidate = MLModel.objects.create(
            name="Invalid Candidate", version="1.0", category="goat",
            model_type="yolov8", status="uploaded", is_active=False,
            model_file=SimpleUploadedFile("invalid.pt", b"not-a-model"),
        )

        response = self.client.post(
            reverse("ml_models:mlmodel-validate-model", args=[candidate.pk])
        )

        self.assertEqual(response.status_code, 400)
        self.assertNotContains(response, "unsafe loader detail", status_code=400)
        candidate.refresh_from_db()
        self.assertEqual(candidate.status, "rejected")
        self.assertIn("could not be loaded", candidate.validation_notes)
