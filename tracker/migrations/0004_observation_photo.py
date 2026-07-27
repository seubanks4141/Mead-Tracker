from django.core.validators import FileExtensionValidator
from django.db import migrations, models

import tracker.models


class Migration(migrations.Migration):
    dependencies = [
        ("tracker", "0003_batch_stage_planning_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="observation",
            name="photo",
            field=models.ImageField(
                blank=True,
                help_text=(
                    "Optional. Upload a JPEG, PNG, or WebP photo up to 10 MB."
                ),
                upload_to=tracker.models.observation_photo_upload_to,
                validators=[
                    FileExtensionValidator(
                        allowed_extensions=("jpg", "jpeg", "png", "webp")
                    ),
                    tracker.models.validate_observation_photo_size,
                ],
            ),
        ),
    ]
