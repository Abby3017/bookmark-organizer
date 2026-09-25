import sqlite3
from bookmark_agent.config import load_settings

config = load_settings()
DB_PATH = config.get("db_path", "")

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Create table for batch jobs
    cursor.execute('''
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

    conn.commit()
    conn.close()


def create_batch_job_entry(job_details: dict):
    # This function can be implemented to insert a new batch job entry into the database
    with sqlite3.connect(DB_PATH) as conn:
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
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute('''
            select * from batch_jobs where status = ?
                            order by created_at desc limit 1
                     ''', (status,)).fetchone()
        return row


def get_all_batches_with_status(status: str = 'pending'):
    """Return all batch jobs matching the given status, oldest first."""
    with sqlite3.connect(DB_PATH) as conn:
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
    with sqlite3.connect(DB_PATH) as conn:
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
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(f'DELETE FROM {table_name}')
        conn.commit()

if __name__ == "__main__":
    init_db()
