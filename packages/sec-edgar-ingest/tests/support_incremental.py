"""Twin lanes for the Stage 1b oracle (§5 item 3): the same inputs in two fresh stores.

`fast` builds as the release does, so an eligible quarter takes the incremental path (C5).
`full` forces today's full rebuild by making C4 refuse every input. Two stores give the same
generation bytes for the same inputs (plan 5, F6).
"""
from datetime import date
from unittest.mock import patch

from support_catalog import Lane
from sec_edgar_ingest.etl import incremental


class Twin:
    def __init__(self, day=date(2026, 10, 7)):
        self.fast, self.full = Lane(day), Lane(day)

    def close(self):
        self.fast.close()
        self.full.close()

    def pin(self, day):
        self.fast.pin(day)
        self.full.pin(day)

    def observation(self, *args, **kwargs):
        return self.fast.observation(*args, **kwargs), self.full.observation(*args, **kwargs)

    def build(self, pairs, previous=None, quarter='2026Q4'):
        """Both lanes' candidates, and the number of incremental builds the fast lane ran."""
        with patch.object(incremental, 'build_incremental', wraps=incremental.build_incremental) as built:
            fast = self.fast.build([pair[0] for pair in pairs], previous[0] if previous else None, quarter)
        with patch.object(incremental, 'eligible', return_value=False):
            full = self.full.build([pair[1] for pair in pairs], previous[1] if previous else None, quarter)
        return (fast, full), built.call_count
