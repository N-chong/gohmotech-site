from io import BytesIO
import base64
import json
import tempfile

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image, ImageDraw

from marketplace.auth import FARM_OWNER_GROUP_NAME

from .goat_photos import validated_goat_image
from .models import Goat, GoatImage


def test_photo(name='goat.jpg', size=(800, 600), colors=('#6f5538', '#e7d8b5')):
    image = Image.new('RGB', size, colors[0])
    draw = ImageDraw.Draw(image)
    step = max(12, min(size) // 12)
    for y in range(0, size[1], step):
        for x in range(0, size[0], step):
            if (x // step + y // step) % 2:
                draw.rectangle((x, y, x + step, y + step), fill=colors[1])
    output = BytesIO()
    image.save(output, 'JPEG', quality=90)
    return SimpleUploadedFile(name, output.getvalue(), content_type='image/jpeg')


def flat_photo(name, color, size=(800, 600)):
    output = BytesIO()
    Image.new('RGB', size, color).save(output, 'JPEG', quality=90)
    return SimpleUploadedFile(name, output.getvalue(), content_type='image/jpeg')


class StandardGoatPhotoTests(TestCase):
    def setUp(self):
        self.media = tempfile.TemporaryDirectory()
        self.addCleanup(self.media.cleanup)
        settings_override = override_settings(MEDIA_ROOT=self.media.name)
        settings_override.enable()
        self.addCleanup(settings_override.disable)

        self.user = get_user_model().objects.create_user(
            username='photo-owner',
            password='test-password',
        )
        owner_group, _ = Group.objects.get_or_create(name=FARM_OWNER_GROUP_NAME)
        self.user.groups.add(owner_group)
        self.client.force_login(self.user)

    def goat_payload(self, goat_id):
        return {
            'goat_id': goat_id,
            'name': 'Photo Goat',
            'tag_number': '',
            'breed': 'native',
            'gender': 'female',
            'date_of_birth': '',
            'weight_kg': '',
            'color_markings': 'Brown and white',
            'health_status': 'healthy',
            'health_notes': '',
            'vaccination_status': 'unknown',
            'vaccine_name': '',
            'vaccination_date': '',
            'next_due_date': '',
            'notes': '',
            'captured_photo': '',
            'captured_photos': '{}',
        }

    def create_goat(self, goat_id='PHOTO-001'):
        return Goat.objects.create(
            goat_id=goat_id,
            name='Photo Goat',
            gender='female',
            owner=self.user,
        )

    def test_add_goat_stores_each_upload_with_its_angle(self):
        payload = self.goat_payload('NEW-PHOTOS')
        payload['photo_front'] = test_photo('front.jpg')
        payload['photo_left'] = test_photo('left.jpg', colors=('#3f3025', '#d9c7a0'))

        response = self.client.post(reverse('iot:add_goat'), payload)

        self.assertEqual(response.status_code, 302)
        goat = Goat.objects.get(goat_id='NEW-PHOTOS')
        self.assertEqual(set(goat.images.values_list('angle', flat=True)), {'front', 'left'})
        self.assertTrue(goat.images.get(angle='front').is_primary)

    def test_add_page_has_mobile_camera_fallback_and_fresh_assets(self):
        response = self.client.get(reverse('iot:add_goat'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-native-capture-angle=', count=5)
        self.assertContains(response, 'capture="environment"', count=5)
        self.assertContains(response, 'goat-photos.css?v=mobile-14')
        self.assertContains(response, 'goat-photo-capture.js?v=mobile-14')
        self.assertContains(response, 'data-camera-url-template=')
        self.assertContains(response, 'data-photo-verification')
        self.assertContains(response, 'data-verification-image')
        self.assertContains(response, 'data-verification-retake')
        self.assertContains(response, 'data-verification-use')

    def test_dedicated_camera_page_is_scoped_to_requested_angle(self):
        response = self.client.get(reverse('iot:goat_photo_camera', args=['left']))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-camera-angle="left"')
        self.assertContains(response, 'Left Side View')
        self.assertContains(response, 'Photograph the complete left side of the goat.')
        self.assertContains(response, 'Capture This View')
        self.assertContains(response, 'Visual Verification')
        self.assertContains(response, 'data-captured-preview')
        self.assertContains(response, 'data-photo-retake')
        self.assertContains(response, 'data-photo-confirm')
        self.assertContains(response, 'goat-photo-camera.css?v=window-6')
        self.assertContains(response, 'goat-photo-camera-window.js?v=window-6')
        self.assertContains(response, 'capture="environment"')

    def test_dedicated_camera_page_rejects_unknown_angle(self):
        response = self.client.get(reverse('iot:goat_photo_camera', args=['unknown']))

        self.assertEqual(response.status_code, 404)

    def test_manage_page_can_add_a_standard_angle(self):
        goat = self.create_goat()
        payload = self.goat_payload(goat.goat_id)
        payload.pop('weight_kg')
        payload['photo_right'] = test_photo('right.jpg')

        response = self.client.post(
            reverse('iot:goat_detail_enhanced', args=[goat.goat_id]),
            payload,
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(goat.images.filter(angle=GoatImage.RIGHT).exists())

    def test_add_goat_stores_a_camera_capture_with_its_angle(self):
        payload = self.goat_payload('CAPTURED-PHOTO')
        captured = test_photo('rear-capture.jpg')
        payload['captured_photos'] = json.dumps({
            'rear': 'data:image/jpeg;base64,' + base64.b64encode(captured.read()).decode('ascii')
        })

        response = self.client.post(reverse('iot:add_goat'), payload)

        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            GoatImage.objects.filter(goat__goat_id='CAPTURED-PHOTO', angle='rear').exists()
        )

    def test_camera_capture_replaces_only_its_requested_angle(self):
        goat = self.create_goat('ANGLE-ISOLATION')
        front = GoatImage.objects.create(
            goat=goat, angle=GoatImage.FRONT, image=test_photo('front-existing.jpg')
        )
        right = GoatImage.objects.create(
            goat=goat, angle=GoatImage.RIGHT, image=test_photo('right-existing.jpg')
        )
        payload = self.goat_payload(goat.goat_id)
        payload.pop('weight_kg')
        captured = test_photo('left-capture.jpg', colors=('#3f3025', '#d9c7a0'))
        payload['captured_photos'] = json.dumps({
            GoatImage.LEFT: 'data:image/jpeg;base64,' + base64.b64encode(
                captured.read()
            ).decode('ascii')
        })

        response = self.client.post(
            reverse('iot:goat_detail_enhanced', args=[goat.goat_id]), payload
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(goat.images.get(angle=GoatImage.FRONT).pk, front.pk)
        self.assertEqual(goat.images.get(angle=GoatImage.RIGHT).pk, right.pk)
        self.assertTrue(goat.images.filter(angle=GoatImage.LEFT).exists())

    def test_uploading_the_same_angle_replaces_instead_of_duplicating(self):
        goat = self.create_goat()
        url = reverse('iot:upload_goat_image', args=[goat.goat_id])
        self.client.post(url, {'angle': 'left', 'image': test_photo('first.jpg')})
        first = goat.images.get(angle='left')
        first_name = first.image.name

        storage = first.image.storage
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(
                url,
                {'angle': 'left', 'image': test_photo('second.jpg', colors=('#1f4d34', '#b7d49c'))},
            )

        self.assertEqual(goat.images.filter(angle='left').count(), 1)
        first.refresh_from_db()
        self.assertNotEqual(first.image.name, first_name)
        self.assertFalse(storage.exists(first_name))

    def test_deleting_an_angle_photo_removes_record_and_file(self):
        goat = self.create_goat()
        photo = GoatImage.objects.create(
            goat=goat,
            angle=GoatImage.REAR,
            image=test_photo('rear.jpg'),
            is_primary=True,
        )
        stored_name = photo.image.name
        storage = photo.image.storage

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                reverse('iot:delete_goat_image', args=[goat.goat_id, photo.pk]),
            )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(GoatImage.objects.filter(pk=photo.pk).exists())
        self.assertFalse(storage.exists(stored_name))

    def test_legacy_image_remains_a_valid_inventory_fallback(self):
        goat = self.create_goat()
        legacy = GoatImage.objects.create(
            goat=goat,
            image='goat_images/legacy-reference.jpg',
            is_primary=True,
        )

        response = self.client.get(reverse('iot:goat_inventory'))

        self.assertEqual(response.status_code, 200)
        listed = next(item for item in response.context['goats'] if item.pk == goat.pk)
        self.assertEqual(listed.latest_image.pk, legacy.pk)

    def test_front_then_left_override_legacy_primary_for_inventory(self):
        goat = self.create_goat()
        legacy = GoatImage.objects.create(goat=goat, image='goat_images/legacy.jpg', is_primary=True)
        left = GoatImage.objects.create(goat=goat, image='goat_images/left.jpg', angle='left')
        self.assertEqual(GoatImage.preferred_from([legacy, left]), left)
        front = GoatImage.objects.create(goat=goat, image='goat_images/front.jpg', angle='front')
        self.assertEqual(GoatImage.preferred_from([legacy, left, front]), front)

    def test_quality_checks_reject_low_resolution_dark_bright_and_blurry_photos(self):
        cases = (
            test_photo('small.jpg', size=(320, 240)),
            flat_photo('dark.jpg', (3, 3, 3)),
            flat_photo('bright.jpg', (252, 252, 252)),
            flat_photo('blurred.jpg', (120, 120, 120)),
        )
        for upload in cases:
            with self.subTest(upload=upload.name), self.assertRaises(ValidationError):
                validated_goat_image(upload, check_quality=True)

    def test_bad_angle_photo_does_not_create_or_modify_goat(self):
        payload = self.goat_payload('BAD-PHOTO')
        payload['photo_front'] = flat_photo('dark.jpg', (2, 2, 2))

        response = self.client.post(reverse('iot:add_goat'), payload)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'too dark')
        self.assertFalse(Goat.objects.filter(goat_id='BAD-PHOTO').exists())

    def test_profile_renders_angle_selectors_and_guidance(self):
        goat = self.create_goat()
        GoatImage.objects.create(goat=goat, image='goat_images/front.jpg', angle='front')
        GoatImage.objects.create(goat=goat, image='goat_images/right.jpg', angle='right')

        response = self.client.get(reverse('iot:goat_detail_enhanced', args=[goat.goat_id]))

        self.assertContains(response, 'Front View')
        self.assertContains(response, 'Right Side View')
        self.assertContains(response, 'Position the goat facing directly toward the camera.')

    def test_comparison_uses_the_same_requested_angle(self):
        first = self.create_goat('COMPARE-A')
        second = self.create_goat('COMPARE-B')
        first_left = GoatImage.objects.create(
            goat=first, image='goat_images/a-left.jpg', angle='left'
        )
        second_left = GoatImage.objects.create(
            goat=second, image='goat_images/b-left.jpg', angle='left'
        )
        response = self.client.get(reverse('iot:goat_comparison'), {
            'goat_a': first.goat_id,
            'goat_b': second.goat_id,
            'angle': 'left',
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['selected_a']['photo'], first_left)
        self.assertEqual(response.context['selected_b']['photo'], second_left)
        self.assertContains(response, 'Left Side View')
