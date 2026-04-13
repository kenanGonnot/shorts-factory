"""Internal publishing domain for the pipeline's YouTube stage.

`PublishingTool` remains the single public LCEL node. This package keeps
validation, metadata shaping, and orchestration testable in isolation.
"""

from app.publishing.metadata import build_publish_metadata
from app.publishing.models import (
    PublishContext,
    PublishMetadata,
    PublishRequest,
    PublishResult,
)
from app.publishing.service import publish_video
from app.publishing.validate import PublishValidationError, validate_state

__all__ = [
    "PublishContext",
    "PublishMetadata",
    "PublishRequest",
    "PublishResult",
    "PublishValidationError",
    "build_publish_metadata",
    "publish_video",
    "validate_state",
]
