from io import BytesIO
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase
from PIL import Image

from iot.goat_models import Goat, GoatImage
from marketplace.auth import FARM_OPERATOR_GROUP_NAME, FARM_OWNER_GROUP_NAME
from marketplace.models import MarketplaceListing, SellerProfile


class MobileMarketplaceTests(APITestCase):
    def create_user(self, username, group_name=None):
        user = get_user_model().objects.create_user(
            username=username, password='safe-test-password'
        )
        if group_name:
            group, _ = Group.objects.get_or_create(name=group_name)
            user.groups.add(group)
        return user

    def authenticate(self, user):
        token = Token.objects.create(user=user)
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {token.key}')

    def setUp(self):
        self.media_directory = TemporaryDirectory()
        self.addCleanup(self.media_directory.cleanup)
        media_override = override_settings(MEDIA_ROOT=self.media_directory.name)
        media_override.enable()
        self.addCleanup(media_override.disable)
        self.owner = self.create_user('market-owner', FARM_OWNER_GROUP_NAME)
        self.approved_seller = self.create_user('approved-seller')
        SellerProfile.objects.create(
            user=self.approved_seller,
            farm_name='Green Hills Farm',
            municipality='Lipa',
            province='Batangas',
            contact_number='09171234567',
            farm_description='Healthy community goats.',
            status=SellerProfile.APPROVED,
        )
        self.public_goat = Goat.objects.create(
            goat_id='COMM-1', name='Maya', breed='boer', gender='female',
            owner=self.approved_seller, record_source=Goat.COMMUNITY,
        )
        self.public_listing = MarketplaceListing.objects.create(
            goat=self.public_goat, seller=self.approved_seller,
            price='15000.00', sales_description='Healthy Boer doe.',
            status=MarketplaceListing.AVAILABLE,
        )

    def test_catalog_returns_trusted_listing_and_public_seller_identity(self):
        pending_seller = self.create_user('pending-seller')
        SellerProfile.objects.create(
            user=pending_seller, farm_name='Pending Farm', municipality='Lipa',
            province='Batangas', contact_number='09170000000',
            farm_description='Pending.', status=SellerProfile.PENDING,
        )
        pending_goat = Goat.objects.create(
            goat_id='COMM-2', breed='native', gender='male', owner=pending_seller,
            record_source=Goat.COMMUNITY,
        )
        MarketplaceListing.objects.create(
            goat=pending_goat, seller=pending_seller, price='9000.00',
            sales_description='Not approved.', status=MarketplaceListing.AVAILABLE,
        )
        self.authenticate(self.owner)

        response = self.client.get('/api/mobile/marketplace/listings/', {'search': 'Maya'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 1)
        result = response.data['results'][0]
        self.assertEqual(result['id'], self.public_listing.id)
        self.assertEqual(result['seller']['farm_name'], 'Green Hills Farm')
        self.assertEqual(result['seller']['location'], 'Lipa, Batangas')
        self.assertNotIn('contact_number', result['seller'])

    def test_owner_can_create_draft_but_cannot_publish_without_photo(self):
        goat = Goat.objects.create(
            goat_id='SMART-NEW', name='Luna', breed='native', gender='female',
            owner=self.owner, record_source=Goat.SMART_FARM,
        )
        self.authenticate(self.owner)

        response = self.client.post('/api/mobile/marketplace/manage/', {
            'goat_id': goat.id,
            'price': '12000.00',
            'sales_description': 'Healthy Smart Farm goat.',
        }, format='json')

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['status'], MarketplaceListing.DRAFT)
        listing_id = response.data['id']
        publish = self.client.post(
            f'/api/mobile/marketplace/manage/{listing_id}/',
            {'action': 'publish'}, format='json',
        )
        self.assertEqual(publish.status_code, 400)
        self.assertIn('photo', publish.data['detail'].lower())

    def test_owner_can_upload_select_and_delete_listing_photos(self):
        goat = Goat.objects.create(
            goat_id='SMART-PHOTOS', name='Photo Goat', breed='native', gender='female',
            owner=self.owner, record_source=Goat.SMART_FARM,
        )
        listing = MarketplaceListing.objects.create(
            goat=goat, seller=self.owner, price='11000.00',
            sales_description='Owner photo workflow.',
        )
        self.authenticate(self.owner)

        def photo(name, color):
            source = BytesIO()
            Image.new('RGB', (1200, 900), color).save(source, format='PNG')
            return SimpleUploadedFile(name, source.getvalue(), content_type='image/png')

        uploaded = self.client.post(
            f'/api/mobile/marketplace/manage/{listing.pk}/images/',
            {'photos': [photo('front.png', 'green'), photo('side.png', 'brown')]},
            format='multipart',
        )
        self.assertEqual(uploaded.status_code, 200)
        self.assertEqual(len(uploaded.data['images']), 2)
        self.assertTrue(all(item['can_delete'] for item in uploaded.data['images']))
        first, second = list(GoatImage.objects.filter(goat=goat).order_by('pk'))

        selected = self.client.post(
            f'/api/mobile/marketplace/manage/{listing.pk}/images/{second.pk}/',
            {'action': 'set_primary'}, format='json',
        )
        self.assertEqual(selected.status_code, 200)
        self.assertEqual(
            next(item['id'] for item in selected.data['images'] if item['is_primary']),
            second.pk,
        )

        deleted = self.client.post(
            f'/api/mobile/marketplace/manage/{listing.pk}/images/{first.pk}/',
            {'action': 'delete'}, format='json',
        )
        self.assertEqual(deleted.status_code, 200)
        self.assertFalse(GoatImage.objects.filter(pk=first.pk).exists())

    def test_photo_delete_protects_farm_records_and_live_final_photo(self):
        goat = Goat.objects.create(
            goat_id='SMART-PROTECTED', breed='native', gender='female',
            owner=self.owner, record_source=Goat.SMART_FARM,
        )
        listing = MarketplaceListing.objects.create(
            goat=goat, seller=self.owner, price='13000.00',
            sales_description='Protected photo workflow.',
            status=MarketplaceListing.AVAILABLE,
        )
        source = BytesIO()
        Image.new('RGB', (300, 300), 'white').save(source, format='JPEG')
        photo = GoatImage.objects.create(
            goat=goat,
            image=SimpleUploadedFile('existing.jpg', source.getvalue(), content_type='image/jpeg'),
            description='Existing farm reference photo',
            is_primary=True,
        )
        self.authenticate(self.owner)
        url = f'/api/mobile/marketplace/manage/{listing.pk}/images/{photo.pk}/'

        protected = self.client.post(url, {'action': 'delete'}, format='json')
        self.assertEqual(protected.status_code, 403)
        photo.description = 'Uploaded from GoHMoTech owner app'
        photo.save(update_fields=['description'])
        final_live = self.client.post(url, {'action': 'delete'}, format='json')
        self.assertEqual(final_live.status_code, 409)
        self.assertTrue(GoatImage.objects.filter(pk=photo.pk).exists())

    def test_operator_cannot_open_management_workspace(self):
        operator = self.create_user('market-operator', FARM_OPERATOR_GROUP_NAME)
        self.authenticate(operator)

        response = self.client.get('/api/mobile/marketplace/manage/')

        self.assertEqual(response.status_code, 403)