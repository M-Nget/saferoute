"""
SafeRoute v5  -  Flet 0.85
  * Road-traffic-injury (RTI) risk module for international students
  * Football (soccer) injury-risk module for players
  * Per-participant data (participant code), automatic DB migration,
    researcher Excel export from inside the app
"""
import flet as ft, threading, time, random, sqlite3, json, os, uuid, glob
from datetime import datetime, timedelta
from pathlib import Path

# ══ SETTINGS ═══════════════════════════════════════════════════
DB = Path(os.environ.get("DB_PATH", "saferoute.db"))
ADMIN_KEY = os.environ.get("ADMIN_KEY", "")          # set on Render to enable export
ASSETS = Path("assets")
SENSOR_SECONDS = 10

# ══ LAYOUT HELPERS (Flet 0.85 safe) ════════════════════════════
def border_all(w, c):
    s = ft.BorderSide(w, c)
    return ft.Border(top=s, bottom=s, left=s, right=s)
def pad(l=0, r=0, t=0, b=0): return ft.Padding(left=l, right=r, top=t, bottom=b)
def pad_all(v): return pad(v, v, v, v)
def pad_hv(h, v): return pad(h, h, v, v)
def mar_all(v): return ft.Margin(left=v, right=v, top=v, bottom=v)
CENTER = ft.Alignment(0, 0)

C = dict(bg="#0D1117", surf="#161B22", surf2="#21262D", bord="#30363D",
         pri="#00D4AA", warn="#F4A261", dang="#E76F51", crit="#C1121F",
         txt="#E6EDF3", dim="#7D8590", fb="#3FB950")

def tier(s):
    if s < 3: return "LOW", "#00D4AA"
    if s < 6: return "MODERATE", "#F4A261"
    if s < 8: return "HIGH", "#E76F51"
    return "CRITICAL", "#C1121F"

# ══ RTI SURVEY (EMA) ═══════════════════════════════════════════
EMA = [
    {"id": "fatigue", "dom": "Fatigue", "q": "How tired are you right now?",
     "t": "slider", "max": 10, "lo": "0 = Not tired", "hi": "10 = Exhausted"},
    {"id": "stress", "dom": "Stress (0–100)",
     "q": "Rate your stress level.\n0 = completely calm | 50 = moderate | 100 = extreme",
     "t": "slider", "max": 100, "lo": "0 = Calm", "hi": "100 = Extreme"},
    {"id": "safety", "dom": "Perceived Safety", "q": "How safe do you feel right now?",
     "t": "lik", "o": ["1 - Very unsafe", "2 - Unsafe", "3 - Neutral", "4 - Safe", "5 - Very safe"]},
    {"id": "dist", "dom": "Distraction", "q": "Were you using your phone while walking?",
     "t": "lik", "o": ["Yes", "Partially", "No"]},
    {"id": "fam", "dom": "Familiarity", "q": "How familiar are you with this area?",
     "t": "lik", "o": ["1 - Not at all", "2 - Slightly", "3 - Somewhat", "4 - Mostly", "5 - Very well"]},
    {"id": "nm", "dom": "Near-miss",
     "q": "Did anything almost happen just now?\n(vehicle came close, almost fell, near collision)",
     "t": "yn"},
    {"id": "cult", "dom": "Cultural confusion", "q": "Do local traffic norms confuse you right now?",
     "t": "lik", "o": ["1 - Not at all", "2 - Slightly", "3 - Somewhat", "4 - Quite", "5 - Very much"]},
    {"id": "acad", "dom": "Academic stress", "q": "How stressed are you about your studies today?",
     "t": "lik", "o": ["1 - None", "2 - Low", "3 - Moderate", "4 - High", "5 - Extreme"]},
]
EMA_REQUIRED = ["fatigue", "stress", "safety", "fam"]

# ══ DATABASE ═══════════════════════════════════════════════════
SCHEMA = {
    "ema": {"id": "INTEGER PRIMARY KEY AUTOINCREMENT", "pid": "TEXT", "ts": "TEXT", "ans": "TEXT",
            "trigger_type": "TEXT", "nearest_risk_id": "INTEGER", "session_minutes": "REAL"},
    "risk": {"id": "INTEGER PRIMARY KEY AUTOINCREMENT", "pid": "TEXT", "ts": "TEXT", "score": "REAL",
             "tier": "TEXT", "fatigue": "REAL", "stress": "REAL", "familiarity": "REAL",
             "distraction": "TEXT", "cultural": "REAL", "near_miss": "INTEGER", "ema_id": "INTEGER"},
    "profile": {"id": "INTEGER PRIMARY KEY AUTOINCREMENT", "pid": "TEXT", "ts": "TEXT",
                "full_name": "TEXT", "country": "TEXT", "university": "TEXT",
                "years_in_china": "TEXT", "academic_level": "TEXT", "transport": "TEXT",
                "housing": "TEXT"},
    "fb_profile": {"id": "INTEGER PRIMARY KEY AUTOINCREMENT", "pid": "TEXT", "ts": "TEXT",
                   "age": "INTEGER", "position": "TEXT", "level": "TEXT",
                   "prev_injury": "TEXT", "weekly_sessions": "TEXT"},
    "fb_wellness": {"id": "INTEGER PRIMARY KEY AUTOINCREMENT", "pid": "TEXT", "ts": "TEXT",
                    "sleep_h": "REAL", "sleep_q": "INTEGER", "soreness": "INTEGER",
                    "fatigue": "INTEGER", "stress": "INTEGER", "mood": "INTEGER",
                    "pain_now": "TEXT", "pain_area": "TEXT", "acwr": "REAL",
                    "score": "REAL", "tier": "TEXT"},
    "fb_session": {"id": "INTEGER PRIMARY KEY AUTOINCREMENT", "pid": "TEXT", "ts": "TEXT",
                   "kind": "TEXT", "minutes": "REAL", "rpe": "REAL", "load": "REAL"},
    "fb_injury": {"id": "INTEGER PRIMARY KEY AUTOINCREMENT", "pid": "TEXT", "ts": "TEXT",
                  "area": "TEXT", "context": "TEXT", "severity": "TEXT", "days_out": "INTEGER"},
}

def conn_():
    return sqlite3.connect(DB, timeout=15)

def init_db():
    """Create tables and ADD any missing columns to old databases."""
    c = conn_()
    for tbl, cols in SCHEMA.items():
        c.execute(f"CREATE TABLE IF NOT EXISTS {tbl}(id INTEGER PRIMARY KEY AUTOINCREMENT)")
        have = {r[1] for r in c.execute(f"PRAGMA table_info({tbl})")}
        for name, typ in cols.items():
            if name not in have:
                c.execute(f"ALTER TABLE {tbl} ADD COLUMN {name} {typ.replace(' PRIMARY KEY AUTOINCREMENT','')}")
    c.commit(); c.close()

def now_iso(): return datetime.now().isoformat(timespec="seconds")

def q_all(sql, args=()):
    c = conn_(); r = c.execute(sql, args).fetchall(); c.close(); return r

def q_one(sql, args=()):
    c = conn_(); r = c.execute(sql, args).fetchone(); c.close(); return r

def q_run(sql, args=()):
    c = conn_(); cur = c.execute(sql, args); c.commit(); i = cur.lastrowid; c.close(); return i

# --- RTI data
def db_save_ema(pid, ans, trigger_type="manual"):
    nr = q_one("SELECT id FROM risk WHERE pid=? ORDER BY id DESC LIMIT 1", (pid,))
    mins = (q_one("SELECT COUNT(*) FROM risk WHERE pid=?", (pid,))[0] or 0) * SENSOR_SECONDS / 60.0
    return q_run("INSERT INTO ema(pid,ts,ans,trigger_type,nearest_risk_id,session_minutes)VALUES(?,?,?,?,?,?)",
                 (pid, now_iso(), json.dumps(ans), trigger_type, nr[0] if nr else None, round(mins, 2)))

def db_save_risk(pid, score, t, fat, str_, fam, dist, cult, nm, ema_id):
    q_run("INSERT INTO risk(pid,ts,score,tier,fatigue,stress,familiarity,distraction,cultural,near_miss,ema_id)"
          "VALUES(?,?,?,?,?,?,?,?,?,?,?)", (pid, now_iso(), score, t, fat, str_, fam, dist, cult, nm, ema_id))

def db_last_ema(pid):
    r = q_one("SELECT id,ans,ts FROM ema WHERE pid=? ORDER BY id DESC LIMIT 1", (pid,))
    if r:
        try: return r[0], json.loads(r[1]), r[2]
        except Exception: pass
    return None, {}, None

def db_minutes_since_ema(pid):
    _, _, ts = db_last_ema(pid)
    if not ts: return 9999
    try: return (datetime.now() - datetime.fromisoformat(ts)).total_seconds() / 60
    except Exception: return 9999

def db_history(pid, n=30):
    return q_all("SELECT ts,score,tier FROM risk WHERE pid=? ORDER BY id DESC LIMIT ?", (pid, n))

def db_stats(pid):
    n1 = q_one("SELECT COUNT(*) FROM ema WHERE pid=?", (pid,))[0]
    n2 = q_one("SELECT COUNT(*) FROM risk WHERE pid=?", (pid,))[0]
    av = q_one("SELECT AVG(score) FROM risk WHERE pid=?", (pid,))[0]
    return n1, n2, round(av or 0.0, 1)

def db_save_profile(pid, d):
    q_run("DELETE FROM profile WHERE pid=?", (pid,))
    q_run("INSERT INTO profile(pid,ts,full_name,country,university,years_in_china,academic_level,transport,housing)"
          "VALUES(?,?,?,?,?,?,?,?,?)",
          (pid, now_iso(), d["name"], d["country"], d["university"], d["years"], d["level"], d["transport"], d["housing"]))

def db_load_profile(pid):
    r = q_one("SELECT full_name,country,university,years_in_china,academic_level,transport,housing "
              "FROM profile WHERE pid=? ORDER BY id DESC LIMIT 1", (pid,))
    if not r: return {}
    return dict(zip(["name", "country", "university", "years", "level", "transport", "housing"], r))

# --- Football data
def fb_load_profile(pid):
    r = q_one("SELECT age,position,level,prev_injury,weekly_sessions FROM fb_profile WHERE pid=? "
              "ORDER BY id DESC LIMIT 1", (pid,))
    if not r: return {}
    return dict(zip(["age", "position", "level", "prev_injury", "weekly"], r))

def fb_save_profile(pid, d):
    q_run("DELETE FROM fb_profile WHERE pid=?", (pid,))
    q_run("INSERT INTO fb_profile(pid,ts,age,position,level,prev_injury,weekly_sessions)VALUES(?,?,?,?,?,?,?)",
          (pid, now_iso(), d["age"], d["position"], d["level"], d["prev_injury"], d["weekly"]))

def fb_save_session(pid, kind, minutes, rpe):
    q_run("INSERT INTO fb_session(pid,ts,kind,minutes,rpe,load)VALUES(?,?,?,?,?,?)",
          (pid, now_iso(), kind, minutes, rpe, round(minutes * rpe, 1)))

def fb_load_loads(pid):
    """-> list of (datetime, load) for the last 28 days (+ first-ever session date)"""
    since = (datetime.now() - timedelta(days=28)).isoformat()
    rows = q_all("SELECT ts,load FROM fb_session WHERE pid=? AND ts>=?", (pid, since))
    first = q_one("SELECT MIN(ts) FROM fb_session WHERE pid=?", (pid,))[0]
    out = []
    for ts, ld in rows:
        try: out.append((datetime.fromisoformat(ts), ld or 0))
        except Exception: pass
    return out, (datetime.fromisoformat(first) if first else None)

def fb_save_wellness(pid, w, acwr, score, t):
    q_run("INSERT INTO fb_wellness(pid,ts,sleep_h,sleep_q,soreness,fatigue,stress,mood,pain_now,pain_area,acwr,score,tier)"
          "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
          (pid, now_iso(), w["sleep_h"], w["sleep_q"], w["soreness"], w["fatigue"], w["stress"], w["mood"],
           w["pain_now"], w.get("pain_area", ""), acwr, score, t))

def fb_last_wellness(pid):
    r = q_one("SELECT ts,score,tier,acwr,sleep_h,soreness,fatigue,pain_now FROM fb_wellness WHERE pid=? "
              "ORDER BY id DESC LIMIT 1", (pid,))
    return r

def fb_save_injury(pid, area, context, severity, days_out):
    q_run("INSERT INTO fb_injury(pid,ts,area,context,severity,days_out)VALUES(?,?,?,?,?,?)",
          (pid, now_iso(), area, context, severity, days_out))

# ══ FOOTBALL SCORING (pure function, unit-testable) ════════════
def compute_acwr(loads, first_session, now=None):
    """Acute (7d total) : chronic (28d weekly average). None until 14 days of history exist."""
    now = now or datetime.now()
    if not loads or not first_session: return None
    if (now - first_session).days < 14: return None
    acute = sum(l for d, l in loads if (now - d).days < 7)
    chronic = sum(l for d, l in loads) / 4.0
    if chronic <= 0: return None
    return round(acute / chronic, 2)

def fb_assess(w, prof, acwr):
    """w: sleep_h, sleep_q(1-5), soreness(1-5), fatigue(1-5), stress(1-5), mood(1-5), pain_now('yes'/'no').
    Returns score 0-10, tier, [(label, points, max)], [advice]. Screening heuristic - not a diagnosis."""
    f = []
    if acwr is None: p_ac = 0.0
    elif acwr > 1.5: p_ac = 3.0
    elif acwr > 1.3: p_ac = 1.8
    elif acwr < 0.8: p_ac = 0.8
    else: p_ac = 0.0
    f.append(("Training load (ACWR)", p_ac, 3.0))
    f.append(("Muscle soreness", (w["soreness"] - 1) * 0.55, 2.2))
    f.append(("Fatigue", (w["fatigue"] - 1) * 0.45, 1.8))
    sh = w["sleep_h"]
    p_sl = 1.5 if sh < 5 else 1.1 if sh < 6 else 0.6 if sh < 7 else 0.0
    p_sl += max(0, 3 - w["sleep_q"]) * 0.3
    f.append(("Sleep", p_sl, 2.1))
    f.append(("Stress / mood", (w["stress"] - 1) * 0.15 + max(0, 3 - w["mood"]) * 0.2, 1.0))
    f.append(("Pain / niggle now", 1.5 if w["pain_now"] == "yes" else 0.0, 1.5))
    p_hist = 0.0
    if prof.get("prev_injury") == "yes": p_hist += 0.8
    try:
        if int(prof.get("age") or 0) >= 30: p_hist += 0.4
    except Exception: pass
    f.append(("History (injury / age)", p_hist, 1.2))
    score = round(max(0.0, min(10.0, sum(p for _, p, _ in f))), 1)
    t, _ = tier(score)
    adv = []
    if acwr is None:
        adv.append("Load baseline still building: keep logging every session for 2+ weeks for ACWR.")
    elif acwr > 1.5:
        adv.append(f"ACWR {acwr}: load spiked. Cut volume/intensity for a few days.")
    elif acwr > 1.3:
        adv.append(f"ACWR {acwr}: load rising fast. Avoid adding more this week.")
    elif acwr < 0.8:
        adv.append(f"ACWR {acwr}: load is low vs your base. Build back gradually.")
    if w["pain_now"] == "yes": adv.append("You reported pain. Do not play through it; get it checked.")
    if sh < 7: adv.append("Sleep is short. Aim for 8+ hours before training or matches.")
    if w["soreness"] >= 4: adv.append("High soreness: prioritise recovery, mobility and a lighter session.")
    if t == "CRITICAL": adv.insert(0, "Very high risk: rest or very light work only today.")
    elif t == "HIGH": adv.insert(0, "High risk: reduce intensity and warm up thoroughly.")
    elif t == "LOW" and not adv: adv.append("Looking good. Train as planned.")
    return score, t, f, adv

# ══ RTI SENSOR ENGINE (one per participant session) ════════════
class Sensor:
    def __init__(self, pid):
        self.pid = pid; self.risk = None
        self.fat = 3; self.str_ = 25; self.fam = 4; self.dist = "no"; self.cult = 1; self.nm = 0; self.safe = 3
        self.night = False; self.rain = False; self.mode = "walking"; self.spd = 1.2
        self.min = 0.0; self._on = False; self.ema_id = None

    def start(self):
        if self._on: return
        self._on = True
        threading.Thread(target=self._loop, daemon=True).start()

    def stop(self): self._on = False

    def update_from_ema(self, ans):
        g = lambda k: ans.get(k, "")
        if g("fatigue") != "": self.fat = int(g("fatigue"))
        if g("stress") != "": self.str_ = int(g("stress"))
        if g("fam") != "": self.fam = int(g("fam")) + 1
        if g("safety") != "": self.safe = int(g("safety")) + 1
        if g("dist") != "":
            d = g("dist"); self.dist = ["yes", "partially", "no"][d] if isinstance(d, int) else str(d)
        if g("cult") != "": self.cult = int(g("cult")) + 1
        self.nm = 1 if g("nm") == "yes" else 0

    def compute(self, noise=True):
        h = datetime.now().hour
        self.night = h >= 22 or h <= 6
        base = (self.fat * 0.35 + self.str_ / 100 * 2.5 + (6 - self.fam) * 0.50 + (5 - self.safe) * 0.25
                + (1.5 if self.night else 0) + (1.0 if self.rain else 0) + (1.5 if self.nm else 0)
                + (self.cult - 1) * 0.30
                + (1.2 if self.dist == "yes" else 0.5 if self.dist == "partially" else 0)
                + (random.gauss(0, 0.4) if noise else 0))
        self.risk = round(max(0.0, min(10.0, base)), 1)
        return self.risk

    def _loop(self):
        while self._on:
            try:
                eid, ans, _ = db_last_ema(self.pid)
                if ans:                       # only record readings once a survey exists
                    self.ema_id = eid
                    self.update_from_ema(ans)
                    self.spd = abs(random.gauss(1.3, 0.4))
                    self.mode = "walking" if self.spd < 2 else "cycling" if self.spd < 8 else "vehicle"
                    self.min += SENSOR_SECONDS / 60
                    r = self.compute()
                    db_save_risk(self.pid, r, tier(r)[0], self.fat, self.str_, self.fam,
                                 self.dist, self.cult, self.nm, eid)
            except Exception as ex:
                print("sensor error:", ex)
            time.sleep(SENSOR_SECONDS)

# ══ UI ATOMS ═══════════════════════════════════════════════════
def T(t, sz=14, col=None, bold=False, mono=False):
    return ft.Text(t, size=sz, color=col or C["txt"],
                   weight=ft.FontWeight.W_700 if bold else ft.FontWeight.W_400,
                   font_family="monospace" if mono else None)
def Dim(t, sz=12): return ft.Text(t, size=sz, color=C["dim"])
def Card(content, bc=None, p=14):
    return ft.Container(content=content, bgcolor=C["surf"], border_radius=12,
                        padding=pad_all(p), border=border_all(1, bc or C["bord"]))
def Badge(label, col):
    return ft.Container(content=ft.Text(label, size=10, weight=ft.FontWeight.W_700, color=col),
                        padding=pad(10, 10, 3, 3), border_radius=20,
                        bgcolor=col + "22", border=border_all(1, col + "55"))
def Btn(label, col, on_click, width=None):
    return ft.Button(label, bgcolor=col, color="#000000", width=width, on_click=on_click,
                     style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=10)))
def GhostBtn(label, on_click):
    return ft.OutlinedButton(label, on_click=on_click,
                             style=ft.ButtonStyle(color=C["dim"], side=ft.BorderSide(1, C["bord"])))
def toast(page, msg, col=None):
    page.show_dialog(ft.SnackBar(content=ft.Text(msg, color="#000"), bgcolor=col or C["pri"]))
def field(hint, val=""):
    return ft.TextField(hint_text=hint, value=val, bgcolor=C["surf2"], border_color=C["bord"],
                        focused_border_color=C["pri"], color=C["txt"],
                        hint_style=ft.TextStyle(color=C["dim"]), border_radius=8)
def drop(opts, val=None):
    return ft.Dropdown(value=val or None, options=[ft.dropdown.Option(o) for o in opts],
                       bgcolor=C["surf2"], border_color=C["bord"], focused_border_color=C["pri"],
                       color=C["txt"], border_radius=8)
def fcard(lbl, widget):
    return Card(ft.Column(spacing=8, controls=[T(lbl, sz=13, col=C["dim"], bold=True), widget]))
def ring(score_txt, col, label, sub="/ 10.0"):
    return ft.Stack(width=180, height=180, controls=[
        ft.Container(width=180, height=180, border_radius=90, border=border_all(6, col + "33")),
        ft.Container(width=148, height=148, border_radius=74, margin=mar_all(16),
                     bgcolor=col + "18", border=border_all(2.5, col),
                     content=ft.Column(alignment=ft.MainAxisAlignment.CENTER,
                                       horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=2,
                                       controls=[T(score_txt, sz=44, col=col, bold=True, mono=True),
                                                 Dim(sub), ft.Container(height=4), Badge(label, col)]))])
def bar(name, val, fc, maxv=1.0, shown=None):
    frac = max(0.0, min(1.0, val / maxv)) if maxv else 0
    return ft.Column(spacing=3, controls=[
        ft.Row(controls=[ft.Text(name, size=12, color=C["dim"], expand=True),
                         ft.Text(shown if shown is not None else f"{val:.1f}", size=12, color=fc,
                                 font_family="monospace")]),
        ft.Container(height=5, border_radius=3, bgcolor=C["surf2"],
                     content=ft.Container(width=max(4.0, 280.0 * frac), height=5, border_radius=3, bgcolor=fc))])

def slider_q(label, lo, hi, step_div, low_txt, high_txt, touched, store, key, fmt=lambda v: str(int(v)), col=None):
    """Slider that is NOT counted as answered until the participant moves it."""
    col = col or C["pri"]
    vt = ft.Text("◄ move the slider to answer ►" if key not in touched else fmt(store[key]),
                 size=22 if key in touched else 13, weight=ft.FontWeight.W_700,
                 color=col if key in touched else C["warn"], font_family="monospace")
    def ch(e):
        v = e.control.value
        store[key] = round(v, 1) if isinstance(step_div, float) else int(round(v))
        touched.add(key)
        vt.value = fmt(store[key]); vt.size = 22; vt.color = col
        vt.update()
    start = store.get(key, (lo + hi) / 2)
    return fcard(label, ft.Column(spacing=6, controls=[
        ft.Container(alignment=CENTER, content=vt),
        ft.Slider(min=lo, max=hi, value=float(start), divisions=int(step_div) if step_div else None,
                  active_color=col, inactive_color=col + "30", on_change=ch),
        ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[Dim(low_txt, 10), Dim(high_txt, 10)])]))

# ══ APP STATE (one per browser session) ════════════════════════
class A:
    def __init__(self, pid):
        self.pid = pid; self.S = Sensor(pid); self.alive = True
        self.fb_view = "home"; self.fb_w = {}; self.fb_touched = set()
        self.fb_s = {}; self.fb_s_touched = set(); self.fb_msg = ""; self.fb_result = None

# ══ EMA REMINDER ═══════════════════════════════════════════════
def show_ema_reminder(page, a, navigate):
    mins = db_minutes_since_ema(a.pid)
    if mins < 30: return
    def go(e): page.pop_dialog(); navigate("ema")
    def later(e): page.pop_dialog()
    page.show_dialog(ft.AlertDialog(
        modal=True, bgcolor=C["surf"],
        title=ft.Text("⏰  Survey due", size=18, weight=ft.FontWeight.W_700, color=C["warn"]),
        content=ft.Column(spacing=10, tight=True, controls=[
            ft.Text("Please complete your check-in survey.", size=14, color=C["txt"]),
            ft.Text(f"Last survey: {int(mins)} min ago" if mins < 9999 else "No survey completed yet",
                    size=12, color=C["warn"])]),
        actions=[ft.TextButton("Later", on_click=later, style=ft.ButtonStyle(color=C["dim"])),
                 ft.Button("Start now →", bgcolor=C["warn"], color="#000", on_click=go)],
        actions_alignment=ft.MainAxisAlignment.END))

# ══ SCREEN: DASHBOARD (RTI) ════════════════════════════════════
def dashboard(page, a, navigate):
    S = a.S; mins = db_minutes_since_ema(a.pid)
    now = datetime.now().strftime("%H:%M · %d %b %Y")
    ema_overdue = mins > 30
    ema_col = C["dang"] if ema_overdue else C["warn"]
    ema_msg = (f"⚠ Overdue! {int(mins)} min ago" if ema_overdue and mins < 9999 else
               f"Last: {int(mins)} min ago" if mins < 9999 else "No survey yet: start now!")
    survey_card = Card(ft.Row(controls=[
        ft.Text("📋", size=20), ft.Container(width=10),
        ft.Column(spacing=2, expand=True, controls=[T("Check-in survey", sz=13, bold=True),
                                                    ft.Text(ema_msg, size=11, color=ema_col)]),
        ft.Button("Start", bgcolor=ema_col, color="#000", on_click=lambda _: navigate("ema"))]),
        bc=ema_col + "44")
    head = ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[
        ft.Column(spacing=2, controls=[T("SafeRoute", sz=22, bold=True), Dim(f"{a.pid} · {now}")])])
    if S.risk is None:
        body = [head, Card(ft.Column(spacing=8, controls=[
            T("Welcome", sz=16, bold=True),
            Dim("Complete your first survey to get your road-risk score. "
                "Your score is based on your own answers plus time of day."),
        ])), survey_card]
    else:
        sc = S.risk; t, col = tier(sc)
        factors = [("Fatigue", S.fat / 10, C["dang"], f"{S.fat}/10"),
                   ("Stress", S.str_ / 100, C["warn"], f"{S.str_}/100"),
                   ("Unfamiliarity", 1 - (S.fam - 1) / 4, C["pri"], f"{S.fam}/5 familiar"),
                   ("Night", 1.0 if S.night else 0.05, "#7B68EE", "yes" if S.night else "no"),
                   ("Near-miss", 1.0 if S.nm else 0.05, C["crit"], "yes" if S.nm else "no")]
        nudge = {"HIGH": "⚠  Multiple risks. Slow down and stay alert.",
                 "CRITICAL": "🚨  Critical risk. Stop and find safety now."}
        sym = {"walking": "🚶", "cycling": "🚴", "vehicle": "🚗"}.get(S.mode, "🚶")
        body = [head, ft.Container(alignment=CENTER, content=ring(f"{sc:.1f}", col, t)),
                ft.Container(visible=t in nudge, padding=pad_all(14), border_radius=12,
                             bgcolor=col + "18", border=border_all(1.5, col + "66"),
                             content=ft.Text(nudge.get(t, ""), size=13, color=col)),
                Card(ft.Column(spacing=10, controls=[T("Risk factors (from your survey)", sz=13, col=C["dim"], bold=True),
                                                     *[bar(n, v, c, 1.0, s) for n, v, c, s in factors]])),
                Card(ft.Row(controls=[ft.Text(sym, size=22), ft.Container(width=10),
                                      ft.Column(spacing=2, expand=True, controls=[
                                          T("Session", sz=13, bold=True),
                                          Dim(f"{S.mode.capitalize()} · {S.min:.0f} min")]),
                                      ft.Container(width=8, height=8, border_radius=4, bgcolor=C["pri"])]),
                     bc=C["pri"] + "44"),
                survey_card]
    return ft.Container(expand=True, bgcolor=C["bg"], padding=pad_hv(18, 16),
                        content=ft.Column(scroll=ft.ScrollMode.AUTO, spacing=14, controls=body))

# ══ SCREEN: RTI SURVEY ═════════════════════════════════════════
def ema_screen(page, a, navigate):
    st = {"q": 0, "ans": {}}
    col_ref = ft.Column(expand=True, spacing=16)
    err = ft.Text("", size=12, color=C["dang"])
    col = C["pri"]

    def render():
        q = EMA[st["q"]]; idx = st["q"]; tot = len(EMA); pct = (idx + 1) / tot
        prog = ft.Column(spacing=4, controls=[
            ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                   controls=[Dim(f"Q {idx+1} of {tot}"), ft.Text(f"{int(pct*100)}%", size=12, color=col)]),
            ft.Container(height=3, border_radius=2, bgcolor=C["surf2"],
                         content=ft.Container(width=max(8.0, 340.0 * pct), height=3, border_radius=2, bgcolor=col))])
        pill = ft.Container(content=ft.Text(q["dom"], size=11, weight=ft.FontWeight.W_700, color=col),
                            padding=pad(12, 12, 4, 4), border_radius=20,
                            bgcolor=col + "20", border=border_all(1, col + "44"))
        if q["t"] == "slider":
            has = q["id"] in st["ans"]
            def lv(v):
                return f"{v}  ({'Calm' if v<20 else 'Mild' if v<40 else 'Moderate' if v<60 else 'High' if v<80 else 'Extreme'})" \
                    if q["id"] == "stress" else str(v)
            vd = ft.Text(lv(st["ans"][q["id"]]) if has else "◄ move the slider to answer ►",
                         size=28 if has else 13, weight=ft.FontWeight.W_700,
                         color=col if has else C["warn"], font_family="monospace")
            def onsl(e):
                v = int(e.control.value); st["ans"][q["id"]] = v
                vd.value = lv(v); vd.size = 28; vd.color = col; vd.update()
            resp = ft.Column(spacing=8, controls=[
                ft.Container(alignment=CENTER, content=vd),
                ft.Slider(min=0, max=q["max"], value=float(st["ans"].get(q["id"], q["max"] / 2)),
                          divisions=q["max"], active_color=col, inactive_color=col + "30", on_change=onsl),
                ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[Dim(q["lo"]), Dim(q["hi"])])])
        elif q["t"] == "lik":
            sel = st["ans"].get(q["id"]); opts = []
            for i, o in enumerate(q["o"]):
                s = sel == i
                def pick(e, i_=i, qid=q["id"]): st["ans"][qid] = i_; render()
                opts.append(ft.Container(
                    padding=pad_all(11), border_radius=10, bgcolor=col + "22" if s else C["surf2"],
                    border=border_all(1.5 if s else 1, col if s else C["bord"]), on_click=pick,
                    content=ft.Row(spacing=12, controls=[
                        ft.Container(width=18, height=18, border_radius=9, bgcolor=col if s else "transparent",
                                     border=border_all(1.5, col if s else C["bord"])),
                        ft.Text(o, size=13, color=C["txt"] if s else C["dim"])])))
            resp = ft.Column(spacing=7, controls=opts)
        else:
            sel = st["ans"].get(q["id"])
            def yes(e): st["ans"][q["id"]] = "yes"; render()
            def no(e): st["ans"][q["id"]] = "no"; render()
            resp = ft.Column(spacing=12, controls=[
                ft.Row(spacing=12, controls=[Btn("Yes: something happened", col if sel == "yes" else C["surf2"], yes),
                                             Btn("No", col if sel == "no" else C["surf2"], no)]),
                ft.Container(visible=sel == "yes", padding=pad_all(10), border_radius=8,
                             bgcolor=C["crit"] + "18", border=border_all(1, C["crit"] + "44"),
                             content=ft.Text("Near-miss recorded. Stay safe!", size=12, color=C["crit"]))])

        def back(e): st["q"] = max(0, st["q"] - 1); err.value = ""; render()
        def nxt(e):
            if st["q"] < tot - 1:
                st["q"] += 1; err.value = ""; render(); return
            missing = [r for r in EMA_REQUIRED if r not in st["ans"]]
            if missing:
                names = {x["id"]: x["dom"] for x in EMA}
                err.value = "Please answer: " + ", ".join(names[m] for m in missing); page.update(); return
            eid = db_save_ema(a.pid, st["ans"], "manual")
            a.S.update_from_ema(st["ans"]); a.S.compute(noise=False); a.S.ema_id = eid
            db_save_risk(a.pid, a.S.risk, tier(a.S.risk)[0], a.S.fat, a.S.str_, a.S.fam, a.S.dist, a.S.cult, a.S.nm, eid)
            a.S.start()
            toast(page, "✓ Survey saved. Risk score updated.")
            navigate("dashboard")
        col_ref.controls = [
            ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                   controls=[T("Check-in survey", sz=20, bold=True), Dim(datetime.now().strftime("%H:%M"))]),
            prog, ft.Container(height=4), pill, T(q["q"], sz=16, bold=True),
            ft.Container(expand=True, content=ft.Column(scroll=ft.ScrollMode.AUTO, controls=[resp])), err,
            ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[
                GhostBtn("← Back", back) if idx > 0 else ft.Container(),
                Btn("Submit ✓" if idx == tot - 1 else "Next →", col, nxt)])]
        page.update()
    render()
    return ft.Container(expand=True, bgcolor=C["bg"], padding=pad_hv(18, 20), content=col_ref)

# ══ SCREEN: FOOTBALL ═══════════════════════════════════════════
POSITIONS = ["Goalkeeper", "Defender", "Midfielder", "Forward"]
LEVELS = ["Recreational", "University team", "Semi-professional", "Professional"]
AREAS = ["Hamstring", "Quadriceps", "Groin", "Calf", "Ankle", "Knee", "Foot", "Hip",
         "Back", "Shoulder", "Head", "Other"]

def football_screen(page, a, navigate):
    fp = fb_load_profile(a.pid)
    def go(view): a.fb_view = view; a.fb_msg = ""; navigate("football")
    def head(title):
        return ft.Row(controls=[ft.IconButton(ft.Icons.ARROW_BACK, icon_color=C["dim"], on_click=lambda e: go("home")),
                                T(title, sz=20, bold=True)])
    wrap = lambda ctrls: ft.Container(expand=True, bgcolor=C["bg"], padding=pad_hv(18, 16),
                                      content=ft.Column(scroll=ft.ScrollMode.AUTO, spacing=12, controls=ctrls))
    err = ft.Text("", size=12, color=C["dang"])

    # ---- football profile
    if a.fb_view == "profile":
        f_age = field("e.g. 22", str(fp.get("age") or "")); f_pos = drop(POSITIONS, fp.get("position"))
        f_lvl = drop(LEVELS, fp.get("level")); f_prev = drop(["yes", "no"], fp.get("prev_injury"))
        f_wk = drop(["1-2", "3-4", "5+"], fp.get("weekly"))
        def save(e):
            if not (f_age.value and f_pos.value and f_prev.value):
                err.value = "Age, position and previous-injury answer are required."; page.update(); return
            try: age = int(f_age.value)
            except ValueError: err.value = "Age must be a number."; page.update(); return
            fb_save_profile(a.pid, {"age": age, "position": f_pos.value, "level": f_lvl.value or "",
                                    "prev_injury": f_prev.value, "weekly": f_wk.value or ""})
            toast(page, "Football profile saved ✓"); go("home")
        return wrap([head("Football profile"), fcard("Age", f_age), fcard("Position", f_pos),
                     fcard("Playing level", f_lvl),
                     fcard("Any injury that kept you out of play in the last 12 months?", f_prev),
                     fcard("Football sessions per week", f_wk), err,
                     ft.Button("Save", bgcolor=C["fb"], color="#000", on_click=save, width=float("inf"))])

    # ---- daily wellness check-in
    if a.fb_view == "checkin":
        w, tc = a.fb_w, a.fb_touched
        pain = drop(["no", "yes"], w.get("pain_now")); area = drop(AREAS, w.get("pain_area"))
        def submit(e):
            need = ["sleep_h", "sleep_q", "soreness", "fatigue", "stress", "mood"]
            miss = [k for k in need if k not in tc]
            if miss or not pain.value:
                err.value = "Please answer every question (move each slider, and choose pain yes/no)."
                page.update(); return
            if pain.value == "yes" and not area.value:
                err.value = "Choose where the pain is."; page.update(); return
            data = dict(w); data["pain_now"] = pain.value; data["pain_area"] = area.value or ""
            loads, first = fb_load_loads(a.pid)
            acwr = compute_acwr(loads, first)
            score, t, factors, adv = fb_assess(data, fp, acwr)
            fb_save_wellness(a.pid, data, acwr, score, t)
            a.fb_result = (score, t, factors, adv, acwr)
            a.fb_w = {}; a.fb_touched = set()
            toast(page, "✓ Check-in saved"); go("home")
        sq = lambda lbl, key, lo, hi: slider_q(lbl, 1, 5, 4, lo, hi, tc, w, key, col=C["fb"])
        return wrap([head("Daily check-in"),
                     slider_q("Hours slept last night", 3, 12, 18.0, "3 h", "12 h", tc, w, "sleep_h",
                              fmt=lambda v: f"{v:.1f} h", col=C["fb"]),
                     sq("Sleep quality", "sleep_q", "1 = Very poor", "5 = Excellent"),
                     sq("Muscle soreness today", "soreness", "1 = None", "5 = Very sore"),
                     sq("Fatigue / tiredness", "fatigue", "1 = Fresh", "5 = Exhausted"),
                     sq("Stress", "stress", "1 = Relaxed", "5 = Very stressed"),
                     sq("Mood", "mood", "1 = Very low", "5 = Great"),
                     fcard("Any pain or niggle right now?", pain),
                     fcard("Where? (if yes)", area), err,
                     ft.Button("Get my injury-risk score", bgcolor=C["fb"], color="#000", on_click=submit,
                               width=float("inf")), ft.Container(height=12)])

    # ---- log a session
    if a.fb_view == "session":
        s, tc = a.fb_s, a.fb_s_touched
        kind = drop(["Training", "Match", "Gym / conditioning"], s.get("kind"))
        def submit(e):
            if not kind.value or "minutes" not in tc or "rpe" not in tc:
                err.value = "Choose the session type and move both sliders."; page.update(); return
            fb_save_session(a.pid, kind.value, s["minutes"], s["rpe"])
            a.fb_s = {}; a.fb_s_touched = set()
            toast(page, "✓ Session logged")
            go("home")
        return wrap([head("Log a session"), fcard("Session type", kind),
                     slider_q("Duration (minutes)", 10, 150, 28, "10", "150", tc, s, "minutes",
                              fmt=lambda v: f"{int(v)} min", col=C["fb"]),
                     slider_q("How hard was it overall? (RPE)", 1, 10, 9, "1 = Very easy", "10 = Maximal",
                              tc, s, "rpe", col=C["fb"]),
                     Dim("Load = minutes × RPE. Log every session: this is what builds your load ratio."),
                     err, ft.Button("Save session", bgcolor=C["fb"], color="#000", on_click=submit, width=float("inf"))])

    # ---- report an injury (outcome data)
    if a.fb_view == "injury":
        d_area = drop(AREAS); d_ctx = drop(["During match", "During training", "Outside football"])
        d_sev = drop(["Minimal (1-3 days)", "Mild (4-7 days)", "Moderate (8-28 days)", "Severe (28+ days)"])
        d_days = field("Estimated days out of football (number)")
        def submit(e):
            if not (d_area.value and d_ctx.value and d_sev.value):
                err.value = "Please complete area, context and severity."; page.update(); return
            try: days = int(d_days.value or 0)
            except ValueError: err.value = "Days must be a number."; page.update(); return
            fb_save_injury(a.pid, d_area.value, d_ctx.value, d_sev.value, days)
            toast(page, "Injury recorded. Get well soon.", C["warn"]); go("home")
        return wrap([head("Report an injury"),
                     Dim("Only report injuries that stopped or limited you. This is the outcome data used to test the score."),
                     fcard("Body area", d_area), fcard("When did it happen?", d_ctx),
                     fcard("Severity", d_sev), fcard("Days out", d_days), err,
                     ft.Button("Save injury report", bgcolor=C["warn"], color="#000", on_click=submit, width=float("inf"))])

    # ---- home
    last = fb_last_wellness(a.pid)
    ctrls = [T("⚽ Football", sz=22, bold=True)]
    if not fp:
        ctrls += [Card(ft.Column(spacing=8, controls=[
            T("Set up your football profile", sz=15, bold=True),
            Dim("Age, position and injury history are used in your score."),
            Btn("Create profile", C["fb"], lambda e: go("profile"))]), bc=C["fb"] + "66")]
    if last:
        ts, score, t, acwr, *_ = last
        col = tier(score)[1]
        try: when = datetime.fromisoformat(ts).strftime("%d %b %H:%M")
        except Exception: when = ts[:16]
        ctrls += [ft.Container(alignment=CENTER, content=ring(f"{score:.1f}", col, t)),
                  Dim(f"Latest check-in: {when}")]
        if a.fb_result:
            sc, tt, factors, adv, ac = a.fb_result
            ctrls += [Card(ft.Column(spacing=10, controls=[
                T("What is driving your score", sz=13, col=C["dim"], bold=True),
                *[bar(n, p, C["fb"] if p < m * 0.5 else C["warn"] if p < m * 0.8 else C["dang"], m, f"{p:.1f}/{m:g}")
                  for n, p, m in factors]])),
                Card(ft.Column(spacing=6, controls=[T("Advice", sz=13, col=C["dim"], bold=True),
                                                    *[ft.Text("• " + x, size=13, color=C["txt"]) for x in adv]]))]
        ctrls += [Dim("ACWR (7-day load ÷ 28-day weekly average): "
                      + (f"{acwr}" if acwr is not None else "building baseline (needs 14+ days of logged sessions)"))]
    else:
        ctrls += [Card(ft.Column(spacing=6, controls=[
            T("No check-in yet", sz=15, bold=True),
            Dim("Do the daily check-in to get your injury-risk score.")]))]
    ctrls += [Btn("Daily check-in", C["fb"], lambda e: go("checkin"), width=float("inf")),
              Btn("Log a training / match session", C["pri"], lambda e: go("session"), width=float("inf")),
              Btn("Report an injury", C["warn"], lambda e: go("injury"), width=float("inf")),
              GhostBtn("Edit football profile", lambda e: go("profile")),
              Dim("This is a research screening tool, not medical advice. Seek a physio or doctor for pain or injury."),
              ft.Container(height=12)]
    return wrap(ctrls)

# ══ SCREEN: HISTORY ════════════════════════════════════════════
def history(page, a, navigate):
    rows = db_history(a.pid); n1, n2, av = db_stats(a.pid); _, ac = tier(av)
    def sc(val, lbl, col):
        return Card(ft.Column(spacing=2, horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                              controls=[T(str(val), sz=26, col=col, bold=True, mono=True), Dim(lbl)]), p=12)
    body = []
    if not rows:
        body = [ft.Container(height=120, alignment=CENTER, content=Dim("No road-risk data yet: complete a survey.", 14))]
    for ts, score, t in rows:
        col = tier(score)[1]
        try: ds = datetime.fromisoformat(ts).strftime("%d %b  %H:%M:%S")
        except Exception: ds = ts[:16]
        body.append(ft.Container(padding=pad(14, 14, 10, 10), border_radius=8, bgcolor=C["surf2"],
            content=ft.Row(controls=[ft.Container(width=4, height=36, border_radius=2, bgcolor=col), ft.Container(width=10),
                ft.Column(spacing=2, expand=True, controls=[ft.Text(ds, size=12, color=C["txt"]),
                                                            ft.Text(t, size=11, color=col, weight=ft.FontWeight.W_600)]),
                T(f"{score:.1f}", sz=22, col=col, bold=True, mono=True)])))
    fbrows = q_all("SELECT ts,score,tier FROM fb_wellness WHERE pid=? ORDER BY id DESC LIMIT 15", (a.pid,))
    fbl = []
    for ts, score, t in fbrows:
        col = tier(score)[1]
        try: ds = datetime.fromisoformat(ts).strftime("%d %b  %H:%M")
        except Exception: ds = ts[:16]
        fbl.append(ft.Container(padding=pad(14, 14, 10, 10), border_radius=8, bgcolor=C["surf2"],
            content=ft.Row(controls=[ft.Container(width=4, height=30, border_radius=2, bgcolor=col), ft.Container(width=10),
                ft.Column(spacing=2, expand=True, controls=[ft.Text(ds, size=12, color=C["txt"]),
                                                            ft.Text(t, size=11, color=col)]),
                T(f"{score:.1f}", sz=20, col=col, bold=True, mono=True)])))
    return ft.Container(expand=True, bgcolor=C["bg"], padding=pad_hv(18, 16),
        content=ft.Column(scroll=ft.ScrollMode.AUTO, spacing=14, controls=[
            T("History", sz=22, bold=True),
            ft.Row(spacing=10, controls=[sc(n1, "Surveys", C["pri"]), sc(n2, "Readings", C["warn"]), sc(av, "Avg", ac)]),
            T("⚽ Football check-ins", sz=13, col=C["dim"], bold=True),
            ft.Column(spacing=8, controls=fbl or [Dim("No football check-ins yet.", 13)]),
            T("Road readings", sz=13, col=C["dim"], bold=True),
            ft.Column(spacing=8, controls=body)]))

# ══ EXCEL EXPORT ═══════════════════════════════════════════════
def build_export():
    import openpyxl
    from openpyxl.styles import PatternFill, Font
    ASSETS.mkdir(exist_ok=True)
    for old in glob.glob(str(ASSETS / "export_*.xlsx")):
        try: os.remove(old)
        except Exception: pass
    wb = openpyxl.Workbook(); wb.remove(wb.active)
    c = conn_()
    for tbl in SCHEMA:
        cur = c.execute(f"SELECT * FROM {tbl} ORDER BY id")
        cols = [d[0] for d in cur.description]; rows = cur.fetchall()
        if tbl == "ema":                       # flatten the answers JSON into columns
            keys = [x["id"] for x in EMA]; cols = [x for x in cols if x != "ans"] + keys
            ai = [d[0] for d in cur.description].index("ans"); new = []
            for r in rows:
                try: ans = json.loads(r[ai])
                except Exception: ans = {}
                new.append([v for i, v in enumerate(r) if i != ai] + [ans.get(k, "") for k in keys])
            rows = new
        ws = wb.create_sheet(tbl); ws.append(cols)
        for cell in ws[1]:
            cell.font = Font(bold=True); cell.fill = PatternFill("solid", fgColor="00D4AA")
        for r in rows: ws.append(list(r))
        for col in ws.columns:
            ws.column_dimensions[col[0].column_letter].width = min(max(len(str(x.value or "")) for x in col) + 3, 40)
    ws = wb.create_sheet("summary", 0)
    ws.append(["table", "rows"])
    for tbl in SCHEMA: ws.append([tbl, c.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]])
    ws.append([]); ws.append(["exported", datetime.now().strftime("%Y-%m-%d %H:%M:%S")])
    c.close()
    name = f"export_{uuid.uuid4().hex[:12]}.xlsx"
    wb.save(ASSETS / name)
    return name

# ══ SCREEN: PROFILE ════════════════════════════════════════════
def profile(page, a, navigate):
    ex = db_load_profile(a.pid)
    f_name = field("e.g. Kwame Mensah", ex.get("name", "")); f_country = field("e.g. Nigeria", ex.get("country", ""))
    f_uni = field("e.g. Central South Univ.", ex.get("university", "")); f_years = field("e.g. 2.5", ex.get("years", ""))
    f_level = drop(["Undergraduate", "Masters", "PhD", "Postdoc"], ex.get("level"))
    f_trans = drop(["Walking", "Cycling", "Bus", "E-scooter", "Car"], ex.get("transport"))
    f_house = drop(["On-campus", "Off-campus"], ex.get("housing"))
    status = ft.Text("", size=13, color=C["pri"])
    def saved(e):
        if not f_name.value or not f_country.value:
            status.value = "Name and Country are required."; status.color = C["dang"]; page.update(); return
        db_save_profile(a.pid, {"name": f_name.value, "country": f_country.value, "university": f_uni.value,
                                "years": f_years.value, "level": f_level.value or "",
                                "transport": f_trans.value or "", "housing": f_house.value or ""})
        status.value = "✓ Profile saved"; status.color = C["pri"]; toast(page, "Profile saved ✓"); page.update()
    admin_box = []
    if ADMIN_KEY:
        key = ft.TextField(hint_text="Researcher key", password=True, can_reveal_password=True,
                           bgcolor=C["surf2"], border_color=C["bord"], color=C["txt"], border_radius=8)
        msg = ft.Text("", size=12, color=C["dang"])
        def exp(e):
            if key.value != ADMIN_KEY: msg.value = "Wrong key."; page.update(); return
            try:
                name = build_export(); msg.value = "Export ready, downloading…"; msg.color = C["pri"]; page.update()
                page.launch_url("/" + name)
            except Exception as ex_:
                msg.value = f"Export failed: {ex_}"; page.update()
        admin_box = [ft.Container(height=8), Card(ft.Column(spacing=8, controls=[
            T("Researcher export", sz=13, col=C["dim"], bold=True), key,
            ft.Button("Download all data (Excel)", bgcolor=C["warn"], color="#000", on_click=exp), msg]))]
    def switch(e):
        a.S.stop(); a.alive = False
        page.controls.clear(); page.navigation_bar = None; show_login(page)
    return ft.Container(expand=True, bgcolor=C["bg"], padding=pad_hv(18, 16),
        content=ft.Column(scroll=ft.ScrollMode.AUTO, spacing=12, controls=[
            T("Profile", sz=22, bold=True), Dim(f"Participant code: {a.pid}"),
            fcard("Full name", f_name), fcard("Country of origin", f_country), fcard("University", f_uni),
            fcard("Years in China", f_years), fcard("Academic level", f_level),
            fcard("Primary transport", f_trans), fcard("Housing", f_house), status,
            ft.Button("Save profile", bgcolor=C["pri"], color="#000", width=float("inf"), on_click=saved),
            GhostBtn("Switch participant / log out", switch), *admin_box, ft.Container(height=16)]))

# ══ LOGIN + MAIN ═══════════════════════════════════════════════
def show_login(page):
    code = field("Your participant code (e.g. your initials + birth year)")
    err = ft.Text("", size=12, color=C["dang"])
    def go(e):
        pid = (code.value or "").strip().lower().replace(" ", "")
        if len(pid) < 3:
            err.value = "Please enter at least 3 characters."; page.update(); return
        page.controls.clear(); start_app(page, pid)
    page.add(ft.Container(expand=True, bgcolor=C["bg"], padding=pad_all(24), alignment=CENTER,
        content=ft.Column(alignment=ft.MainAxisAlignment.CENTER, spacing=16, controls=[
            T("SafeRoute", sz=32, bold=True), Dim("Road-safety & football injury-risk study", 14),
            Card(ft.Column(spacing=10, controls=[
                T("Enter your participant code", sz=15, bold=True),
                Dim("Use the SAME code every time so your data stays together. Do not use your real name."),
                code, err, Btn("Continue →", C["pri"], go, width=float("inf"))])),
            Dim("By continuing you agree to take part in this research. Data are used for the study only.", 11)])))
    page.update()

def start_app(page, pid):
    a = A(pid)
    content = ft.Container(expand=True)
    nav_ref = ft.Ref[ft.NavigationBar]()
    names = ["dashboard", "ema", "football", "history", "profile"]
    builders = [dashboard, ema_screen, football_screen, history, profile]

    def navigate(screen):
        idx = names.index(screen) if screen in names else 0
        content.content = builders[idx](page, a, navigate)
        if nav_ref.current: nav_ref.current.selected_index = idx
        page.update()
    def on_nav(e):
        if names[e.control.selected_index] == "football": a.fb_view = "home"
        navigate(names[e.control.selected_index])

    def refresh():
        while a.alive:
            time.sleep(10)
            try:
                if nav_ref.current and nav_ref.current.selected_index == 0:
                    content.content = dashboard(page, a, navigate); page.update()
            except Exception: pass
    def reminder():
        time.sleep(120)
        while a.alive:
            try:
                if a.S.risk is not None: show_ema_reminder(page, a, navigate)
            except Exception: pass
            time.sleep(1800)

    def on_disc(e): a.alive = False; a.S.stop()
    page.on_disconnect = on_disc

    _, ans, _ = db_last_ema(pid)
    if ans:
        a.S.update_from_ema(ans); a.S.compute(noise=False); a.S.start()
    threading.Thread(target=refresh, daemon=True).start()
    threading.Thread(target=reminder, daemon=True).start()

    page.add(ft.Column(expand=True, spacing=0, controls=[
        content,
        ft.NavigationBar(ref=nav_ref, bgcolor=C["surf"], indicator_color=C["pri"] + "22",
                         selected_index=0, on_change=on_nav,
                         destinations=[
                             ft.NavigationBarDestination(icon=ft.Icons.HOME, label="Home"),
                             ft.NavigationBarDestination(icon=ft.Icons.EDIT, label="Survey"),
                             ft.NavigationBarDestination(icon=ft.Icons.SPORTS_SOCCER, label="Football"),
                             ft.NavigationBarDestination(icon=ft.Icons.BAR_CHART, label="History"),
                             ft.NavigationBarDestination(icon=ft.Icons.PERSON, label="Profile")])]))
    navigate("dashboard")

def main(page: ft.Page):
    init_db()
    page.title = "SafeRoute"; page.theme_mode = ft.ThemeMode.DARK
    page.bgcolor = C["bg"]; page.padding = 0
    show_login(page)

if __name__ == "__main__":
    PORT = int(os.environ.get("PORT", 8000))
    ASSETS.mkdir(exist_ok=True)
    ft.run(main, view=ft.AppView.WEB_BROWSER, port=PORT, host="0.0.0.0", assets_dir=str(ASSETS))