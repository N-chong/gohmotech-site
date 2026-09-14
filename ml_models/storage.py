"""
Storage backend for protected ML model files.

Model weights must NOT be publicly accessible. Django serves everything under
MEDIA_ROOT (via the dev static() helper and typically the web server in prod),
so uploaded models are stored in a SEPARATE directory outside MEDIA_ROOT and
have no public base_url. They can only be retrieved through an authenticated
download view.
"""

from django.conf import settings
from django.core.files.storage import FileSystemStorage

# A dedicated location, deliberately NOT under MEDIA_ROOT.
PROTECTED_MODELS_ROOT = getattr(
    settings, 'PROTECTED_MODELS_ROOT', settings.BASE_DIR / 'protected_media' / 'ml_models'
)


class ProtectedModelStorage(FileSystemStorage):
    """FileSystemStorage rooted outside MEDIA_ROOT with no public URL."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault('location', str(PROTECTED_MODELS_ROOT))
        # No base_url -> .url raises, which is intentional: these files are
        # never linked publicly.
        kwargs.setdefault('base_url', None)
        super().__init__(*args, **kwargs)


protected_model_storage = ProtectedModelStorage()
