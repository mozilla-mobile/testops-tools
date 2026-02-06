import logging
import vertexai
from common.config import Settings

_INITIALIZED = False


def init_vertex(settings: Settings) -> None:
    """Initialize Vertex AI once per process."""
    global _INITIALIZED
    if _INITIALIZED:
        return

    project = settings.require_project()
    vertexai.init(project=project, location=settings.gcp_location)
    logging.getLogger(__name__).info(
        "Vertex AI initialized (project=%s, location=%s).",
        project,
        settings.gcp_location,
    )
    _INITIALIZED = True
