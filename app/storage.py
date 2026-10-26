import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

DATA_DIR = Path(os.environ.get('ACADEMY_DATA_DIR', './data')).resolve()
DB_PATH = DATA_DIR / 'academy.sqlite3'
SESSION_AGE = 14 * 24 * 3600


def connect():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH, timeout=15)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA busy_timeout=15000')
    c.execute('PRAGMA foreign_keys=ON')
    return c


def init_db():
    with connect() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS users (
          id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE,
          password_hash TEXT NOT NULL, is_admin INTEGER NOT NULL DEFAULT 0,
          created_at INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS sessions (
          token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          csrf TEXT NOT NULL, expires INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS progress (
          user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          kind TEXT NOT NULL, item_id TEXT NOT NULL, completed_at INTEGER NOT NULL,
          PRIMARY KEY(user_id, kind, item_id));
        CREATE TABLE IF NOT EXISTS attempts (
          id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          lesson_id TEXT NOT NULL, score INTEGER NOT NULL,
          total INTEGER NOT NULL, created_at INTEGER NOT NULL);
        CREATE INDEX IF NOT EXISTS attempts_user_idx ON attempts(user_id,lesson_id);
        CREATE TABLE IF NOT EXISTS achievements (
          user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          badge_id TEXT NOT NULL, earned_at INTEGER NOT NULL,
          PRIMARY KEY(user_id, badge_id));
        ''')


def hash_password(password):
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return 'scrypt$' + salt.hex() + '$' + digest.hex()


def check_password(password, encoded):
    try:
        scheme, hexsalt, hexdigest = encoded.split('$')
        if scheme != 'scrypt':
            return False
        test = hashlib.scrypt(password.encode(), salt=bytes.fromhex(hexsalt), n=2**14, r=8, p=1)
        return hmac.compare_digest(test, bytes.fromhex(hexdigest))
    except (ValueError, TypeError):
        return False


def valid_username(value):
    return bool(re.fullmatch(r'[a-z][a-z0-9._-]{2,31}', value))


def add_user(username, password, admin=False):
    if not valid_username(username) or len(password) < 12 or len(password) > 256:
        raise ValueError('Логин: 3–32 символа [a-z0-9._-], пароль: минимум 12 символов.')
    with connect() as c:
        c.execute('INSERT INTO users(username,password_hash,is_admin,created_at) VALUES(?,?,?,?)',
                  (username, hash_password(password), int(admin), int(time.time())))



def create_guest_session():
    """Create an unprivileged, passwordless browser identity; returns a bearer token.
    Password login is deliberately impossible for these synthetic accounts.
    """
    username = 'guest-' + secrets.token_hex(12)
    with connect() as c:
        cursor = c.execute(
            'INSERT INTO users(username,password_hash,is_admin,created_at) VALUES(?,?,0,?)',
            (username, '!disabled-guest-login', int(time.time())))
        user_id = cursor.lastrowid
    return create_session(user_id, age=GUEST_SESSION_AGE)


GUEST_SESSION_AGE = 365 * 24 * 3600


def count_users():
    with connect() as c:
        return c.execute('SELECT count(*) FROM users').fetchone()[0]


def authenticate(username, password):
    with connect() as c:
        row = c.execute('SELECT * FROM users WHERE username=?', (username,)).fetchone()
        if row and check_password(password, row['password_hash']):
            return dict(row)
    return None


def create_session(user_id, age=SESSION_AGE):
    token = secrets.token_urlsafe(40)
    csrf = secrets.token_urlsafe(32)
    now = int(time.time())
    with connect() as c:
        c.execute('DELETE FROM sessions WHERE expires<?', (now,))
        c.execute('INSERT INTO sessions VALUES (?,?,?,?)',
                  (hashlib.sha256(token.encode()).hexdigest(), user_id, csrf, now + age))
    return token


def get_session(token):
    if not token:
        return None
    digest = hashlib.sha256(token.encode()).hexdigest()
    with connect() as c:
        row = c.execute('''SELECT u.id,u.username,u.is_admin,s.csrf,
            CASE WHEN u.password_hash='!disabled-guest-login' THEN 1 ELSE 0 END AS is_guest
            FROM sessions s
            JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires>?''',
            (digest, int(time.time()))).fetchone()
        return dict(row) if row else None


def revoke_session(token):
    if token:
        with connect() as c:
            c.execute('DELETE FROM sessions WHERE token_hash=?', (hashlib.sha256(token.encode()).hexdigest(),))


def complete(user_id, kind, item_id):
    with connect() as c:
        c.execute('INSERT OR IGNORE INTO progress VALUES(?,?,?,?)', (user_id, kind, item_id, int(time.time())))


def completed(user_id):
    with connect() as c:
        return {(r['kind'], r['item_id']) for r in c.execute('SELECT kind,item_id FROM progress WHERE user_id=?',(user_id,))}


def record_attempt(user_id, lesson_id, score, total):
    with connect() as c:
        c.execute('INSERT INTO attempts(user_id,lesson_id,score,total,created_at) VALUES(?,?,?,?,?)',
                  (user_id,lesson_id,score,total,int(time.time())))


def list_users():
    with connect() as c:
        return [dict(r) for r in c.execute('''SELECT u.id,u.username,u.is_admin,u.created_at,
         count(p.item_id) AS completed FROM users u LEFT JOIN progress p ON u.id=p.user_id
         GROUP BY u.id ORDER BY u.id''')]


def reset_password(user_id, password):
    if not 12 <= len(password) <= 256:
        raise ValueError('Пароль должен содержать не менее 12 символов.')
    with connect() as c:
        c.execute('UPDATE users SET password_hash=? WHERE id=?',(hash_password(password),user_id))
        c.execute('DELETE FROM sessions WHERE user_id=?',(user_id,))


def register(username, password, guest_user_id=None):
    """Claim an existing guest identity without losing its labs or progress."""
    username = str(username).strip().lower()
    if not valid_username(username) or username.startswith('guest-'):
        raise ValueError('Логин: 3–32 символа, латиница, цифры, точка, тире и подчёркивание.')
    if len(password) < 12 or len(password) > 256:
        raise ValueError('Пароль должен содержать от 12 до 256 символов.')
    encoded=hash_password(password)
    with connect() as c:
        if guest_user_id is not None:
            result=c.execute(
              "UPDATE users SET username=?,password_hash=? WHERE id=? AND password_hash='!disabled-guest-login'",
              (username,encoded,int(guest_user_id)))
            if result.rowcount != 1:
                raise ValueError('Гостевой профиль недоступен для регистрации.')
            uid=int(guest_user_id)
        else:
            cur=c.execute('INSERT INTO users(username,password_hash,is_admin,created_at) VALUES(?,?,0,?)',
                          (username,encoded,int(time.time())))
            uid=cur.lastrowid
        c.execute('DELETE FROM sessions WHERE user_id=?',(uid,))
    return uid


def revoke_user_sessions(user_id):
    with connect() as c:
        c.execute('DELETE FROM sessions WHERE user_id=?',(int(user_id),))


def awarded_badges(user_id):
    with connect() as c:
        return {r['badge_id']:r['earned_at'] for r in
            c.execute('SELECT badge_id,earned_at FROM achievements WHERE user_id=?',(user_id,))}


def award_badges(user_id, badge_ids):
    now=int(time.time())
    if not badge_ids:
        return
    with connect() as c:
        c.executemany(
          'INSERT OR IGNORE INTO achievements(user_id,badge_id,earned_at) VALUES(?,?,?)',
          [(user_id,key,now) for key in badge_ids])
