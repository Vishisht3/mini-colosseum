"""History entries are user runs saved in SQLite; they must be deletable."""
import os
import tempfile

from backend.store import RunStore
from backend.models import RunConfig


def test_delete_run_removes_trace():
    with tempfile.TemporaryDirectory() as tmp:
        store = RunStore(db_path=os.path.join(tmp, "test.db"))
        config = RunConfig(problem_statement="delete me")
        store.create_run(config, "2026-01-01 00:00:00")
        assert store.list_runs()
        assert store.delete_run(config.run_id) is True
        assert store.list_runs() == []
        assert store.export_trace_json(config.run_id) == {}
        assert store.delete_run(config.run_id) is False
