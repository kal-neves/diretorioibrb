from io import BytesIO
import warnings

from django.core.exceptions import ValidationError
from PIL import Image, ImageOps, UnidentifiedImageError


MAX_BYTES = 1024 * 1024
MAX_SIDE = 1200


def process_photo(upload):
    data = upload.read(MAX_BYTES + 1)
    if not data or len(data) > MAX_BYTES:
        raise ValidationError({"photo": "Envie um recorte de até 1 MiB."})
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data), formats=["JPEG", "PNG", "WEBP"]) as source:
                if getattr(source, "n_frames", 1) != 1 or max(source.size) > MAX_SIDE:
                    raise ValueError
                source.load()
                oriented = ImageOps.exif_transpose(source).convert("RGBA")
                clean = Image.new("RGB", oriented.size, "white")
                clean.paste(oriented, mask=oriented.getchannel("A"))
                for quality in (85, 75, 65, 50):
                    output = BytesIO()
                    clean.save(output, format="JPEG", quality=quality, optimize=True)
                    if output.tell() <= MAX_BYTES:
                        return output.getvalue(), clean.width, clean.height
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError, Image.DecompressionBombError,
            Image.DecompressionBombWarning):
        pass
    raise ValidationError({"photo": "Use uma imagem estática JPEG, PNG ou WebP com lado máximo de 1.200 pixels."})
