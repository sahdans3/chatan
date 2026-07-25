import os
import psycopg2
import psycopg2.pool
import threading
import time
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ================= CEK DATABASE_URL =================

DATABASE_URL = os.getenv('DATABASE_URL')

if not DATABASE_URL:
    logger.error("❌ DATABASE_URL tidak ditemukan!")
    logger.info("📋 Pastikan sudah menambahkan PostgreSQL di Railway:")
    logger.info("   railway add → Database → PostgreSQL")
else:
    logger.info("✅ DATABASE_URL ditemukan")

# ================= CONNECTION POOL =================

db_pool = None

def get_db_pool():
    global db_pool
    if db_pool is None and DATABASE_URL:
        try:
            db_pool = psycopg2.pool.SimpleConnectionPool(
                minconn=1,
                maxconn=5,
                dsn=DATABASE_URL
            )
            logger.info("✅ Database connection pool created")
        except Exception as e:
            logger.error(f"❌ Failed to create pool: {e}")
            db_pool = None
    return db_pool

def connect_db():
    if not DATABASE_URL:
        return None
    try:
        pool = get_db_pool()
        if pool:
            return pool.getconn()
        else:
            return psycopg2.connect(DATABASE_URL)
    except Exception as e:
        logger.error(f"⚠️ Database connection error: {e}")
        return None

# ================= CREATE TABLES =================

def init_db():
    if not DATABASE_URL:
        logger.warning("⚠️ Skipping database init (no DATABASE_URL)")
        return
    
    db = connect_db()
    if not db:
        logger.error("❌ Cannot initialize database")
        return
    
    cursor = db.cursor()
    
    # Drop existing tables (clean slate)
    cursor.execute("DROP TABLE IF EXISTS waiting_queue CASCADE")
    cursor.execute("DROP TABLE IF EXISTS feedback CASCADE")
    cursor.execute("DROP TABLE IF EXISTS users CASCADE")
    
    # Users table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            searching INT DEFAULT 0,
            partner_id BIGINT DEFAULT NULL
        )
    """)
    
    # Feedback table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS feedback (
            id SERIAL PRIMARY KEY,
            from_user BIGINT NOT NULL,
            to_user BIGINT NOT NULL,
            feedback VARCHAR(50) NOT NULL
        )
    """)
    
    # Waiting queue table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS waiting_queue (
            id SERIAL PRIMARY KEY,
            user_id BIGINT UNIQUE NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    db.commit()
    cursor.close()
    db.close()
    logger.info("✅ Database tables created")

# ================= KEEP ALIVE =================

def keep_alive():
    while True:
        try:
            if DATABASE_URL:
                db = connect_db()
                if db:
                    cursor = db.cursor()
                    cursor.execute("SELECT 1")
                    cursor.fetchall()
                    cursor.close()
                    db.close()
                    logger.info("✅ Database ping successful")
        except Exception as e:
            logger.error(f"❌ Database ping failed: {e}")
        time.sleep(300)

def start_keep_alive():
    if not DATABASE_URL:
        logger.warning("⚠️ Database keep-alive disabled (no DATABASE_URL)")
        return
    try:
        thread = threading.Thread(target=keep_alive, daemon=True)
        thread.start()
        logger.info("🔄 Database keep-alive started")
    except Exception as e:
        logger.error(f"⚠️ Failed to start keep-alive: {e}")

# ================= USER FUNCTIONS =================

def register_user(user_id):
    if not DATABASE_URL:
        return
    db = connect_db()
    if not db:
        return
    cursor = db.cursor()
    cursor.execute("INSERT INTO users(user_id) VALUES(%s) ON CONFLICT (user_id) DO NOTHING", (user_id,))
    db.commit()
    cursor.close()
    db.close()

def clear_user_status(user_id):
    if not DATABASE_URL:
        return
    db = connect_db()
    if not db:
        return
    cursor = db.cursor()
    try:
        cursor.execute("UPDATE users SET searching=0, partner_id=NULL WHERE user_id=%s", (user_id,))
        cursor.execute("DELETE FROM waiting_queue WHERE user_id=%s", (user_id,))
        db.commit()
        logger.info(f"✅ Status user {user_id} cleared")
    except Exception as e:
        logger.error(f"❌ Clear status error: {e}")
        db.rollback()
    finally:
        cursor.close()
        db.close()

def set_searching(user_id, status):
    if not DATABASE_URL:
        return
    db = connect_db()
    if not db:
        return
    cursor = db.cursor()
    cursor.execute("UPDATE users SET searching=%s WHERE user_id=%s", (status, user_id))
    db.commit()
    cursor.close()
    db.close()

def is_searching(user_id):
    if not DATABASE_URL:
        return False
    db = connect_db()
    if not db:
        return False
    cursor = db.cursor()
    cursor.execute("SELECT searching FROM users WHERE user_id=%s", (user_id,))
    result = cursor.fetchone()
    cursor.close()
    db.close()
    return result and result[0] == 1

def join_queue(user_id):
    if not DATABASE_URL:
        return
    db = connect_db()
    if not db:
        return
    cursor = db.cursor()
    try:
        # Cek apakah user sudah di queue
        cursor.execute("SELECT user_id FROM waiting_queue WHERE user_id=%s", (user_id,))
        if cursor.fetchone():
            cursor.close()
            db.close()
            return
        
        # Cek apakah user sedang dalam chat
        cursor.execute("SELECT partner_id FROM users WHERE user_id=%s", (user_id,))
        result = cursor.fetchone()
        if result and result[0] is not None:
            cursor.close()
            db.close()
            return
        
        cursor.execute("INSERT INTO waiting_queue(user_id) VALUES(%s) ON CONFLICT (user_id) DO NOTHING", (user_id,))
        db.commit()
        logger.info(f"✅ User {user_id} joined queue")
    except Exception as e:
        logger.error(f"❌ Join queue error: {e}")
        db.rollback()
    finally:
        cursor.close()
        db.close()

def leave_queue(user_id):
    if not DATABASE_URL:
        return
    db = connect_db()
    if not db:
        return
    cursor = db.cursor()
    cursor.execute("DELETE FROM waiting_queue WHERE user_id=%s", (user_id,))
    db.commit()
    cursor.close()
    db.close()

def find_partner(user_id):
    """Find partner with FOR UPDATE locking to prevent race conditions"""
    if not DATABASE_URL:
        logger.warning(f"⚠️ No DATABASE_URL for user {user_id}")
        return None
    
    db = connect_db()
    if not db:
        logger.error(f"❌ Cannot connect to database for user {user_id}")
        return None
    
    cursor = db.cursor()
    
    try:
        cursor.execute("BEGIN")
        
        # Cek apakah user sedang dalam chat
        cursor.execute("SELECT partner_id, searching FROM users WHERE user_id=%s FOR UPDATE", (user_id,))
        user_check = cursor.fetchone()
        logger.info(f"🔍 User {user_id} check: partner_id={user_check[0] if user_check else None}, searching={user_check[1] if user_check else None}")
        
        if user_check and user_check[0] is not None:
            logger.info(f"ℹ️ User {user_id} sudah dalam chat")
            cursor.execute("COMMIT")
            return None
        
        # Cari partner di queue
        cursor.execute("""
            SELECT wq.user_id, u.searching
            FROM waiting_queue wq
            JOIN users u ON u.user_id = wq.user_id
            WHERE wq.user_id <> %s
                AND (u.partner_id IS NULL OR u.partner_id = 0)
                AND u.searching = 1
            ORDER BY wq.created_at ASC
            LIMIT 1
            FOR UPDATE
        """, (user_id,))
        
        partner = cursor.fetchone()
        
        if not partner:
            logger.info(f"ℹ️ Tidak ada partner di queue untuk user {user_id}")
            cursor.execute("COMMIT")
            return None
        
        partner_id = partner[0]
        logger.info(f"🔍 Found potential partner: {partner_id}")
        
        # Lock partner row
        cursor.execute("SELECT partner_id, searching FROM users WHERE user_id=%s FOR UPDATE", (partner_id,))
        partner_check = cursor.fetchone()
        
        if partner_check and partner_check[0] is not None:
            logger.info(f"ℹ️ Partner {partner_id} sudah dalam chat, membersihkan queue...")
            leave_queue(partner_id)
            cursor.execute("COMMIT")
            return None
        
        # Update kedua user
        cursor.execute("UPDATE users SET partner_id=%s, searching=0 WHERE user_id=%s", (partner_id, user_id))
        cursor.execute("UPDATE users SET partner_id=%s, searching=0 WHERE user_id=%s", (user_id, partner_id))
        
        # Hapus dari queue
        cursor.execute("DELETE FROM waiting_queue WHERE user_id IN (%s, %s)", (user_id, partner_id))
        
        cursor.execute("COMMIT")
        logger.info(f"✅ Partner found: {user_id} <-> {partner_id}")
        return partner_id
        
    except Exception as e:
        logger.error(f"❌ Find partner error for user {user_id}: {e}")
        try:
            cursor.execute("ROLLBACK")
        except:
            pass
        return None
    finally:
        cursor.close()
        db.close()

def stop_chat(user_id):
    """Stop chat with locking to prevent race conditions"""
    if not DATABASE_URL:
        return None
    db = connect_db()
    if not db:
        return None
    cursor = db.cursor()
    try:
        cursor.execute("BEGIN")
        
        # Lock user row
        cursor.execute("SELECT partner_id FROM users WHERE user_id=%s FOR UPDATE", (user_id,))
        result = cursor.fetchone()
        partner_id = result[0] if result else None
        
        # Update user
        cursor.execute("UPDATE users SET partner_id=NULL, searching=0 WHERE user_id=%s", (user_id,))
        
        # Update partner jika ada
        if partner_id:
            cursor.execute("SELECT partner_id FROM users WHERE user_id=%s FOR UPDATE", (partner_id,))
            cursor.execute("UPDATE users SET partner_id=NULL, searching=0 WHERE user_id=%s", (partner_id,))
        
        # Hapus dari queue
        leave_queue(user_id)
        if partner_id:
            leave_queue(partner_id)
        
        cursor.execute("COMMIT")
        logger.info(f"✅ Chat stopped: {user_id} with {partner_id}")
        return partner_id
        
    except Exception as e:
        logger.error(f"❌ Stop chat error: {e}")
        try:
            cursor.execute("ROLLBACK")
        except:
            pass
        return None
    finally:
        cursor.close()
        db.close()

def get_partner(user_id):
    if not DATABASE_URL:
        return None
    db = connect_db()
    if not db:
        return None
    cursor = db.cursor()
    try:
        cursor.execute("SELECT partner_id FROM users WHERE user_id=%s AND partner_id IS NOT NULL", (user_id,))
        result = cursor.fetchone()
        if result and result[0]:
            partner_id = result[0]
            cursor.execute("SELECT user_id FROM users WHERE user_id=%s AND partner_id=%s", (partner_id, user_id))
            if cursor.fetchone():
                return partner_id
            else:
                cursor.execute("UPDATE users SET partner_id=NULL, searching=0 WHERE user_id=%s", (user_id,))
                db.commit()
                return None
        return None
    except Exception as e:
        logger.error(f"❌ Get partner error: {e}")
        return None
    finally:
        cursor.close()
        db.close()

def remove_user(user_id):
    if not DATABASE_URL:
        return
    db = connect_db()
    if not db:
        return
    cursor = db.cursor()
    try:
        cursor.execute("DELETE FROM users WHERE user_id=%s", (user_id,))
        cursor.execute("DELETE FROM waiting_queue WHERE user_id=%s", (user_id,))
        db.commit()
        logger.info(f"✅ User {user_id} removed from database")
    except Exception as e:
        logger.error(f"❌ Remove user error: {e}")
        db.rollback()
    finally:
        cursor.close()
        db.close()

def get_user_status(user_id):
    if not DATABASE_URL:
        return None
    db = connect_db()
    if not db:
        return None
    cursor = db.cursor()
    cursor.execute("SELECT * FROM users WHERE user_id=%s", (user_id,))
    result = cursor.fetchone()
    cursor.close()
    db.close()
    return result

def save_feedback(from_user, to_user, feedback):
    if not DATABASE_URL:
        return
    db = connect_db()
    if not db:
        return
    cursor = db.cursor()
    cursor.execute("INSERT INTO feedback(from_user, to_user, feedback) VALUES(%s, %s, %s)", (from_user, to_user, feedback))
    db.commit()
    cursor.close()
    db.close()