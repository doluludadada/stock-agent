class ReportParseFailure(ValueError):
    pass


class StrictParseFailure(ReportParseFailure):
    pass


class ParseRule:
    def apply(self, text: str) -> str:
        if not text:
            raise StrictParseFailure(text)
        return text
