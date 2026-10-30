from typing import override


class Base:
    def fetch(self) -> int:
        return 1


class Adapter(Base):
    @override
    def fetch(self) -> int:
        return 2
