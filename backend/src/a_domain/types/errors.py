class IllegalOrderTransition(ValueError):
    pass


class AiReportParseError(ValueError):
    """The model response holds no usable report or classification, so the stock gets no AI score or sentiment."""
