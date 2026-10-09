import marketplace.models
import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("marketplace", "0014_marketplacelisting_is_featured"),
    ]

    operations = [
        migrations.AlterField(
            model_name="message",
            name="body",
            field=models.TextField(blank=True, max_length=2000),
        ),
        migrations.AddField(
            model_name="message",
            name="image_attachment",
            field=models.ImageField(
                blank=True,
                storage=marketplace.models.PrivateInquiryStorage(),
                upload_to=marketplace.models.inquiry_image_path,
                validators=[
                    django.core.validators.FileExtensionValidator(
                        ["jpg", "jpeg", "png", "webp"]
                    ),
                    marketplace.models.validate_inquiry_image_size,
                ],
            ),
        ),
        migrations.AddField(
            model_name="message",
            name="image_content_type",
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name="message",
            name="image_original_name",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="message",
            name="image_size",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
    ]
