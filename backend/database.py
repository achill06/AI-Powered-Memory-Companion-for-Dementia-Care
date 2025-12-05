import sqlite3
import os
import logging 
from datetime import datetime, date

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DATABASE_PATH = os.path.join(os.path.dirname(__file__), 'memory_companion.db')

def get_db_connection():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_database():
    conn = get_db_connection()
    try:
        with open('schema.sql', 'r') as f:
            conn.executescript(f.read())
        
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM patients")
        if cursor.fetchone()[0] == 0:
            cursor.execute("INSERT INTO patients (name) VALUES (?)", ("John",))
            
            today = date.today().isoformat()
            default_tasks = [
                ("morning_medicine", "09:00", today),
                ("breakfast", "09:30", today),
                ("lunch", "13:00", today),
                ("evening_walk", "17:00", today),
                ("dinner", "19:00", today),
                ("night_medicine", "21:00", today)
            ]
            cursor.executemany(
                "INSERT INTO tasks (patient_id, task_name, scheduled_time, date) VALUES (1, ?, ?, ?)",
                default_tasks
            )
        conn.commit()
    except Exception as e:
        logger.error(f"Database init error: {e}")
    finally:
        conn.close()

def get_patient_id():
    conn = get_db_connection()
    try:
        patient = conn.execute("SELECT id FROM patients LIMIT 1").fetchone()
        return patient['id'] if patient else None
    finally:
        conn.close()

def create_task(patient_id, task_name, scheduled_time, task_date=None):
    conn = get_db_connection()
    try:
        if task_date is None:
            target_date = date.today().isoformat()
        else:
            target_date = task_date

        existing = conn.execute(
            "SELECT id FROM tasks WHERE patient_id = ? AND task_name = ? AND date = ?",
            (patient_id, task_name, target_date)
        ).fetchone()
        
        if not existing:
            conn.execute(
                "INSERT INTO tasks (patient_id, task_name, scheduled_time, date, completed) VALUES (?, ?, ?, ?, 0)",
                (patient_id, task_name, scheduled_time, target_date)
            )
            conn.commit()
            return True
        return False
    finally:
        conn.close()

def get_all_tasks(patient_id):
    conn = get_db_connection()
    try:
        today = date.today().isoformat()
        tasks = conn.execute(
            "SELECT * FROM tasks WHERE patient_id = ? AND date = ? ORDER BY scheduled_time",
            (patient_id, today)
        ).fetchall()
        return [dict(task) for task in tasks]
    finally:
        conn.close()

def mark_task_completed(patient_id, task_name):
    conn = get_db_connection()
    try:
        today = date.today().isoformat()
        conn.execute(
            "UPDATE tasks SET completed = 1, completed_at = ? WHERE patient_id = ? AND task_name = ? AND date = ?",
            (datetime.now().isoformat(), patient_id, task_name, today)
        )
        conn.commit()
    finally:
        conn.close()

def add_memory_note(patient_id, note_text, reminder_time=None):
    conn = get_db_connection()
    try:
        conn.execute(
            "INSERT INTO memory_notes (patient_id, note_text, reminder_time) VALUES (?, ?, ?)",
            (patient_id, note_text, reminder_time)
        )
        conn.commit()
    finally:
        conn.close()

def get_memory_notes(patient_id):
    conn = get_db_connection()
    try:
        notes = conn.execute(
            "SELECT * FROM memory_notes WHERE patient_id = ? ORDER BY created_at DESC LIMIT 10",
            (patient_id,)
        ).fetchall()
        return [dict(note) for note in notes]
    finally:
        conn.close()

def save_conversation(patient_id, user_message, agent_response):
    conn = get_db_connection()
    try:
        conn.execute(
            "INSERT INTO conversation_history (patient_id, user_message, agent_response) VALUES (?, ?, ?)",
            (patient_id, user_message, agent_response)
        )
        conn.commit()
    finally:
        conn.close()

def get_recent_conversations(patient_id, limit=5):
    conn = get_db_connection()
    try:
        conversations = conn.execute(
            "SELECT * FROM conversation_history WHERE patient_id = ? ORDER BY timestamp DESC LIMIT ?",
            (patient_id, limit)
        ).fetchall()
        return [dict(conv) for conv in reversed(conversations)]
    finally:
        conn.close()

def record_contact_call(patient_id, caller_name):
    conn = get_db_connection()
    try:
        conn.execute(
            "INSERT INTO contact_calls (patient_id, caller_name) VALUES (?, ?)",
            (patient_id, caller_name)
        )
        conn.commit()
    finally:
        conn.close()

def get_recent_caller(patient_id):
    conn = get_db_connection()
    try:
        call = conn.execute(
            "SELECT caller_name, call_time FROM contact_calls WHERE patient_id = ? ORDER BY call_time DESC LIMIT 1",
            (patient_id,)
        ).fetchone()
        return dict(call) if call else None
    finally:
        conn.close()

def update_task_status(task_id, is_completed):
    conn = get_db_connection()
    try:
        completed_int = 1 if is_completed else 0
        completed_at = datetime.now().isoformat() if is_completed else None
        
        conn.execute(
            "UPDATE tasks SET completed = ?, completed_at = ? WHERE id = ?",
            (completed_int, completed_at, task_id)
        )
        conn.commit()
    finally:
        conn.close()

def delete_all_memory_notes(patient_id):
    """
    Deletes all notes for a patient.
    Returns: Integer (number of notes deleted)
    """
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        with conn: # Automatically commits if successful, rolls back if error
            cursor.execute("DELETE FROM memory_notes WHERE patient_id = ?", (patient_id,))
            deleted_count = cursor.rowcount
            
        logger.info(f"Deleted {deleted_count} notes for patient {patient_id}")
        return deleted_count

    except sqlite3.Error as e:
        logger.error(f"Database error in delete_all_memory_notes: {e}")
        return 0
    finally:
        if conn:
            conn.close()

def delete_task(patient_id, task_name, task_date=None):
    """
    Deletes a specific task. 
    Returns: Boolean (True if found and deleted, False otherwise)
    """
    conn = None
    try:
        conn = get_db_connection()
        
        # Use provided date, or default to today
        if task_date is None:
            target_date = date.today().isoformat()
        else:
            target_date = task_date
            
        cursor = conn.cursor()
        
        with conn:
            cursor.execute(
                "DELETE FROM tasks WHERE patient_id = ? AND task_name = ? AND date = ?",
                (patient_id, task_name, target_date)
            )
            rows_affected = cursor.rowcount
            
        return rows_affected > 0

    except sqlite3.Error as e:
        logger.error(f"Database error in delete_task: {e}")
        return False
    finally:
        if conn:
            conn.close()

def delete_all_tasks(patient_id, task_date=None):
    """
    Clears all tasks for a specific date.
    Returns: Integer (number of tasks deleted)
    """
    conn = None
    try:
        conn = get_db_connection()
        
        if task_date is None:
            target_date = date.today().isoformat()
        else:
            target_date = task_date

        cursor = conn.cursor()
        
        with conn:
            cursor.execute(
                "DELETE FROM tasks WHERE patient_id = ? AND date = ?",
                (patient_id, target_date)
            )
            deleted_count = cursor.rowcount
            
        return deleted_count

    except sqlite3.Error as e:
        logger.error(f"Database error in delete_all_tasks: {e}")
        return 0
    finally:
        if conn:
            conn.close()