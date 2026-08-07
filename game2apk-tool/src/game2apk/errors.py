"""Domain errors used by both the CLI and the Tkinter front end."""


class Game2ApkError(Exception):
    """Base class for expected, user-diagnosable failures."""


class BlockedError(Game2ApkError):
    """A safety or compatibility gate intentionally stopped the pipeline."""


class ConfigurationError(Game2ApkError):
    """A versioned configuration or user setting is invalid."""


class ExternalToolError(Game2ApkError):
    """An external tool was missing or returned a non-zero exit code."""


class TranslationError(Game2ApkError):
    """Translation transport or response validation failure."""


class CancelledError(Game2ApkError):
    """A long-running operation was cancelled by the user."""

