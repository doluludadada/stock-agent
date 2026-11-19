from a_domain.model.trading.account import Account


class LoadAccount:
    async def execute(self) -> Account:
        return Account(cash=0)
