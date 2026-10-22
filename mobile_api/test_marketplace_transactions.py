from io import BytesIO
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase
from PIL import Image

from iot.goat_models import Goat
from marketplace.auth import FARM_OPERATOR_GROUP_NAME, FARM_OWNER_GROUP_NAME
from marketplace.models import Conversation, MarketplaceListing, Message, Reservation
from marketplace.services import request_reservation


class MobileMarketplaceTransactionTests(APITestCase):
    def create_user(self, username, group_name=None):
        user = get_user_model().objects.create_user(username=username, password='safe-test-password')
        if group_name:
            group, _ = Group.objects.get_or_create(name=group_name)
            user.groups.add(group)
        return user

    def authenticate(self, user):
        token = Token.objects.create(user=user)
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {token.key}')

    def setUp(self):
        self.inquiry_directory = TemporaryDirectory()
        self.addCleanup(self.inquiry_directory.cleanup)
        storage = Message._meta.get_field('image_attachment').storage
        original_location = storage._location
        storage._location = self.inquiry_directory.name
        storage.__dict__.pop('base_location', None)
        storage.__dict__.pop('location', None)

        def restore_storage():
            storage._location = original_location
            storage.__dict__.pop('base_location', None)
            storage.__dict__.pop('location', None)

        self.addCleanup(restore_storage)
        self.owner = self.create_user('transaction-owner', FARM_OWNER_GROUP_NAME)
        self.buyer = self.create_user('transaction-buyer')
        goat = Goat.objects.create(
            goat_id='SMART-TXN', name='Maya', breed='boer', gender='female',
            owner=self.owner, record_source=Goat.SMART_FARM,
        )
        self.listing = MarketplaceListing.objects.create(
            goat=goat, seller=self.owner, price='18000.00',
            sales_description='Healthy Smart Farm goat.', status=MarketplaceListing.AVAILABLE,
        )
        self.conversation = Conversation.objects.create(listing=self.listing, buyer=self.buyer)
        self.buyer_message = Message.objects.create(
            conversation=self.conversation, sender=self.buyer, body='Is Maya available?'
        )

    def test_seller_inbox_reports_unread_and_detail_marks_message_read(self):
        self.authenticate(self.owner)
        inbox = self.client.get('/api/mobile/marketplace/seller/conversations/')
        self.assertEqual(inbox.status_code, 200)
        self.assertEqual(inbox.data['unread_count'], 1)
        self.assertEqual(inbox.data['conversations'][0]['buyer']['username'], self.buyer.username)

        detail = self.client.get(
            f'/api/mobile/marketplace/seller/conversations/{self.conversation.pk}/'
        )
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.data['messages'][0]['body'], 'Is Maya available?')
        self.buyer_message.refresh_from_db()
        self.assertTrue(self.buyer_message.is_read)

    def test_seller_can_reply_and_close_conversation(self):
        self.authenticate(self.owner)
        url = f'/api/mobile/marketplace/seller/conversations/{self.conversation.pk}/'
        reply = self.client.post(url, {'action': 'message', 'body': 'Yes, Maya is available.'}, format='json')
        self.assertEqual(reply.status_code, 201)
        self.assertTrue(Message.objects.filter(sender=self.owner, body__contains='Maya').exists())
        closed = self.client.post(url, {'action': 'close'}, format='json')
        self.assertEqual(closed.status_code, 200)
        self.assertEqual(closed.data['status'], Conversation.CLOSED)

    def test_seller_can_send_and_retrieve_private_image_reply(self):
        self.authenticate(self.owner)
        source = BytesIO()
        Image.new('RGB', (640, 480), 'green').save(source, format='PNG')
        upload = SimpleUploadedFile(
            'inspection.png', source.getvalue(), content_type='image/png'
        )
        url = f'/api/mobile/marketplace/seller/conversations/{self.conversation.pk}/'

        reply = self.client.post(
            url,
            {'action': 'message', 'body': '', 'image_attachment': upload},
            format='multipart',
        )
        self.assertEqual(reply.status_code, 201)
        self.assertTrue(reply.data['image_url'])
        message = Message.objects.get(pk=reply.data['id'])
        self.assertEqual(message.image_original_name, 'inspection.png')
        self.assertEqual(message.image_content_type, 'image/png')
        image = self.client.get(
            f'/api/mobile/marketplace/messages/{message.pk}/image/'
        )
        self.assertEqual(image.status_code, 200)
        self.assertEqual(image['Content-Type'], 'image/png')
        self.assertEqual(image['Cache-Control'], 'private, no-store')
        message.delete()

    def test_seller_attachment_rejects_unverified_image_content(self):
        self.authenticate(self.owner)
        url = f'/api/mobile/marketplace/seller/conversations/{self.conversation.pk}/'
        fake = SimpleUploadedFile(
            'fake.png', b'not-an-image', content_type='image/png'
        )
        response = self.client.post(
            url,
            {'action': 'message', 'body': '', 'image_attachment': fake},
            format='multipart',
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Message.objects.filter(sender=self.owner).exists())
    def test_seller_can_accept_pending_reservation(self):
        reservation = request_reservation(self.listing.pk, self.buyer, self.conversation)
        self.authenticate(self.owner)
        response = self.client.post(
            f'/api/mobile/marketplace/seller/reservations/{reservation.pk}/',
            {'action': 'accept', 'pickup_location': 'GoHMoTech Farm'}, format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['status'], Reservation.ACCEPTED)
        self.listing.refresh_from_db()
        self.assertEqual(self.listing.status, MarketplaceListing.RESERVED)

    def test_operator_cannot_access_seller_transactions(self):
        operator = self.create_user('transaction-operator', FARM_OPERATOR_GROUP_NAME)
        self.authenticate(operator)
        inbox = self.client.get('/api/mobile/marketplace/seller/conversations/')
        reservations = self.client.get('/api/mobile/marketplace/seller/reservations/')
        self.assertEqual(inbox.status_code, 403)
        self.assertEqual(reservations.status_code, 403)
