#!/usr/bin/env python3
import json, os, sqlite3, threading, time, secrets, hashlib, base64, urllib.parse, urllib.request
from datetime import datetime, timezone, timedelta
try:
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo("Asia/Shanghai")
except Exception:
    TZ = timezone(timedelta(hours=8))
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "state.db")
PORT = int(os.environ.get("PORT", "8080"))
LOCK = threading.Lock()
COOKIE = "cy_sid"
LEGACY = "legacy"

with open(os.path.join(BASE, "words.json"), encoding="utf-8") as f:
    WORDS = json.load(f)

def load_conf():
    p = os.path.join(BASE, "oidc.json")
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)

CONF = load_conf()

def db():
    c = sqlite3.connect(DB, timeout=10)
    c.row_factory = sqlite3.Row
    return c

ITEM_COLS = "word, uid, def, pinyin, ease, interval, due, reps, lapses, seen, correct, last_seen, last_ms, quote, gloss, example, similar, opposite, usage, story"

def init():
    with db() as c:
        cols = [r[1] for r in c.execute("PRAGMA table_info(items)")]
        if cols and "uid" not in cols:
            c.execute("ALTER TABLE items RENAME TO items_legacy")
            cols = []
        c.executescript("""
        CREATE TABLE IF NOT EXISTS items(
          word TEXT, uid TEXT, def TEXT, pinyin TEXT,
          ease REAL DEFAULT 2.5, interval REAL DEFAULT 0, due INTEGER DEFAULT 0,
          reps INTEGER DEFAULT 0, lapses INTEGER DEFAULT 0,
          seen INTEGER DEFAULT 0, correct INTEGER DEFAULT 0,
          last_seen INTEGER DEFAULT 0, last_ms INTEGER DEFAULT 0,
          quote TEXT, gloss TEXT, example TEXT, similar TEXT, opposite TEXT, usage TEXT, story TEXT,
          PRIMARY KEY(word, uid));
        CREATE TABLE IF NOT EXISTS log(
          id INTEGER PRIMARY KEY AUTOINCREMENT, word TEXT, ts INTEGER, ok INTEGER, ms INTEGER, skip INTEGER DEFAULT 0, uid TEXT);
        CREATE TABLE IF NOT EXISTS sessions(
          sid TEXT PRIMARY KEY, uid TEXT, name TEXT, created INTEGER, expires INTEGER);
        CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);
        """)
        if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='items_legacy'").fetchone():
            old_cols = "def, pinyin, ease, interval, due, reps, lapses, seen, correct, last_seen, last_ms, quote, gloss, example, similar, opposite, usage, story"
            c.execute("INSERT OR IGNORE INTO items(word, uid, def, pinyin, ease, interval, due, reps, lapses, seen, correct, last_seen, last_ms, quote, gloss, example, similar, opposite, usage, story) SELECT word, '" + LEGACY + "', " + old_cols + " FROM items_legacy")
            c.execute("DROP TABLE items_legacy")
        for col, ddl in [("skip", "ALTER TABLE log ADD COLUMN skip INTEGER DEFAULT 0"),
                         ("uid", "ALTER TABLE log ADD COLUMN uid TEXT")]:
            try:
                c.execute(ddl)
            except sqlite3.OperationalError:
                pass
        c.execute("UPDATE log SET uid=? WHERE uid IS NULL", (LEGACY,))
        n = c.execute("SELECT COUNT(*) n FROM items WHERE uid=?", (LEGACY,)).fetchone()["n"]
        if n == 0:
            c.execute("INSERT OR IGNORE INTO items(word,uid) SELECT value,? FROM json_each(?)",
                      (LEGACY, json.dumps([w["word"] for w in WORDS])))

def seed_user(c, uid):
    c.execute("INSERT OR IGNORE INTO items(word,uid) SELECT value,? FROM json_each(?)",
              (uid, json.dumps([w["word"] for w in WORDS])))

def txt(v):
    if v is None:
        return None
    if isinstance(v, (list, tuple)):
        return "；".join(str(x) for x in v)
    if isinstance(v, dict):
        return json.dumps(v, ensure_ascii=False)
    return str(v)

def sync_words(c, uid):
    for w in WORDS:
        c.execute("UPDATE items SET def=?, pinyin=?, gloss=?, quote=?, example=?, similar=?, opposite=?, usage=?, story=? WHERE word=? AND uid=?",
                  (txt(w.get("def")), txt(w.get("pinyin")), txt(w.get("gloss")), txt(w.get("quote")), txt(w.get("example")),
                   json.dumps(w.get("similar") or [], ensure_ascii=False),
                   json.dumps(w.get("opposite") or [], ensure_ascii=False), txt(w.get("usage")),
                   json.dumps(w.get("story") or [], ensure_ascii=False), w["word"], uid))

def row_to_item(r):
    return {
        "word": r["word"], "def": r["def"], "pinyin": r["pinyin"],
        "gloss": r["gloss"], "quote": r["quote"], "example": r["example"],
        "similar": json.loads(r["similar"]) if r["similar"] else [],
        "opposite": json.loads(r["opposite"]) if r["opposite"] else [],
        "usage": r["usage"],
        "story": json.loads(r["story"]) if r["story"] else [],
        "ease": round(r["ease"], 2), "interval": round(r["interval"], 3), "due": r["due"],
        "reps": r["reps"], "lapses": r["lapses"], "seen": r["seen"], "correct": r["correct"],
        "acc": round(100 * r["correct"] / r["seen"]) if r["seen"] else None,
        "lastSeen": r["last_seen"],
    }

def get_item(word, uid):
    with db() as c:
        r = c.execute("SELECT * FROM items WHERE word=? AND uid=?", (word, uid)).fetchone()
    return row_to_item(r) if r else None

def review(word, uid, ok, ms, skip=False):
    now = int(time.time() * 1000)
    with LOCK, db() as c:
        r = c.execute("SELECT * FROM items WHERE word=? AND uid=?", (word, uid)).fetchone()
        if not r:
            return None
        ease, interval, reps, lapses = r["ease"], r["interval"], r["reps"], r["lapses"]
        if skip:
            interval = 1.0
            due = now + int(interval * 86400000)
            c.execute("UPDATE items SET interval=?, due=?, seen=seen+1, last_seen=?, last_ms=? WHERE word=? AND uid=?",
                      (interval, due, now, ms, word, uid))
            c.execute("INSERT INTO log(word,ts,ok,ms,skip,uid) VALUES(?,?,?,?,1,?)", (word, now, 0, ms, uid))
            return get_item(word, uid)
        if ok:
            ease = min(2.8, ease + 0.05)
            if reps == 0:
                interval = 1.0
            elif reps == 1:
                interval = 3.0
            else:
                interval = min(180.0, max(1.0, interval * ease))
            reps += 1
        else:
            ease = max(1.3, ease - 0.2)
            lapses += 1
            reps = 0
            interval = 1.0
        due = now + int(interval * 86400000)
        c.execute("""UPDATE items SET ease=?, interval=?, due=?, reps=?, lapses=?,
                     seen=seen+1, correct=correct+?, last_seen=?, last_ms=? WHERE word=? AND uid=?""",
                  (ease, interval, due, reps, lapses, 1 if ok else 0, now, ms, word, uid))
        c.execute("INSERT INTO log(word,ts,ok,ms,uid) VALUES(?,?,?,?,?)", (word, now, 1 if ok else 0, ms, uid))
    return get_item(word, uid)

def recommend(uid, limit):
    now = int(time.time() * 1000)
    with db() as c:
        rows = c.execute("SELECT * FROM items WHERE uid=? AND seen>0 AND due<=? ORDER BY due ASC, ease ASC LIMIT ?",
                         (uid, now, limit)).fetchall()
    return [row_to_item(r) for r in rows]

def summary(uid):
    now = int(time.time() * 1000)
    day = 86400000
    with db() as c:
        total = c.execute("SELECT COUNT(*) n FROM items WHERE uid=?", (uid,)).fetchone()["n"]
        seen = c.execute("SELECT COUNT(*) n FROM items WHERE uid=? AND seen>0", (uid,)).fetchone()["n"]
        mastered = c.execute("SELECT COUNT(*) n FROM items WHERE uid=? AND interval>=7", (uid,)).fetchone()["n"]
        due = c.execute("SELECT COUNT(*) n FROM items WHERE uid=? AND seen>0 AND due<=?", (uid, now)).fetchone()["n"]
        logs = c.execute("SELECT COUNT(*) n, SUM(ok) k FROM log WHERE uid=? AND ts>=? AND skip=0", (uid, now - 7 * day)).fetchone()
        today = c.execute("SELECT COUNT(*) n, SUM(ok) k FROM log WHERE uid=? AND ts>=? AND skip=0", (uid, now - day)).fetchone()
        weak = [row_to_item(r) for r in c.execute("SELECT * FROM items WHERE uid=? AND seen>0 ORDER BY (CAST(correct AS REAL)/seen) ASC LIMIT 5", (uid,))]
        day_start = int(datetime.now(TZ).replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)
        new_today = c.execute("SELECT COUNT(*) n FROM (SELECT word, MIN(ts) f FROM log WHERE uid=? GROUP BY word) WHERE f>=?", (uid, day_start)).fetchone()["n"]
        today_total = today["n"] or 0
        new_words = c.execute("SELECT COUNT(*) n FROM items WHERE uid=? AND seen=0", (uid,)).fetchone()["n"]
        days = [r["d"] for r in c.execute("SELECT DISTINCT date(ts/1000,'unixepoch','localtime') d FROM log WHERE uid=? ORDER BY d DESC LIMIT 60", (uid,))]
    streak = 0
    if days:
        from datetime import date, timedelta
        cur = date.today()
        if days[0] != cur.isoformat():
            cur = cur - timedelta(days=1)
        for d in days:
            if d == cur.isoformat():
                streak += 1
                cur = cur - timedelta(days=1)
            else:
                break
    return {"total": total, "seen": seen, "mastered": mastered, "due": due,
            "acc7": round(100 * (logs["k"] or 0) / logs["n"]) if logs["n"] else None,
            "reviews7": logs["n"] or 0, "today": today_total,
            "todayAcc": round(100 * (today["k"] or 0) / today_total) if today_total else None,
            "todayNew": new_today, "todayReview": max(0, today_total - new_today),
            "newWords": new_words, "streak": streak, "weak": weak}

PENDING = {}
SESS_DAYS = 30

def new_sid():
    return secrets.token_urlsafe(32)

def get_session(sid):
    if not sid:
        return None
    now = int(time.time())
    with db() as c:
        r = c.execute("SELECT * FROM sessions WHERE sid=?", (sid,)).fetchone()
    if not r or r["expires"] < now:
        return None
    return {"uid": r["uid"], "name": r["name"]}

def http_json(url, data=None, headers=None):
    body = None
    hdrs = {"Accept": "application/json"}
    if headers:
        hdrs.update(headers)
    if data is not None:
        body = urllib.parse.urlencode(data).encode()
        hdrs["Content-Type"] = "application/x-www-form-urlencoded"
    req = urllib.request.Request(url, data=body, headers=hdrs)
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode())

def claim_legacy(uid):
    with LOCK, db() as c:
        if c.execute("SELECT v FROM meta WHERE k='claimed'").fetchone():
            return
        c.execute("DELETE FROM items WHERE uid=? AND seen=0", (uid,))
        c.execute("DELETE FROM items WHERE uid=? AND word IN (SELECT word FROM items WHERE uid=?)", (uid, LEGACY))
        c.execute("UPDATE items SET uid=? WHERE uid=?", (uid, LEGACY))
        c.execute("UPDATE log SET uid=? WHERE uid=?", (uid, LEGACY))
        c.execute("INSERT OR REPLACE INTO meta(k,v) VALUES('claimed',?)", (uid,))

class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=BASE, **kw)

    def log_message(self, fmt, *args):
        pass

    def sid(self):
        raw = self.headers.get("Cookie") or ""
        for part in raw.split(";"):
            k, _, v = part.strip().partition("=")
            if k == COOKIE:
                return v
        return None

    def send_json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def redirect(self, url, cookie=None):
        self.send_response(302)
        self.send_header("Location", url)
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        try:
            return self._get()
        except Exception as e:
            try:
                return self.send_json({"error": "server error", "detail": str(e)[:200]}, 500)
            except Exception:
                pass

    def _get(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        sess = get_session(self.sid())

        if u.path == "/notice":
            self.path = "/notice.html"
            return super().do_GET()

        if u.path == "/login":
            if not CONF:
                return self.send_json({"error": "oidc not configured"}, 500)
            if (q.get("accept") or [""])[0] != "1":
                return self.redirect("/notice")
            state = secrets.token_urlsafe(24)
            verifier = secrets.token_urlsafe(48)
            PENDING[state] = (verifier, time.time())
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
            params = {
                "response_type": "code", "client_id": CONF["client_id"],
                "redirect_uri": CONF["redirect_uri"], "scope": "openid profile email",
                "state": state, "code_challenge": challenge, "code_challenge_method": "S256",
            }
            return self.redirect(CONF["issuer"] + "/oidc/authorize?" + urllib.parse.urlencode(params))

        if u.path == "/oidc/callback":
            code = (q.get("code") or [""])[0]
            state = (q.get("state") or [""])[0]
            ver = PENDING.pop(state, None)
            if not code or not ver:
                return self.redirect("/login")
            try:
                tok = http_json(CONF["issuer"] + "/oidc/token", {
                    "grant_type": "authorization_code", "code": code,
                    "redirect_uri": CONF["redirect_uri"], "client_id": CONF["client_id"],
                    "client_secret": CONF["client_secret"], "code_verifier": ver[0],
                })
                info = http_json(CONF["issuer"] + "/oidc/userinfo", None, {"Authorization": "Bearer " + tok["access_token"]})
            except Exception as e:
                return self.send_json({"error": "oidc failed", "detail": str(e)[:200]}, 502)
            uid = str(info.get("sub") or "")
            name = info.get("preferred_username") or info.get("name") or uid[:8]
            if not uid:
                return self.send_json({"error": "no sub"}, 502)
            sid = new_sid()
            now = int(time.time())
            with LOCK, db() as c:
                seed_user(c, uid)
                sync_words(c, uid)
                c.execute("INSERT INTO sessions(sid,uid,name,created,expires) VALUES(?,?,?,?,?)",
                          (sid, uid, name, now, now + SESS_DAYS * 86400))
            claim_legacy(uid)
            return self.redirect("/", cookie=f"{COOKIE}={sid}; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age={SESS_DAYS*86400}")

        if u.path == "/logout":
            sid = self.sid()
            if sid:
                with LOCK, db() as c:
                    c.execute("DELETE FROM sessions WHERE sid=?", (sid,))
            return self.redirect("/login", cookie=f"{COOKIE}=; Path=/; Max-Age=0; HttpOnly; Secure; SameSite=Lax")

        if u.path.startswith("/api/"):
            if not sess:
                return self.send_json({"error": "login required"}, 401)
            if u.path == "/api/me":
                return self.send_json(sess)
            if u.path == "/api/words":
                return self.send_json(WORDS)
            if u.path == "/api/summary":
                return self.send_json(summary(sess["uid"]))
            if u.path == "/api/state":
                with db() as c:
                    items = [row_to_item(r) for r in c.execute("SELECT * FROM items WHERE uid=?", (sess["uid"],))]
                return self.send_json(items)
            if u.path == "/api/recommend":
                limit = int(q.get("limit", ["15"])[0])
                return self.send_json(recommend(sess["uid"], max(1, min(60, limit))))
            return self.send_json({"error": "not found"}, 404)

        if not sess:
            return self.redirect("/notice")
        if u.path == "/":
            self.path = "/dist/index.html"
        elif u.path.startswith("/assets/"):
            self.path = "/dist" + u.path
        elif u.path.endswith(".html"):
            pass
        else:
            rel = u.path.lstrip("/")
            if not os.path.exists(os.path.join(BASE, rel)):
                self.path = "/dist/index.html"
        super().do_GET()

    def end_headers(self):
        if self.path.endswith(".html"):
            self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_POST(self):
        try:
            return self._post()
        except Exception as e:
            try:
                return self.send_json({"error": "server error", "detail": str(e)[:200]}, 500)
            except Exception:
                pass

    def _post(self):
        u = urlparse(self.path)
        sess = get_session(self.sid())
        if not sess:
            return self.send_json({"error": "login required"}, 401)
        if u.path != "/api/review":
            return self.send_json({"error": "not found"}, 404)
        n = int(self.headers.get("Content-Length") or 0)
        try:
            data = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return self.send_json({"error": "bad json"}, 400)
        word = str(data.get("word", ""))
        ok = bool(data.get("ok"))
        skip = bool(data.get("skip"))
        ms = int(data.get("ms") or 0)
        item = review(word, sess["uid"], ok, ms, skip)
        if not item:
            return self.send_json({"error": "unknown word"}, 404)
        return self.send_json({"ok": True, "item": item, "summary": summary(sess["uid"])})

if __name__ == "__main__":
    init()
    if CONF:
        with LOCK, db() as c:
            seed_user(c, LEGACY)
            sync_words(c, LEGACY)
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print("chengyu server on", PORT, "oidc" if CONF else "no-oidc")
    srv.serve_forever()
