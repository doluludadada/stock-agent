class DomainError(Exception):
    pass


class OrderVersionConflict(DomainError):
    pass
