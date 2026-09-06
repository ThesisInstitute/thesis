"""Official-source adapters, loaded lazily for custody-only compatibility."""


def __getattr__(name):
    if name in {
        "CaptureResult",
        "HttpRequest",
        "HttpResponse",
        "capture",
        "get_source",
        "registered_sources",
        "capture_release_evidence",
        "release_evidence_from_bytes",
        "validate_source",
        "validate_observation",
        "observation_availability",
        "target_release_availability",
        "validate_resolution",
    }:
        from . import registry

        return getattr(registry, name)
    raise AttributeError(name)
