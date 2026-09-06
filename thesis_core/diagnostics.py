"""Bounded public diagnostics that cannot replace an existing failure."""

from .security import redact_value

MAX_DIAGNOSTIC_CHARACTERS = 4096
OMITTED_DIAGNOSTIC = "Content withheld: safe redaction was unavailable."


def safe_exception_text(error: BaseException) -> str:
    """Redact an exception, withholding unsafe or oversized diagnostic text.

    Callers already handling a failed operation must preserve its durable state
    even if formatting or redacting its diagnostic fails. Never fall back to the
    original message, and avoid feeding oversized messages into the redactor.
    """
    try:
        message = str(error)
        if len(message) > MAX_DIAGNOSTIC_CHARACTERS:
            return OMITTED_DIAGNOSTIC
        redacted = redact_value(message)
        if not isinstance(redacted, str) or len(redacted) > MAX_DIAGNOSTIC_CHARACTERS:
            return OMITTED_DIAGNOSTIC
        return redacted
    except Exception:
        return OMITTED_DIAGNOSTIC
