"""Backfill, daily and a gated reconcile on fixture packs: shared by the summary tests and the image smoke."""
from pathlib import Path

from support import fixture_settings
from support_reconcile import A, B, X, Y, Q3_URL, Q4_URL, quarterly
from support_workflows import quarter_pack, replace_pack_body

TODAY = '2026-10-07'
BASE_Q3 = (A, B)
GATED_Q3 = (A,)


def scenario_settings():
    return fixture_settings(backfill={'start_quarter': '2026Q3', 'end_quarter': 'open'},
                            daily={'start_date': '2026-10-01'}, etl={'parser_version': 'fixture-index-parser-v1'},
                            http={'retry_base_seconds': 0.001, 'retry_cap_seconds': 0.001},
                            fixture={'allow_clock_override': True, 'allow_deadline_override': False})


def scenario_pack(root: Path, name: str, q3: tuple) -> Path:
    """A pack whose 2026Q3 quarterly lists `q3` and whose 2026Q4 quarterly lists X and Y; returns its manifest."""
    pack = quarter_pack(Path(root) / name, ('2026Q3', '2026Q4'), empty_daily=True)
    replace_pack_body(pack, Q3_URL, quarterly(q3))
    replace_pack_body(pack, Q4_URL, quarterly((X, Y)))
    return pack
