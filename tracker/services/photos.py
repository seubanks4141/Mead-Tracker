"""Normalization helpers for photos uploaded from phones and computers."""

from io import BytesIO
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image, ImageOps


HEIF_FORMATS = {"HEIC", "HEIF"}


def normalize_observation_photo(photo):
    """Convert HEIC/HEIF uploads to a broadly displayable, oriented JPEG."""

    image_format = str(
        getattr(getattr(photo, "image", None), "format", "")
    ).upper()
    if image_format not in HEIF_FORMATS:
        return photo

    photo.seek(0)
    with Image.open(photo) as source:
        source.seek(0)
        oriented = ImageOps.exif_transpose(source)
        oriented.load()

        if "A" in oriented.getbands():
            normalized = Image.new("RGB", oriented.size, "white")
            normalized.paste(
                oriented,
                mask=oriented.getchannel("A"),
            )
        else:
            normalized = oriented.convert("RGB")

        output = BytesIO()
        normalized.save(
            output,
            format="JPEG",
            quality=88,
            optimize=True,
        )

    filename_stem = Path(photo.name).stem or "observation-photo"
    return SimpleUploadedFile(
        f"{filename_stem}.jpg",
        output.getvalue(),
        content_type="image/jpeg",
    )
