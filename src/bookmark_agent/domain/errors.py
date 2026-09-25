"""Domain exceptions for the bookmark agent pipeline."""

from __future__ import annotations


class BookmarkAgentError(Exception):
    """Base class for all expected application errors."""


class ConfigError(BookmarkAgentError):
    """Raised when configuration is missing or invalid."""


class TreeNotBuiltError(BookmarkAgentError):
    """Raised when the bookmark graph pickle does not exist or cannot load."""


class BatchJobFailedError(BookmarkAgentError):
    """Raised when an OpenAI batch job finishes in a failed state."""


class NoPendingBatchError(BookmarkAgentError):
    """Raised when no pending batch jobs are available for processing."""


class BatchUploadError(BookmarkAgentError):
    """Raised when batch submission or persistence fails."""
