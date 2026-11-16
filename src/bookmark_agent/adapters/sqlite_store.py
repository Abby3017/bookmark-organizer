import sqlite3
from pathlib import Path

from bookmark_agent.config import load_settings

DEFAULT_DB_FOLDER = "data"
DB_FILENAME = "bookmarks.db"


def _db_path() -> str:
    """Resolve the db file path lazily: config's db_path, else the default."""
    path = load_settings().get("db_path") or f"{DEFAULT_DB_FOLDER}/{DB_FILENAME}"
    # tolerate a folder being configured where a file belongs
    if path.endswith("/") or Path(path).is_dir():
        path = f"{path.rstrip('/')}/{DB_FILENAME}"
    return path


def init_db(folder: str = DEFAULT_DB_FOLDER) -> str:
    """Create the batch-jobs database in `folder` and return its file path."""
    db_file = Path(folder) / DB_FILENAME
    if db_file.exists():
        raise FileExistsError(
            f"db already exists at {db_file}; refusing to re-initialize"
        )
    db_file.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_file) as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS batch_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT UNIQUE,
                file_path_read TEXT,
                file_path_write TEXT,
                file_object_details TEXT,
                batch_object_details TEXT,
                status TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
    return str(db_file)


def create_batch_job_entry(job_details: dict):
    # This function can be implemented to insert a new batch job entry into the database
    with sqlite3.connect(_db_path()) as conn:
        conn.execute('''
            INSERT OR REPLACE INTO batch_jobs (job_id, file_path_read,
                    file_object_details, batch_object_details, status )
            VALUES (?, ?, ?, ?, ?)
            ''', (
            job_details.get('job_id'),
            job_details.get('file_path_read'),
            job_details.get('file_object_details'),
            job_details.get('batch_object_details'),
            job_details.get('status')
        ))


def get_batch_with_given_status(status: str = 'pending'):
    with sqlite3.connect(_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute('''
            select * from batch_jobs where status = ?
                            order by created_at desc limit 1
                     ''', (status,)).fetchone()
        return row


def get_all_batches_with_status(status: str = 'pending'):
    """Return all batch jobs matching the given status, oldest first."""
    with sqlite3.connect(_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            '''
            SELECT * FROM batch_jobs
            WHERE status = ?
            ORDER BY created_at ASC
            ''', (status,)
        ).fetchall()
        return rows


def update_batch_job_status(job_id: str, status: str, file_path_write: str | None = None):
    """Update the status (and optionally the output file path) of a batch job."""
    with sqlite3.connect(_db_path()) as conn:
        if file_path_write:
            conn.execute('''
                UPDATE batch_jobs
                SET status = ?, file_path_write = ?, updated_at = CURRENT_TIMESTAMP
                WHERE job_id = ?
            ''', (status, file_path_write, job_id))
        else:
            conn.execute('''
                UPDATE batch_jobs
                SET status = ?, updated_at = CURRENT_TIMESTAMP
                WHERE job_id = ?
            ''', (status, job_id))


def clear_all_given_table(table_name: str):
    with sqlite3.connect(_db_path()) as conn:
        conn.execute(f'DELETE FROM {table_name}')
        conn.commit()

if __name__ == "__main__":
    init_db()
