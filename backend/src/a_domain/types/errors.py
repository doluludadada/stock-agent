class IllegalOrderTransition(ValueError):
    pass


class AiReportParseError(ValueError):
    """The model response holds no usable report, so the stock gets no AI score."""
