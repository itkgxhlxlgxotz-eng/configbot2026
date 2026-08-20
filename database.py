# -*- coding: utf-8 -*-
"""
لایه دیتابیس (SQLite) - تمام اطلاعات به صورت دائمی ذخیره می‌شود و با ری‌استارت
شدن ربات از بین نمی‌رود (امتیازها، موجودی، خریدها و ...).
"""
import sqlite3
import threading
import random
import string
import datetime
from contextlib import contextmanager

import config

_lock = threading.Lock()


def _connect():
    conn = sqlite3.connect(config.DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def get_cursor(commit=False):
    with _lock:
        conn = _connect()
        try:
            cur = conn.cursor()
            yield cur
            if commit:
                conn.commit()
        finally:
            conn.close()


def now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def init_db():
    with get_cursor(commit=True) as c:
        c.execute("""CREATE TABLE IF NOT EXISTS users(
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            points INTEGER NOT NULL DEFAULT 0,
            balance INTEGER NOT NULL DEFAULT 0,
            is_banned INTEGER NOT NULL DEFAULT 0,
            referrer_id INTEGER,
            joined_at TEXT
        )""")

        c.execute("""CREATE TABLE IF NOT EXISTS admins(
            user_id INTEGER PRIMARY KEY
        )""")

        c.execute("""CREATE TABLE IF NOT EXISTS force_channels(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel TEXT UNIQUE
        )""")

        c.execute("""CREATE TABLE IF NOT EXISTS config_packages(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            volume TEXT,
            duration TEXT,
            price INTEGER,
            active INTEGER NOT NULL DEFAULT 1
        )""")

        c.execute("""CREATE TABLE IF NOT EXISTS point_packages(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            volume TEXT,
            duration TEXT,
            points_price INTEGER,
            active INTEGER NOT NULL DEFAULT 1
        )""")

        c.execute("""CREATE TABLE IF NOT EXISTS purchases(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            package_type TEXT,      -- 'config' یا 'point'
            package_title TEXT,
            price_text TEXT,
            status TEXT NOT NULL DEFAULT 'pending',  -- pending/approved/rejected
            receipt_file_id TEXT,
            admin_msg_id INTEGER,
            created_at TEXT
        )""")

        c.execute("""CREATE TABLE IF NOT EXISTS charge_requests(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount INTEGER,
            receipt_file_id TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            admin_msg_id INTEGER,
            created_at TEXT
        )""")

        c.execute("""CREATE TABLE IF NOT EXISTS gift_codes(
            code TEXT PRIMARY KEY,
            points INTEGER,
            max_uses INTEGER,
            used_count INTEGER NOT NULL DEFAULT 0,
            created_at TEXT
        )""")

        c.execute("""CREATE TABLE IF NOT EXISTS gift_code_uses(
            code TEXT,
            user_id INTEGER,
            PRIMARY KEY(code, user_id)
        )""")

        c.execute("""CREATE TABLE IF NOT EXISTS settings(
            key TEXT PRIMARY KEY,
            value TEXT
        )""")

        c.execute("""CREATE TABLE IF NOT EXISTS custom_buttons(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT,
            response_text TEXT,
            enabled INTEGER NOT NULL DEFAULT 1
        )""")

        c.execute("""CREATE TABLE IF NOT EXISTS button_visibility(
            button_key TEXT PRIMARY KEY,
            enabled INTEGER NOT NULL DEFAULT 1
        )""")

        c.execute("""CREATE TABLE IF NOT EXISTS support_map(
            admin_msg_id INTEGER PRIMARY KEY,
            user_id INTEGER
        )""")

        # مقادیر پیش‌فرض تنظیمات
        defaults = {
            "card_number": config.DEFAULT_CARD_NUMBER,
            "sales_channel": config.DEFAULT_SALES_CHANNEL,
            "button_style": config.DEFAULT_BUTTON_STYLE,
            "welcome_text": config.WELCOME_TEXT,
        }
        for k, v in defaults.items():
            c.execute("INSERT OR IGNORE INTO settings(key, value) VALUES(?,?)", (k, v))

        for ch in config.DEFAULT_FORCE_CHANNELS:
            c.execute("INSERT OR IGNORE INTO force_channels(channel) VALUES(?)", (ch,))

        c.execute("INSERT OR IGNORE INTO admins(user_id) VALUES(?)", (config.OWNER_ID,))

        # پکیج‌های پیش‌فرض کانفینگ (حجم، مدت، قیمت تومان)
        c.execute("SELECT COUNT(*) AS n FROM config_packages")
        if c.fetchone()["n"] == 0:
            default_cfg = [
                ("10 گیگ", "1 ماه", 30000),
                ("15 گیگ", "1 ماه", 55000),
                ("20 گیگ", "1 ماه", 60000),
                ("30 گیگ", "1 ماه", 90000),
                ("40 گیگ", "2 ماه", 125000),
                ("50 گیگ", "2 ماه", 155000),
                ("100 گیگ", "3 ماه", 450000),
                ("نامحدود", "1 ماه", 200000),
            ]
            c.executemany(
                "INSERT INTO config_packages(volume,duration,price) VALUES(?,?,?)",
                default_cfg,
            )

        c.execute("SELECT COUNT(*) AS n FROM point_packages")
        if c.fetchone()["n"] == 0:
            default_pt = [
                ("1 گیگ", "2 روز", 20),
                ("4 گیگ", "6 روز", 30),
                ("8 گیگ", "20 روز", 50),
                ("8 گیگ", "25 روز", 60),
                ("9 گیگ", "25 روز", 70),
                ("10 گیگ", "25 روز", 80),
                ("13 گیگ", "30 روز", 100),
            ]
            c.executemany(
                "INSERT INTO point_packages(volume,duration,points_price) VALUES(?,?,?)",
                default_pt,
            )


# ---------------------------------------------------------------- settings
def get_setting(key, default=None):
    with get_cursor() as c:
        c.execute("SELECT value FROM settings WHERE key=?", (key,))
        row = c.fetchone()
        return row["value"] if row else default


def set_setting(key, value):
    with get_cursor(commit=True) as c:
        c.execute(
            "INSERT INTO settings(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )


# ---------------------------------------------------------------- users
def upsert_user(user_id, username, first_name, referrer_id=None):
    with get_cursor(commit=True) as c:
        c.execute("SELECT user_id FROM users WHERE user_id=?", (user_id,))
        exists = c.fetchone()
        if exists:
            c.execute(
                "UPDATE users SET username=?, first_name=? WHERE user_id=?",
                (username, first_name, user_id),
            )
            return False
        else:
            c.execute(
                "INSERT INTO users(user_id, username, first_name, referrer_id, joined_at) "
                "VALUES(?,?,?,?,?)",
                (user_id, username, first_name, referrer_id, now()),
            )
            return True


def get_user(user_id):
    with get_cursor() as c:
        c.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
        return c.fetchone()


def all_user_ids():
    with get_cursor() as c:
        c.execute("SELECT user_id FROM users")
        return [r["user_id"] for r in c.fetchall()]


def users_count():
    with get_cursor() as c:
        c.execute("SELECT COUNT(*) AS n FROM users")
        return c.fetchone()["n"]


def set_ban(user_id, banned: bool):
    with get_cursor(commit=True) as c:
        c.execute("UPDATE users SET is_banned=? WHERE user_id=?", (1 if banned else 0, user_id))


def is_banned(user_id):
    u = get_user(user_id)
    return bool(u and u["is_banned"])


def add_points(user_id, amount):
    with get_cursor(commit=True) as c:
        c.execute("UPDATE users SET points = points + ? WHERE user_id=?", (amount, user_id))


def deduct_points(user_id, amount):
    with get_cursor(commit=True) as c:
        c.execute("UPDATE users SET points = points - ? WHERE user_id=? AND points >= ?",
                   (amount, user_id, amount))
        return c.rowcount > 0


def add_balance(user_id, amount):
    with get_cursor(commit=True) as c:
        c.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (amount, user_id))


def referrals_count(user_id):
    with get_cursor() as c:
        c.execute("SELECT COUNT(*) AS n FROM users WHERE referrer_id=?", (user_id,))
        return c.fetchone()["n"]


# ---------------------------------------------------------------- admins
def is_admin(user_id):
    if user_id == config.OWNER_ID:
        return True
    with get_cursor() as c:
        c.execute("SELECT 1 FROM admins WHERE user_id=?", (user_id,))
        return c.fetchone() is not None


def add_admin(user_id):
    with get_cursor(commit=True) as c:
        c.execute("INSERT OR IGNORE INTO admins(user_id) VALUES(?)", (user_id,))


def list_admins():
    with get_cursor() as c:
        c.execute("SELECT user_id FROM admins")
        return [r["user_id"] for r in c.fetchall()]


# ---------------------------------------------------------------- channels
def list_force_channels():
    with get_cursor() as c:
        c.execute("SELECT channel FROM force_channels")
        return [r["channel"] for r in c.fetchall()]


def add_force_channel(channel):
    with get_cursor(commit=True) as c:
        c.execute("INSERT OR IGNORE INTO force_channels(channel) VALUES(?)", (channel,))


def remove_force_channel(channel):
    with get_cursor(commit=True) as c:
        c.execute("DELETE FROM force_channels WHERE channel=?", (channel,))


# ---------------------------------------------------------------- packages
def list_config_packages(active_only=True):
    with get_cursor() as c:
        if active_only:
            c.execute("SELECT * FROM config_packages WHERE active=1 ORDER BY id")
        else:
            c.execute("SELECT * FROM config_packages ORDER BY id")
        return c.fetchall()


def get_config_package(pkg_id):
    with get_cursor() as c:
        c.execute("SELECT * FROM config_packages WHERE id=?", (pkg_id,))
        return c.fetchone()


def add_config_package(volume, duration, price):
    with get_cursor(commit=True) as c:
        c.execute("INSERT INTO config_packages(volume,duration,price) VALUES(?,?,?)",
                   (volume, duration, price))


def delete_config_package(pkg_id):
    with get_cursor(commit=True) as c:
        c.execute("DELETE FROM config_packages WHERE id=?", (pkg_id,))


def toggle_config_package(pkg_id):
    with get_cursor(commit=True) as c:
        c.execute("UPDATE config_packages SET active = 1-active WHERE id=?", (pkg_id,))


def list_point_packages(active_only=True):
    with get_cursor() as c:
        if active_only:
            c.execute("SELECT * FROM point_packages WHERE active=1 ORDER BY id")
        else:
            c.execute("SELECT * FROM point_packages ORDER BY id")
        return c.fetchall()


def get_point_package(pkg_id):
    with get_cursor() as c:
        c.execute("SELECT * FROM point_packages WHERE id=?", (pkg_id,))
        return c.fetchone()


def add_point_package(volume, duration, points_price):
    with get_cursor(commit=True) as c:
        c.execute("INSERT INTO point_packages(volume,duration,points_price) VALUES(?,?,?)",
                   (volume, duration, points_price))


def delete_point_package(pkg_id):
    with get_cursor(commit=True) as c:
        c.execute("DELETE FROM point_packages WHERE id=?", (pkg_id,))


def toggle_point_package(pkg_id):
    with get_cursor(commit=True) as c:
        c.execute("UPDATE point_packages SET active = 1-active WHERE id=?", (pkg_id,))


# ---------------------------------------------------------------- purchases
def create_purchase(user_id, package_type, package_title, price_text, receipt_file_id):
    with get_cursor(commit=True) as c:
        c.execute(
            "INSERT INTO purchases(user_id,package_type,package_title,price_text,"
            "receipt_file_id,created_at) VALUES(?,?,?,?,?,?)",
            (user_id, package_type, package_title, price_text, receipt_file_id, now()),
        )
        return c.lastrowid


def set_purchase_admin_msg(purchase_id, admin_msg_id):
    with get_cursor(commit=True) as c:
        c.execute("UPDATE purchases SET admin_msg_id=? WHERE id=?", (admin_msg_id, purchase_id))


def get_purchase(purchase_id):
    with get_cursor() as c:
        c.execute("SELECT * FROM purchases WHERE id=?", (purchase_id,))
        return c.fetchone()


def set_purchase_status(purchase_id, status):
    with get_cursor(commit=True) as c:
        c.execute("UPDATE purchases SET status=? WHERE id=?", (status, purchase_id))


def approved_purchases_for_user(user_id):
    with get_cursor() as c:
        c.execute(
            "SELECT * FROM purchases WHERE user_id=? AND status='approved' ORDER BY id DESC",
            (user_id,),
        )
        return c.fetchall()


def all_approved_purchases():
    with get_cursor() as c:
        c.execute("SELECT * FROM purchases WHERE status='approved'")
        return c.fetchall()


# ---------------------------------------------------------------- charge requests
def create_charge_request(user_id, amount, receipt_file_id):
    with get_cursor(commit=True) as c:
        c.execute(
            "INSERT INTO charge_requests(user_id,amount,receipt_file_id,created_at) "
            "VALUES(?,?,?,?)",
            (user_id, amount, receipt_file_id, now()),
        )
        return c.lastrowid


def set_charge_admin_msg(req_id, admin_msg_id):
    with get_cursor(commit=True) as c:
        c.execute("UPDATE charge_requests SET admin_msg_id=? WHERE id=?", (admin_msg_id, req_id))


def get_charge_request(req_id):
    with get_cursor() as c:
        c.execute("SELECT * FROM charge_requests WHERE id=?", (req_id,))
        return c.fetchone()


def set_charge_status(req_id, status):
    with get_cursor(commit=True) as c:
        c.execute("UPDATE charge_requests SET status=? WHERE id=?", (status, req_id))


def pending_charge_requests():
    with get_cursor() as c:
        c.execute("SELECT * FROM charge_requests WHERE status='pending' ORDER BY id DESC")
        return c.fetchall()


# ---------------------------------------------------------------- gift codes
def generate_code(length=8):
    chars = string.ascii_uppercase + string.digits
    return "".join(random.choice(chars) for _ in range(length))


def create_gift_code(points, max_uses):
    code = generate_code()
    with get_cursor(commit=True) as c:
        while True:
            c.execute("SELECT 1 FROM gift_codes WHERE code=?", (code,))
            if not c.fetchone():
                break
            code = generate_code()
        c.execute(
            "INSERT INTO gift_codes(code,points,max_uses,created_at) VALUES(?,?,?,?)",
            (code, points, max_uses, now()),
        )
    return code


def get_gift_code(code):
    with get_cursor() as c:
        c.execute("SELECT * FROM gift_codes WHERE code=?", (code,))
        return c.fetchone()


def redeem_gift_code(code, user_id):
    """اگر کد معتبر باشد و کاربر قبلا استفاده نکرده باشد، مصرف می‌کند و مقدار امتیاز را
    برمی‌گرداند. در غیر این‌صورت None برمی‌گرداند به همراه دلیل."""
    with get_cursor(commit=True) as c:
        c.execute("SELECT * FROM gift_codes WHERE code=?", (code,))
        row = c.fetchone()
        if not row:
            return None, "not_found"
        if row["used_count"] >= row["max_uses"]:
            return None, "exhausted"
        c.execute("SELECT 1 FROM gift_code_uses WHERE code=? AND user_id=?", (code, user_id))
        if c.fetchone():
            return None, "already_used"
        c.execute("INSERT INTO gift_code_uses(code,user_id) VALUES(?,?)", (code, user_id))
        c.execute("UPDATE gift_codes SET used_count = used_count + 1 WHERE code=?", (code,))
        c.execute("UPDATE users SET points = points + ? WHERE user_id=?", (row["points"], user_id))
        return row["points"], None


# ---------------------------------------------------------------- custom buttons
def list_custom_buttons(enabled_only=True):
    with get_cursor() as c:
        if enabled_only:
            c.execute("SELECT * FROM custom_buttons WHERE enabled=1 ORDER BY id")
        else:
            c.execute("SELECT * FROM custom_buttons ORDER BY id")
        return c.fetchall()


def add_custom_button(text, response_text):
    with get_cursor(commit=True) as c:
        c.execute("INSERT INTO custom_buttons(text,response_text) VALUES(?,?)",
                   (text, response_text))


def delete_custom_button(btn_id):
    with get_cursor(commit=True) as c:
        c.execute("DELETE FROM custom_buttons WHERE id=?", (btn_id,))


def get_custom_button(btn_id):
    with get_cursor() as c:
        c.execute("SELECT * FROM custom_buttons WHERE id=?", (btn_id,))
        return c.fetchone()


# ---------------------------------------------------------------- button visibility (predefined)
def is_button_visible(key):
    with get_cursor() as c:
        c.execute("SELECT enabled FROM button_visibility WHERE button_key=?", (key,))
        row = c.fetchone()
        return True if row is None else bool(row["enabled"])


def toggle_button_visibility(key):
    with get_cursor(commit=True) as c:
        c.execute("SELECT enabled FROM button_visibility WHERE button_key=?", (key,))
        row = c.fetchone()
        if row is None:
            c.execute("INSERT INTO button_visibility(button_key,enabled) VALUES(?,0)", (key,))
        else:
            new_val = 0 if row["enabled"] else 1
            c.execute("UPDATE button_visibility SET enabled=? WHERE button_key=?", (new_val, key))


def all_visibility():
    with get_cursor() as c:
        c.execute("SELECT button_key, enabled FROM button_visibility")
        return {r["button_key"]: bool(r["enabled"]) for r in c.fetchall()}


# ---------------------------------------------------------------- support map
def map_support_message(admin_msg_id, user_id):
    with get_cursor(commit=True) as c:
        c.execute(
            "INSERT OR REPLACE INTO support_map(admin_msg_id,user_id) VALUES(?,?)",
            (admin_msg_id, user_id),
        )


def get_support_user(admin_msg_id):
    with get_cursor() as c:
        c.execute("SELECT user_id FROM support_map WHERE admin_msg_id=?", (admin_msg_id,))
        row = c.fetchone()
        return row["user_id"] if row else None


# ---------------------------------------------------------------- stats
def stats_summary():
    with get_cursor() as c:
        c.execute("SELECT COUNT(*) n FROM users")
        total_users = c.fetchone()["n"]
        c.execute("SELECT COUNT(*) n FROM purchases WHERE status='approved'")
        total_sales = c.fetchone()["n"]
        c.execute(
            "SELECT COALESCE(SUM(CAST(price_text AS INTEGER)),0) s FROM purchases "
            "WHERE status='approved' AND package_type='config'"
        )
        try:
            total_revenue = c.fetchone()["s"]
        except Exception:
            total_revenue = 0
        c.execute("SELECT COUNT(*) n FROM purchases WHERE status='pending'")
        pending_purchases = c.fetchone()["n"]
        c.execute("SELECT COUNT(*) n FROM charge_requests WHERE status='pending'")
        pending_charges = c.fetchone()["n"]
        c.execute("SELECT COUNT(*) n FROM users WHERE is_banned=1")
        banned = c.fetchone()["n"]
        return {
            "total_users": total_users,
            "total_sales": total_sales,
            "total_revenue": total_revenue,
            "pending_purchases": pending_purchases,
            "pending_charges": pending_charges,
            "banned": banned,
        }
