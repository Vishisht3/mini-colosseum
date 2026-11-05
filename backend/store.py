"""
SQLite Storage and Trace Engine for Mini-Colosseum.
Based on Section 7 & Section 10 of Mini-Colosseum Specification v1.0.
Every node, edge, input, output, and usage figure is written as each completes.
Every run is saved as a replayable trace that can be reopened without calling any model.
"""

import sqlite3
import json
import os
import sys
from typing import Dict, Any, List, Optional
from .models import Node, Edge, Event, RunConfig, KnowledgeEntry

def get_default_data_dir() -> str:
    env_dir = os.environ.get("MINI_COLOSSEUM_DATA_DIR")
    if env_dir:
        return env_dir
    if sys.platform == "win32":
        app_data = os.environ.get("APPDATA") or os.path.expanduser("~\\AppData\\Roaming")
        return os.path.join(app_data, "Mini-Colosseum")
    elif sys.platform == "darwin":
        return os.path.expanduser("~/Library/Application Support/Mini-Colosseum")
    else:
        return os.path.expanduser("~/.local/share/mini-colosseum")

DEFAULT_DB_DIR = get_default_data_dir()


class RunStore:
    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            os.makedirs(DEFAULT_DB_DIR, exist_ok=True)
            self.db_path = os.path.join(DEFAULT_DB_DIR, "mini_colosseum.db")
        else:
            self.db_path = db_path
            os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _execute(self, query: str, params: tuple = ()):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            conn.commit()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                problem TEXT,
                status TEXT,
                stage TEXT,
                round INTEGER,
                cost_usd REAL DEFAULT 0.0,
                cost_meta_usd REAL DEFAULT 0.0,
                cost_baseten_usd REAL DEFAULT 0.0,
                tokens_in INTEGER DEFAULT 0,
                tokens_cached INTEGER DEFAULT 0,
                tokens_out INTEGER DEFAULT 0,
                tokens_meta_in INTEGER DEFAULT 0,
                tokens_meta_out INTEGER DEFAULT 0,
                tokens_baseten_in INTEGER DEFAULT 0,
                tokens_baseten_out INTEGER DEFAULT 0,
                created_at TEXT,
                finished_at TEXT,
                config_json TEXT,
                assembled_latex TEXT
            )
            """)

            cursor.execute("""
            CREATE TABLE IF NOT EXISTS nodes (
                node_id TEXT,
                run_id TEXT,
                type TEXT,
                stage TEXT,
                round INTEGER,
                status TEXT,
                parents_json TEXT,
                label TEXT,
                model TEXT,
                provider TEXT DEFAULT 'meta',
                primary_provider TEXT DEFAULT 'meta',
                primary_model TEXT,
                fallback_used INTEGER DEFAULT 0,
                fallback_reason TEXT,
                tokens_in INTEGER,
                tokens_cached INTEGER,
                tokens_out INTEGER,
                cost_usd REAL,
                input_summary TEXT,
                input_ref TEXT,
                output_json TEXT,
                analysis_json TEXT,
                danus_fingerprint TEXT,
                is_stale INTEGER DEFAULT 0,
                is_invalidated INTEGER DEFAULT 0,
                rollouts_json TEXT,
                falsifier_report_json TEXT,
                objections_json TEXT,
                retry_count INTEGER DEFAULT 0,
                started_at TEXT,
                finished_at TEXT,
                PRIMARY KEY (run_id, node_id)
            )
            """)

            # Safe column migrations for existing databases
            existing_run_cols = {row[1] for row in cursor.execute("PRAGMA table_info(runs)").fetchall()}
            for col_name, col_type in [
                ("cost_meta_usd", "REAL DEFAULT 0.0"),
                ("cost_baseten_usd", "REAL DEFAULT 0.0"),
                ("tokens_meta_in", "INTEGER DEFAULT 0"),
                ("tokens_meta_out", "INTEGER DEFAULT 0"),
                ("tokens_baseten_in", "INTEGER DEFAULT 0"),
                ("tokens_baseten_out", "INTEGER DEFAULT 0"),
            ]:
                if col_name not in existing_run_cols:
                    cursor.execute(f"ALTER TABLE runs ADD COLUMN {col_name} {col_type}")

            existing_node_cols = {row[1] for row in cursor.execute("PRAGMA table_info(nodes)").fetchall()}
            for col_name, col_type in [
                ("provider", "TEXT DEFAULT 'meta'"),
                ("primary_provider", "TEXT DEFAULT 'meta'"),
                ("primary_model", "TEXT"),
                ("fallback_used", "INTEGER DEFAULT 0"),
                ("fallback_reason", "TEXT"),
                ("analysis_json", "TEXT"),
                ("danus_fingerprint", "TEXT"),
                ("is_stale", "INTEGER DEFAULT 0"),
                ("is_invalidated", "INTEGER DEFAULT 0"),
                ("rollouts_json", "TEXT"),
            ]:
                if col_name not in existing_node_cols:
                    cursor.execute(f"ALTER TABLE nodes ADD COLUMN {col_name} {col_type}")

            cursor.execute("""
            CREATE TABLE IF NOT EXISTS edges (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT,
                source TEXT,
                target TEXT,
                edge_type TEXT
            )
            """)

            cursor.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT,
                seq INTEGER,
                timestamp TEXT,
                event_type TEXT,
                payload_json TEXT
            )
            """)

            cursor.execute("""
            CREATE TABLE IF NOT EXISTS knowledge (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT,
                entry_type TEXT,
                title TEXT,
                contents TEXT,
                source TEXT,
                caveats TEXT
            )
            """)

            cursor.execute("""
            CREATE TABLE IF NOT EXISTS hmed_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                record_id TEXT,
                run_id TEXT,
                stage TEXT,
                subproblem_index INTEGER,
                failed_draft TEXT,
                critique TEXT,
                revised_draft TEXT,
                downstream_verdict TEXT,
                attribution_defect TEXT,
                cost_usd REAL,
                model_solver TEXT,
                model_falsifier TEXT
            )
            """)

            cursor.execute("""
            CREATE TABLE IF NOT EXISTS raw_provenance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                claim_id TEXT,
                run_id TEXT,
                source_node TEXT,
                target_statement TEXT,
                falsifier_verdict TEXT,
                failure_point TEXT,
                boundary_cases_json TEXT
            )
            """)
            conn.commit()
        finally:
            conn.close()

    def create_run(self, config: RunConfig, created_at: str):
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            clean_cfg = config.model_dump()
            clean_cfg.pop("baseten_api_key", None)
            clean_cfg.pop("api_key", None)
            cursor.execute("""
            INSERT OR REPLACE INTO runs (
                run_id, problem, status, stage, round, cost_usd,
                tokens_in, tokens_cached, tokens_out, created_at, finished_at,
                config_json, assembled_latex
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                config.run_id,
                config.problem_statement,
                "running",
                "exploration",
                1,
                0.0,
                0,
                0,
                0,
                created_at,
                None,
                json.dumps(clean_cfg),
                "",
            ))
            conn.commit()
        finally:
            conn.close()

    def update_run_status(
        self,
        run_id: str,
        status: str,
        stage: str,
        round_num: int,
        cost_usd: float,
        tokens_in: int,
        tokens_cached: int,
        tokens_out: int,
        finished_at: Optional[str] = None,
        assembled_latex: Optional[str] = None,
        cost_meta_usd: Optional[float] = None,
        cost_baseten_usd: Optional[float] = None,
        tokens_meta_in: Optional[int] = None,
        tokens_meta_out: Optional[int] = None,
        tokens_baseten_in: Optional[int] = None,
        tokens_baseten_out: Optional[int] = None,
    ):
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            # Section 7.C: Prevent accidental status resets.
            # Never allow progress events to overwrite a terminal status.
            cursor.execute("SELECT status FROM runs WHERE run_id = ?", (run_id,))
            row = cursor.fetchone()
            current_status = row[0] if row else None
            terminal_statuses = {"completed", "cancelled", "budget_exceeded", "failed", "accepted", "rejected"}
            if current_status in terminal_statuses and status not in terminal_statuses:
                status_to_write = current_status
            else:
                status_to_write = status

            cursor.execute("""
            UPDATE runs SET
                status = ?,
                stage = ?,
                round = ?,
                cost_usd = ?,
                tokens_in = ?,
                tokens_cached = ?,
                tokens_out = ?,
                finished_at = COALESCE(?, finished_at),
                assembled_latex = COALESCE(?, assembled_latex),
                cost_meta_usd = COALESCE(?, cost_meta_usd),
                cost_baseten_usd = COALESCE(?, cost_baseten_usd),
                tokens_meta_in = COALESCE(?, tokens_meta_in),
                tokens_meta_out = COALESCE(?, tokens_meta_out),
                tokens_baseten_in = COALESCE(?, tokens_baseten_in),
                tokens_baseten_out = COALESCE(?, tokens_baseten_out)
            WHERE run_id = ?
            """, (
                status_to_write,
                stage,
                round_num,
                cost_usd,
                tokens_in,
                tokens_cached,
                tokens_out,
                finished_at,
                assembled_latex,
                cost_meta_usd,
                cost_baseten_usd,
                tokens_meta_in,
                tokens_meta_out,
                tokens_baseten_in,
                tokens_baseten_out,
                run_id,
            ))
            conn.commit()
        finally:
            conn.close()

    def save_node(self, run_id: str, node: Node):
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT OR REPLACE INTO nodes (
                node_id, run_id, type, stage, round, status,
                parents_json, label, model, provider, primary_provider, primary_model,
                fallback_used, fallback_reason,
                tokens_in, tokens_cached, tokens_out,
                cost_usd, input_summary, input_ref, output_json,
                analysis_json, danus_fingerprint, is_stale, is_invalidated, rollouts_json,
                falsifier_report_json, objections_json, retry_count,
                started_at, finished_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                node.id,
                run_id,
                node.type,
                node.stage,
                node.round,
                node.status,
                json.dumps(node.parents),
                node.label,
                node.model,
                getattr(node, "provider", "meta"),
                getattr(node, "primary_provider", "meta"),
                getattr(node, "primary_model", None),
                1 if getattr(node, "fallback_used", False) else 0,
                getattr(node, "fallback_reason", None),
                node.tokens_in,
                node.tokens_cached,
                node.tokens_out,
                node.cost_usd,
                node.input_summary,
                node.input_ref,
                json.dumps(node.output),
                json.dumps(getattr(node, "analysis", None)) if getattr(node, "analysis", None) else None,
                getattr(node, "danus_fingerprint", None),
                1 if getattr(node, "is_stale", False) else 0,
                1 if getattr(node, "is_invalidated", False) else 0,
                json.dumps(getattr(node, "rollouts", [])) if getattr(node, "rollouts", None) else None,
                json.dumps(node.falsifier_report) if node.falsifier_report else None,
                json.dumps(node.objections),
                node.retry_count,
                node.started_at,
                node.finished_at,
            ))
            conn.commit()
        finally:
            conn.close()

    def save_edge(self, run_id: str, edge: Edge):
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("""
            SELECT 1 FROM edges WHERE run_id = ? AND source = ? AND target = ? AND edge_type = ?
            """, (run_id, edge.source, edge.target, edge.type))
            if not cursor.fetchone():
                cursor.execute("""
                INSERT INTO edges (run_id, source, target, edge_type)
                VALUES (?, ?, ?, ?)
                """, (run_id, edge.source, edge.target, edge.type))
                conn.commit()
        finally:
            conn.close()

    def save_event(self, event: Event):
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT INTO events (run_id, seq, timestamp, event_type, payload_json)
            VALUES (?, ?, ?, ?, ?)
            """, (
                event.run_id,
                event.seq,
                event.timestamp,
                event.event_type,
                json.dumps(event.payload),
            ))
            conn.commit()
        finally:
            conn.close()

    def add_knowledge(self, run_id: str, entry: KnowledgeEntry):
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT INTO knowledge (run_id, entry_type, title, contents, source, caveats)
            VALUES (?, ?, ?, ?, ?, ?)
            """, (
                run_id,
                entry.entry_type,
                entry.title,
                entry.contents,
                entry.source,
                entry.caveats,
            ))
            conn.commit()
        finally:
            conn.close()

    def add_raw_provenance(self, run_id: str, entry: Dict[str, Any]):
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT INTO raw_provenance (claim_id, run_id, source_node, target_statement, falsifier_verdict, failure_point, boundary_cases_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                entry.get("claim_id", ""),
                run_id,
                entry.get("source_node", ""),
                entry.get("target_statement", ""),
                entry.get("falsifier_verdict", "survives"),
                entry.get("failure_point"),
                json.dumps(entry.get("tested_boundary_cases", [])),
            ))
            conn.commit()
        finally:
            conn.close()

    def get_raw_provenance(self, run_id: str) -> List[Dict[str, Any]]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM raw_provenance WHERE run_id = ?", (run_id,))
            rows = cursor.fetchall()
            res = []
            for r in rows:
                item = dict(r)
                item["tested_boundary_cases"] = json.loads(r["boundary_cases_json"] or "[]")
                res.append(item)
            return res
        finally:
            conn.close()

    def save_hmed_record(self, record: Any):
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            data = record.model_dump() if hasattr(record, "model_dump") else record
            cursor.execute("""
            INSERT INTO hmed_records (
                record_id, run_id, stage, subproblem_index, failed_draft,
                critique, revised_draft, downstream_verdict, attribution_defect,
                cost_usd, model_solver, model_falsifier
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                data.get("record_id", ""),
                data.get("run_id", ""),
                data.get("stage", ""),
                data.get("subproblem_index"),
                data.get("failed_draft", ""),
                data.get("critique", ""),
                data.get("revised_draft", ""),
                data.get("downstream_verdict", "accepted"),
                data.get("attribution_defect"),
                data.get("cost_usd", 0.0),
                data.get("model_solver", "muse-spark-1.3"),
                data.get("model_falsifier", "muse-wonder-1.0"),
            ))
            conn.commit()
        finally:
            conn.close()

    def export_hmed_records(self, run_id: str) -> List[Dict[str, Any]]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM hmed_records WHERE run_id = ?", (run_id,))
            return [dict(r) for r in cursor.fetchall()]
        finally:
            conn.close()

    def export_hmed_jsonl(self, run_id: str) -> str:
        records = self.export_hmed_records(run_id)
        return "\n".join(json.dumps(r) for r in records)

    def get_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,))
            row = cursor.fetchone()
            if not row:
                return None
            return dict(row)
        finally:
            conn.close()

    def list_runs(self) -> List[Dict[str, Any]]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT run_id, problem, status, stage, round, cost_usd, tokens_in, tokens_out, created_at, finished_at FROM runs ORDER BY created_at DESC")
            return [dict(r) for r in cursor.fetchall()]
        finally:
            conn.close()

    def delete_run(self, run_id: str) -> bool:
        """Delete a run and all of its trace data. Returns True if a run existed."""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT run_id FROM runs WHERE run_id = ?", (run_id,))
            if not cursor.fetchone():
                return False
            for table in ("nodes", "edges", "events", "knowledge", "hmed_records", "raw_provenance", "runs"):
                cursor.execute(f"DELETE FROM {table} WHERE run_id = ?", (run_id,))
            conn.commit()
            return True
        finally:
            conn.close()

    def export_trace_json(self, run_id: str) -> Dict[str, Any]:
        """Produce a complete replayable trace artifact as JSON."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,))
            run_row = cursor.fetchone()
            if not run_row:
                return {}

            cursor.execute("SELECT * FROM nodes WHERE run_id = ? ORDER BY started_at ASC", (run_id,))
            nodes = []
            for r in cursor.fetchall():
                node_dict = dict(r)
                node_dict["parents"] = json.loads(r["parents_json"] or "[]")
                node_dict["output"] = json.loads(r["output_json"] or "{}")
                node_dict["analysis"] = json.loads(node_dict["analysis_json"]) if node_dict.get("analysis_json") else None
                node_dict["rollouts"] = json.loads(node_dict["rollouts_json"]) if node_dict.get("rollouts_json") else []
                node_dict["falsifier_report"] = json.loads(node_dict["falsifier_report_json"]) if node_dict.get("falsifier_report_json") else None
                node_dict["objections"] = json.loads(node_dict["objections_json"] or "[]")
                node_dict["danus_fingerprint"] = node_dict.get("danus_fingerprint")
                node_dict["is_stale"] = bool(node_dict.get("is_stale", 0))
                node_dict["is_invalidated"] = bool(node_dict.get("is_invalidated", 0))
                node_dict["provider"] = node_dict.get("provider", "meta")
                node_dict["primary_provider"] = node_dict.get("primary_provider", "meta")
                node_dict["primary_model"] = node_dict.get("primary_model")
                node_dict["fallback_used"] = bool(node_dict.get("fallback_used", 0))
                node_dict["fallback_reason"] = node_dict.get("fallback_reason")
                nodes.append(node_dict)

            cursor.execute("SELECT source, target, edge_type FROM edges WHERE run_id = ?", (run_id,))
            edges = [dict(r) for r in cursor.fetchall()]

            cursor.execute("SELECT seq, timestamp, event_type, payload_json FROM events WHERE run_id = ? ORDER BY seq ASC", (run_id,))
            events = []
            for r in cursor.fetchall():
                ev = dict(r)
                ev["payload"] = json.loads(r["payload_json"] or "{}")
                events.append(ev)

            cursor.execute("SELECT entry_type, title, contents, source, caveats FROM knowledge WHERE run_id = ?", (run_id,))
            knowledge = [dict(r) for r in cursor.fetchall()]

            cursor.execute("SELECT record_id, stage, subproblem_index, failed_draft, critique, revised_draft, downstream_verdict, attribution_defect, cost_usd, model_solver, model_falsifier FROM hmed_records WHERE run_id = ?", (run_id,))
            hmed_records = [dict(r) for r in cursor.fetchall()]

            cursor.execute("SELECT claim_id, source_node, target_statement, falsifier_verdict, failure_point, boundary_cases_json FROM raw_provenance WHERE run_id = ?", (run_id,))
            raw_prov = []
            for r in cursor.fetchall():
                item = dict(r)
                item["tested_boundary_cases"] = json.loads(r["boundary_cases_json"] or "[]")
                raw_prov.append(item)

            run_dict = dict(run_row)
            if "config_json" in run_dict and run_dict["config_json"]:
                try:
                    loaded_cfg = json.loads(run_dict["config_json"])
                    loaded_cfg.pop("baseten_api_key", None)
                    loaded_cfg.pop("api_key", None)
                    run_dict["config_json"] = json.dumps(loaded_cfg)
                except Exception:
                    pass

            return {
                "version": "2.0",
                "harness": "Mini-Colosseum v2.0 (Deterministic Multi-Agent Research Harness)",
                "run": run_dict,
                "nodes": nodes,
                "edges": edges,
                "events": events,
                "knowledge_directory": knowledge,
                "raw_provenance": raw_prov,
                "hmed_records": hmed_records,
                "assembled_latex": run_row["assembled_latex"] or "",
            }
        finally:
            conn.close()

    def export_trace_jsonl(self, run_id: str) -> str:
        """Export trace as newline-delimited JSONL stream for streaming replay."""
        trace = self.export_trace_json(run_id)
        if not trace:
            return ""
        lines = []
        # Header line
        lines.append(json.dumps({
            "record_type": "meta",
            "version": trace.get("version", "2.0"),
            "harness": trace.get("harness", ""),
            "run": trace.get("run", {}),
            "assembled_latex": trace.get("assembled_latex", ""),
        }))
        # Knowledge entries
        for k in trace.get("knowledge_directory", []):
            lines.append(json.dumps({"record_type": "knowledge", "data": k}))
        # Provenance entries
        for p in trace.get("raw_provenance", []):
            lines.append(json.dumps({"record_type": "provenance", "data": p}))
        # Nodes
        for n in trace.get("nodes", []):
            lines.append(json.dumps({"record_type": "node", "data": n}))
        # Edges
        for e in trace.get("edges", []):
            lines.append(json.dumps({"record_type": "edge", "data": e}))
        # Events (in sequential order for step replay)
        for ev in trace.get("events", []):
            lines.append(json.dumps({"record_type": "event", "data": ev}))
        # HMED records
        for h in trace.get("hmed_records", []):
            lines.append(json.dumps({"record_type": "hmed", "data": h}))
        return "\n".join(lines)

    def import_trace_jsonl(self, jsonl_content: str) -> str:
        """Import a JSONL trace for offline replay."""
        nodes = []
        edges = []
        events = []
        knowledge = []
        raw_prov = []
        hmed_records = []
        run_data = {}
        assembled_latex = ""

        for line in jsonl_content.strip().splitlines():
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            rec_type = record.get("record_type")
            if rec_type == "meta":
                run_data = record.get("run", {})
                assembled_latex = record.get("assembled_latex", "")
            elif rec_type == "node":
                nodes.append(record.get("data", {}))
            elif rec_type == "edge":
                edges.append(record.get("data", {}))
            elif rec_type == "event":
                events.append(record.get("data", {}))
            elif rec_type == "knowledge":
                knowledge.append(record.get("data", {}))
            elif rec_type == "provenance":
                raw_prov.append(record.get("data", {}))
            elif rec_type == "hmed":
                hmed_records.append(record.get("data", {}))

        trace = {
            "version": "2.0",
            "run": run_data,
            "assembled_latex": assembled_latex,
            "nodes": nodes,
            "edges": edges,
            "events": events,
            "knowledge_directory": knowledge,
            "raw_provenance": raw_prov,
            "hmed_records": hmed_records,
        }
        return self.import_trace_json(trace)

    def import_trace_json(self, trace: Dict[str, Any]) -> str:
        """Import a JSON trace for instant offline replay."""
        run_data = trace.get("run", {})
        run_id = run_data.get("run_id", "imported_run")
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT OR REPLACE INTO runs (
                run_id, problem, status, stage, round, cost_usd,
                tokens_in, tokens_cached, tokens_out, created_at, finished_at,
                config_json, assembled_latex,
                cost_meta_usd, cost_baseten_usd, tokens_meta_in, tokens_meta_out,
                tokens_baseten_in, tokens_baseten_out
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                run_id,
                run_data.get("problem", ""),
                run_data.get("status", "accepted"),
                run_data.get("stage", "verification"),
                run_data.get("round", 1),
                run_data.get("cost_usd", 0.0),
                run_data.get("tokens_in", 0),
                run_data.get("tokens_cached", 0),
                run_data.get("tokens_out", 0),
                run_data.get("created_at", ""),
                run_data.get("finished_at", ""),
                json.dumps(trace.get("config", {})),
                trace.get("assembled_latex", run_data.get("assembled_latex", "")),
                run_data.get("cost_meta_usd", 0.0),
                run_data.get("cost_baseten_usd", 0.0),
                run_data.get("tokens_meta_in", 0),
                run_data.get("tokens_meta_out", 0),
                run_data.get("tokens_baseten_in", 0),
                run_data.get("tokens_baseten_out", 0),
            ))

            for n in trace.get("nodes", []):
                cursor.execute("""
                INSERT OR REPLACE INTO nodes (
                    node_id, run_id, type, stage, round, status,
                    parents_json, label, model, provider, tokens_in, tokens_cached, tokens_out,
                    cost_usd, input_summary, input_ref, output_json,
                    analysis_json, danus_fingerprint, is_stale, is_invalidated, rollouts_json,
                    falsifier_report_json, objections_json, retry_count,
                    started_at, finished_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    n.get("node_id") or n.get("id"),
                    run_id,
                    n.get("type", "explorer"),
                    n.get("stage", "exploration"),
                    n.get("round", 1),
                    n.get("status", "accepted"),
                    json.dumps(n.get("parents", [])),
                    n.get("label", ""),
                    n.get("model", "meta-models/muse-spark-open-1026"),
                    n.get("provider", "meta"),
                    n.get("tokens_in", 0),
                    n.get("tokens_cached", 0),
                    n.get("tokens_out", 0),
                    n.get("cost_usd", 0.0),
                    n.get("input_summary", ""),
                    n.get("input_ref", ""),
                    json.dumps(n.get("output", {})),
                    json.dumps(n.get("analysis")) if n.get("analysis") else None,
                    n.get("danus_fingerprint"),
                    1 if n.get("is_stale") else 0,
                    1 if n.get("is_invalidated") else 0,
                    json.dumps(n.get("rollouts", [])) if n.get("rollouts") else None,
                    json.dumps(n.get("falsifier_report")) if n.get("falsifier_report") else None,
                    json.dumps(n.get("objections", [])),
                    n.get("retry_count", 0),
                    n.get("started_at"),
                    n.get("finished_at"),
                ))

            for e in trace.get("edges", []):
                cursor.execute("""
                INSERT INTO edges (run_id, source, target, edge_type)
                VALUES (?, ?, ?, ?)
                """, (run_id, e["source"], e["target"], e.get("edge_type", e.get("type", "aggregation"))))

            for ev in trace.get("events", []):
                cursor.execute("""
                INSERT INTO events (run_id, seq, timestamp, event_type, payload_json)
                VALUES (?, ?, ?, ?, ?)
                """, (
                    run_id,
                    ev.get("seq", 0),
                    ev.get("timestamp", ""),
                    ev.get("event_type", ""),
                    json.dumps(ev.get("payload", {})),
                ))

            for k in trace.get("knowledge_directory", []):
                cursor.execute("""
                INSERT INTO knowledge (run_id, entry_type, title, contents, source, caveats)
                VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    run_id,
                    k.get("entry_type", "theorems_and_lemmas"),
                    k.get("title", ""),
                    k.get("contents", ""),
                    k.get("source", ""),
                    k.get("caveats", ""),
                ))
            conn.commit()
        finally:
            conn.close()
        return run_id
