"""
Validation for uploaded ML model files.

Security requirements enforced here:
  * Validate the file type (extension allow-list for known weight formats).
  * Validate the file size (reject empty / oversized files).
  * Prevent arbitrary executable files from being uploaded.
  * Prevent path traversal via crafted filenames.

Metadata is stored separately from the file (in the MLModel row); this module
only concerns itself with the file itself.
"""

import os

from django.conf import settings
from django.core.exceptions import ValidationError

# Known model-weight extensions. This is an ALLOW-LIST — anything not here is
# rejected, which is what blocks arbitrary executables (.exe, .sh, .bat, .py...).
ALLOWED_MODEL_EXTENSIONS = {
    '.pt', '.pth', '.ckpt',  # PyTorch / YOLO / RF-DETR Lightning
    '.h5', '.keras',      # Keras / TensorFlow
    '.pb',                # TensorFlow SavedModel graph
    '.onnx',              # ONNX
    '.tflite',            # TensorFlow Lite
    '.pkl', '.joblib',    # scikit-learn
    '.weights',           # Darknet
}

# Extensions we explicitly refuse even if someone widens the allow-list later.
BLOCKED_EXTENSIONS = {
    '.exe', '.dll', '.so', '.dylib', '.bat', '.cmd', '.sh', '.bash',
    '.py', '.pyc', '.js', '.php', '.rb', '.pl', '.jar', '.msi', '.app',
    '.com', '.scr', '.ps1', '.vbs',
}

MAX_MODEL_FILE_SIZE = getattr(
    settings, 'MODEL_UPLOAD_MAX_FILE_SIZE', 500 * 1024 * 1024
)
MIN_MODEL_FILE_SIZE = 1                   # reject empty files


def _safe_basename(filename):
    """
    Return the bare filename, rejecting any path-traversal attempt.

    A legitimate upload has no directory separators in its name. Anything with
    '/', '\\', or '..' is treated as hostile.
    """
    if not filename:
        raise ValidationError("Uploaded file has no name.")

    # Normalize away any directory component the client may have sent.
    base = os.path.basename(filename.replace('\\', '/'))

    if not base or base in ('.', '..'):
        raise ValidationError("Invalid file name.")
    if '..' in base or '/' in base or '\\' in base:
        raise ValidationError("File name contains illegal path characters.")
    return base


def validate_model_upload(uploaded_file):
    """
    Validate an uploaded model file. Returns a dict of collected facts
    (safe_name, extension, size) on success; raises ValidationError otherwise.

    This performs static checks only — it never executes or imports the file.
    """
    safe_name = _safe_basename(getattr(uploaded_file, 'name', ''))
    ext = os.path.splitext(safe_name)[1].lower()

    if not ext:
        raise ValidationError("File has no extension; cannot determine its type.")

    if ext in BLOCKED_EXTENSIONS:
        raise ValidationError(
            f"'{ext}' files are not allowed (executable/script content is blocked)."
        )

    if ext not in ALLOWED_MODEL_EXTENSIONS:
        allowed = ', '.join(sorted(ALLOWED_MODEL_EXTENSIONS))
        raise ValidationError(
            f"Unsupported model file type '{ext}'. Allowed types: {allowed}."
        )

    size = getattr(uploaded_file, 'size', 0) or 0
    if size < MIN_MODEL_FILE_SIZE:
        raise ValidationError("Uploaded file is empty.")
    if size > MAX_MODEL_FILE_SIZE:
        limit_mb = MAX_MODEL_FILE_SIZE // (1024 * 1024)
        raise ValidationError(f"File is too large (limit is {limit_mb} MB).")

    return {'safe_name': safe_name, 'extension': ext, 'size': size}
