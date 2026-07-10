"""
运行历史 SQLite 持久化

表结构:
- runs: 每次运行的元信息 + 节点状态
- run_logs: 每次运行的日志条目
"""
import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Optional

_DB_PATH = Path(__file__).parent.parent.parent / "data" / "runs.db"
_lock = threading.Lock()


def _get_conn() -> sqlite3.Connection:
    """获取 SQLite 连接（线程安全）"""
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """初始化数据库表"""
    conn = _get_conn()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS runs (
                run_id       TEXT PRIMARY KEY,
                workflow_id  TEXT NOT NULL,
                status       TEXT NOT NULL DEFAULT 'pending',
                date         TEXT DEFAULT '',
                start_time   REAL DEFAULT 0,
                end_time     REAL DEFAULT 0,
                current_nodes TEXT DEFAULT '[]',
                node_states  TEXT DEFAULT '{}',
                created_at   REAL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_runs_workflow ON runs(workflow_id);
            CREATE INDEX IF NOT EXISTS idx_runs_start ON runs(start_time);

            CREATE TABLE IF NOT EXISTS run_logs (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id       TEXT NOT NULL,
                seq          INTEGER DEFAULT 0,
                node_id      TEXT DEFAULT '',
                level        TEXT DEFAULT 'INFO',
                message      TEXT DEFAULT '',
                logger       TEXT DEFAULT '',
                timestamp    REAL DEFAULT 0,
                log_type     TEXT DEFAULT 'log'
            );
            CREATE INDEX IF NOT EXISTS idx_logs_run ON run_logs(run_id, seq);
        """)
        conn.commit()
    finally:
        conn.close()


def save_run(run_id: str, workflow_id: str, status: str, date: str,
             start_time: float, end_time: float, current_nodes: list,
             node_states: dict):
    """保存/更新一条运行记录"""
    with _lock:
        conn = _get_conn()
        try:
            conn.execute("""
                INSERT INTO runs (run_id, workflow_id, status, date, start_time, end_time, current_nodes, node_states, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    status = excluded.status,
                    end_time = excluded.end_time,
                    current_nodes = excluded.current_nodes,
                    node_states = excluded.node_states
            """, (
                run_id, workflow_id, status, date,
                start_time, end_time,
                json.dumps(current_nodes, ensure_ascii=False),
                json.dumps(node_states, ensure_ascii=False),
                time.time()
            ))
            conn.commit()
        finally:
            conn.close()


def append_log(run_id: str, seq: int, log_entry: dict):
    """追加一条日志"""
    with _lock:
        conn = _get_conn()
        try:
            log_type = 'node_progress' if log_entry.get('type') == 'node_progress' else 'log'
            conn.execute("""
                INSERT INTO run_logs (run_id, seq, node_id, level, message, logger, timestamp, log_type)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                run_id, seq,
                log_entry.get('node_id', ''),
                log_entry.get('level', 'INFO'),
                log_entry.get('message', ''),
                log_entry.get('logger', ''),
                log_entry.get('timestamp', 0),
                log_type,
            ))
            conn.commit()
        finally:
            conn.close()


def get_run_history(workflow_id: str, limit: int = 50) -> list[dict]:
    """获取某个工作流的运行历史"""
    conn = _get_conn()
    try:
        rows = conn.execute("""
            SELECT * FROM runs WHERE workflow_id = ? ORDER BY start_time DESC LIMIT ?
        """, (workflow_id, limit)).fetchall()
        result = []
        for row in rows:
            result.append({
                "run_id": row["run_id"],
                "workflow_id": row["workflow_id"],
                "status": row["status"],
                "date": row["date"],
                "start_time": row["start_time"],
                "end_time": row["end_time"],
                "current_nodes": json.loads(row["current_nodes"] or "[]"),
                "node_states": json.loads(row["node_states"] or "{}"),
            })
        return result
    finally:
        conn.close()


def get_run_detail(run_id: str) -> Optional[dict]:
    """获取某次运行的详细状态 + 日志"""
    conn = _get_conn()
    try:
        row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        if not row:
            return None
        # 获取日志
        log_rows = conn.execute("""
            SELECT * FROM run_logs WHERE run_id = ? ORDER BY seq ASC
        """, (run_id,)).fetchall()
        logs = []
        for lr in log_rows:
            if lr["log_type"] == "node_progress":
                logs.append({
                    "type": "node_progress",
                    "node_id": lr["node_id"],
                    "progress": 0,
                    "message": lr["message"],
                })
            else:
                logs.append({
                    "node_id": lr["node_id"],
                    "level": lr["level"],
                    "message": lr["message"],
                    "logger": lr["logger"],
                    "timestamp": lr["timestamp"],
                })
        return {
            "run_id": row["run_id"],
            "workflow_id": row["workflow_id"],
            "status": row["status"],
            "date": row["date"],
            "start_time": row["start_time"],
            "end_time": row["end_time"],
            "current_nodes": json.loads(row["current_nodes"] or "[]"),
            "node_states": json.loads(row["node_states"] or "{}"),
            "logs": logs,
        }
    finally:
        conn.close()


def update_run_status(run_id: str, status: str, end_time: float = 0, node_states: dict = None, current_nodes: list = None):
    """更新运行状态（运行中用）"""
    with _lock:
        conn = _get_conn()
        try:
            if node_states is not None and current_nodes is not None:
                conn.execute("""
                    UPDATE runs SET status = ?, end_time = ?, node_states = ?, current_nodes = ? WHERE run_id = ?
                """, (status, end_time, json.dumps(node_states, ensure_ascii=False),
                      json.dumps(current_nodes, ensure_ascii=False), run_id))
            elif node_states is not None:
                conn.execute("""
                    UPDATE runs SET status = ?, node_states = ? WHERE run_id = ?
                """, (status, json.dumps(node_states, ensure_ascii=False), run_id))
            else:
                conn.execute("UPDATE runs SET status = ?, end_time = ? WHERE run_id = ?",
                             (status, end_time, run_id))
            conn.commit()
        finally:
            conn.close()
