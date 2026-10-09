# Generated manually to expose RF-DETR checkpoints in model management.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ml_models', '0006_mlmodel_category_mlmodel_file_size_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='mlmodel',
            name='model_type',
            field=models.CharField(
                choices=[
                    ('yolov8', 'YOLOv8 (Ultralytics)'),
                    ('rfdetr', 'RF-DETR (auto-detect checkpoint)'),
                    ('roboflow', 'Roboflow Inference (Self-hosted)'),
                    ('roboflow-hosted', 'Roboflow Hosted API'),
                    ('yolo', 'YOLO (TensorFlow/Keras)'),
                    ('pytorch', 'PyTorch Model'),
                    ('sklearn', 'scikit-learn'),
                    ('tensorflow', 'TensorFlow/Keras'),
                ],
                default='yolo',
                max_length=100,
            ),
        ),
    ]
