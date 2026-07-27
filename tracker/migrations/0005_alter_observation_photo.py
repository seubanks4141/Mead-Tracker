from django.core.validators import FileExtensionValidator
from django.db import migrations, models

import tracker.models


class Migration(migrations.Migration):
    dependencies = [
        ("tracker", "0004_observation_photo"),
    ]

    operations = [
        migrations.AlterField(
            model_name="observation",
            name="photo",
            field=models.ImageField(
                blank=True,
                help_text=(
                    "Optional. Upload a JPEG, PNG, WebP, HEIC, or HEIF photo "
                    "up to 10 MB. Phone HEIC/HEIF photos are converted to JPEG."
                ),
                upload_to=tracker.models.observation_photo_upload_to,
                validators=[
                    FileExtensionValidator(
                        allowed_extensions=(
                            "jpg",
                            "jpeg",
                            "png",
                            "webp",
                            "heic",
                            "heif",
                        )
                    ),
                    tracker.models.validate_observation_photo_size,
                ],
            ),
        ),
    ]
