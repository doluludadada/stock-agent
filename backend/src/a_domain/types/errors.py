class IllegalOrderTransition(ValueError):
    pass


class AiReportParseError(ValueError):
    """The model response holds no usable report or classification, so the stock gets no AI score or sentiment."""


class TechnicalSettingsConflictError(RuntimeError):
    """The owner's technical settings changed after the caller read them. Read them again before saving."""


class ListingUnavailableError(RuntimeError):
    """The exchange listing could not be loaded, so no stock can be found in it. It is not an empty market."""


class SettingsConflictError(RuntimeError):
    """The settings file changed after the caller read it: another tab or an editor saved first. Read it again."""


class SettingsEditError(ValueError):
    """The edit names a setting of another file, or a backup that does not exist. Nothing was written."""
