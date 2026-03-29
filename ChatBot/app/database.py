import mysql.connector
from app.config import DB_CONFIG

def connect_db():
    return mysql.connector.connect(
        host="127.0.0.1",   # FIX ERROR PIPE
        user="root",
        password="",
        database="anonymous_chat",
        port=3306
    )

# ================= USER =================
def register_user(user_id):
    db = connect_db()
    cursor = db.cursor()
    cursor.execute("""
        INSERT IGNORE INTO users (user_id) VALUES (%s)
    """, (user_id,))
    db.commit()
    cursor.close()
    db.close()

def set_searching(user_id, status):
    db = connect_db()
    cursor = db.cursor()
    cursor.execute("""
        UPDATE users SET searching=%s WHERE user_id=%s
    """, (status, user_id))
    db.commit()
    cursor.close()
    db.close()

def find_partner(user_id):
    db = connect_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute("""
        SELECT * FROM users 
        WHERE searching=1 AND user_id!=%s AND partner_id IS NULL 
        LIMIT 1
    """, (user_id,))
    partner = cursor.fetchone()

    if partner:
        cursor.execute("""
            UPDATE users SET partner_id=%s, searching=0 WHERE user_id=%s
        """, (partner["user_id"], user_id))
        cursor.execute("""
            UPDATE users SET partner_id=%s, searching=0 WHERE user_id=%s
        """, (user_id, partner["user_id"]))
        db.commit()

    cursor.close()
    db.close()
    return partner

def stop_chat(user_id):
    db = connect_db()
    cursor = db.cursor()
    cursor.execute("""
        SELECT partner_id FROM users WHERE user_id=%s
    """, (user_id,))
    result = cursor.fetchone()
    partner_id = result[0] if result else None

    cursor.execute("""
        UPDATE users SET partner_id=NULL, searching=0 WHERE user_id=%s
    """, (user_id,))
    if partner_id:
        cursor.execute("""
            UPDATE users SET partner_id=NULL, searching=0 WHERE user_id=%s
        """, (partner_id,))
    db.commit()
    cursor.close()
    db.close()
    return partner_id

def get_partner(user_id):
    db = connect_db()
    cursor = db.cursor()
    cursor.execute("""
        SELECT partner_id FROM users WHERE user_id=%s
    """, (user_id,))
    result = cursor.fetchone()
    cursor.close()
    db.close()
    return result[0] if result else None

# ================= FEEDBACK =================
def save_feedback(from_user, to_user, feedback):
    db = connect_db()
    cursor = db.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS feedback (
            id INT AUTO_INCREMENT PRIMARY KEY,
            from_user BIGINT,
            to_user BIGINT,
            feedback VARCHAR(20)
        )
    """)
    cursor.execute("""
        INSERT INTO feedback (from_user, to_user, feedback)
        VALUES (%s, %s, %s)
    """, (from_user, to_user, feedback))
    db.commit()
    cursor.close()
    db.close()