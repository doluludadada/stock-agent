class Runs:
    def __init__(self) -> None:
        self._running: set[str] = set()

    def start(self, run_id: str) -> None:
        class Started:
            def _mark(self, running: set[str]) -> None:
                running.add(run_id)

        Started()._mark(self._running)
