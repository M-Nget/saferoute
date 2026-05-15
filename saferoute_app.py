"""
SafeRoute — RTI Risk Prediction App
Single-file, self-contained. Run with: python saferoute_app.py
"""

import flet as ft
import threading
import time
import math
import random
import sqlite3
import json
from datetime import datetime, timezone
from pathlib import Path

# ══════════════════════════════════════════════════════════════════
# CONSTANTS & THEME
# ══════════════════════════════════════════════════════════════════

DB_PATH = Path("saferoute.db")

COLORS = {
    "bg":        "#0D1117",
    "surface":   "#161B22",
    "surface2":  "#21262D",
    "border":    "#30363D",
    "primary":   "#00D4AA",
    "warning":   "#F4A261",
    "danger":    "#E76F51",
    "critical":  "#C1121F",
    "text":      "#E6EDF3",
    "text_dim":  "#7D8590",
}

RISK_TIERS = [
    (0.0, 3.0,  "LOW",      "#00D4AA"),
    (3.0, 6.0,  "MODERATE", "#F4A261"),
    (6.0, 8.0,  "HIGH",     "#E76F51"),
    (8.0, 10.1, "CRITICAL", "#C1121F"),
]

def get_tier(score):
    for lo, hi, label, color in RISK_TIERS:
        if lo <= score < hi:
            return label, color
    return "LOW", "#00D4AA"

EMA_QUESTIONS = [
    {"id": "fatigue",   "domain": "Fatigue",         "text": "How tired are you right now?",                    "type": "slider", "max": 10},
    {"id": "stress",    "domain": "Stress",           "text": "Rate your current stress level.",                 "type": "slider", "max": 100},
    {"id": "safety",    "domain": "Perceived Safety", "text": "How safe do you feel right now?",                 "type": "likert", "opts": ["Very unsafe","Unsafe","Neutral","Safe","Very safe"]},
    {"id": "distract",  "domain": "Distraction",      "text": "Were you using your phone while walking?",        "type": "choice", "opts": ["Yes","Partially","No"]},
    {"id": "familiar",  "domain": "Familiarity",      "text": "How familiar are you with this area?",            "type": "likert", "opts": ["Not at all","Slightly","Somewhat","Mostly","Very well"]},
    {"id": "nearmiss",  "domain": "Near-miss",        "text": "Did anything almost happen just now?",            "type": "yesno"},
    {"id": "cultural",  "domain": "Cultural",         "text": "Do local traffic norms confuse you right now?",   "type": "likert", "opts": ["Not at all","Slightly","Somewhat","Quite","Very much"]},
    {"id": "academic",  "domain": "Academic stress",  "text": "How stressed are you about your studies today?",  "type": "likert", "opts": ["None","Low","Moderate","High","Extreme"]},
]

# ══════════════════════════════════════════════════════════════════
# DATABASE
# ══════════════════════════════════════════════════════════════════

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS ema_responses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT, answers TEXT
        );
        CREATE TABLE IF NOT EXISTS risk_scores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT, score REAL, tier TEXT,
            fatigue INTEGER, stress INTEGER
        );
        CREATE TABLE IF NOT EXISTS gps_points (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT, lat REAL, lng REAL, speed REAL, mode TEXT
        );
    """)
    conn.commit()
    conn.close()

def save_ema(answers: dict):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("INSERT INTO ema_responses (timestamp, answers) VALUES (?,?)",
                 (datetime.now().isoformat(), json.dumps(answers)))
    conn.commit(); conn.close()

def save_risk(score, tier, fatigue=0, stress=0):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("INSERT INTO risk_scores (timestamp,score,tier,fatigue,stress) VALUES (?,?,?,?,?)",
                 (datetime.now().isoformat(), score, tier, fatigue, stress))
    conn.commit(); conn.close()

def get_risk_history(limit=20):
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("SELECT timestamp,score,tier FROM risk_scores ORDER BY id DESC LIMIT ?",
                        (limit,)).fetchall()
    conn.close()
    return rows

def get_stats():
    conn = sqlite3.connect(DB_PATH)
    n_ema  = conn.execute("SELECT COUNT(*) FROM ema_responses").fetchone()[0]
    n_risk = conn.execute("SELECT COUNT(*) FROM risk_scores").fetchone()[0]
    avg    = conn.execute("SELECT AVG(score) FROM risk_scores").fetchone()[0]
    conn.close()
    return n_ema, n_risk, round(avg or 0, 1)

# ══════════════════════════════════════════════════════════════════
# SIMULATED SENSORS (replace with real platform APIs)
# ══════════════════════════════════════════════════════════════════

class SensorEngine:
    """Simulates GPS + accelerometer + risk scoring in background thread."""
    def __init__(self):
        self.lat       = 28.1826
        self.lng       = 112.9346
        self.speed     = 1.2
        self.mode      = "walking"
        self.risk      = 2.1
        self.fatigue   = 3
        self.stress    = 25
        self.raining   = False
        self.night     = False
        self.familiar  = 4
        self.trip_min  = 0
        self._running  = False
        self._callbacks = []

    def start(self):
        self._running = True
        threading.Thread(target=self._loop, daemon=True).start()

    def stop(self):
        self._running = False

    def add_callback(self, fn):
        self._callbacks.append(fn)

    def _loop(self):
        while self._running:
            # Drift position
            self.lat  += random.uniform(-0.0001, 0.0001)
            self.lng  += random.uniform(-0.0001, 0.0001)
            self.speed = abs(random.gauss(1.3, 0.4))
            self.mode  = "walking" if self.speed < 2 else "cycling" if self.speed < 8 else "vehicle"
            self.trip_min += 5/60

            # Recompute risk score
            base = (
                self.fatigue * 0.30 +
                self.stress / 100 * 2.0 +
                (6 - self.familiar) * 0.40 +
                (1.5 if self.night else 0) +
                (1.0 if self.raining else 0) +
                random.gauss(0, 0.3)
            )
            self.risk = round(max(0, min(10, base)), 1)
            tier, _ = get_tier(self.risk)
            save_risk(self.risk, tier, self.fatigue, self.stress)

            for fn in self._callbacks:
                try: fn()
                except: pass
            time.sleep(5)

sensor = SensorEngine()

# ══════════════════════════════════════════════════════════════════
# UI HELPERS
# ══════════════════════════════════════════════════════════════════

def card(content, padding=16, border_color=None):
    return ft.Container(
        content=content,
        bgcolor=COLORS["surface"],
        border_radius=12,
        padding=padding,
        border=ft.border.all(1, border_color or COLORS["border"]),
    )

def label(text, size=11, color=None, bold=False):
    return ft.Text(text, size=size, color=color or COLORS["text_dim"],
                   weight=ft.FontWeight.W_600 if bold else ft.FontWeight.W_400)

def heading(text, size=16):
    return ft.Text(text, size=size, weight=ft.FontWeight.W_700, color=COLORS["text"])

def tier_badge(tier, color):
    return ft.Container(
        content=ft.Text(tier, size=10, weight=ft.FontWeight.W_700, color=color),
        padding=ft.padding.symmetric(horizontal=10, vertical=3),
        border_radius=20,
        bgcolor=color + "22",
        border=ft.border.all(1, color + "55"),
    )

# ══════════════════════════════════════════════════════════════════
# SCREEN 1: DASHBOARD
# ══════════════════════════════════════════════════════════════════

def build_dashboard(page: ft.Page, navigate):
    score  = sensor.risk
    tier, color = get_tier(score)
    now    = datetime.now().strftime("%H:%M · %d %b %Y")

    # ── Risk ring ─────────────────────────────────────────────────
    ring = ft.Stack(width=180, height=180, controls=[
        ft.Container(width=180, height=180, border_radius=90,
                     border=ft.border.all(6, color + "33")),
        ft.Container(
            width=148, height=148, border_radius=74,
            margin=ft.margin.all(16),
            bgcolor=color + "18",
            border=ft.border.all(2.5, color),
            content=ft.Column(
                alignment=ft.MainAxisAlignment.CENTER,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=0,
                controls=[
                    ft.Text(f"{score:.1f}", size=44, weight=ft.FontWeight.W_700,
                            color=color, font_family="monospace"),
                    ft.Text("/ 10.0", size=11, color=COLORS["text_dim"]),
                    ft.Container(height=4),
                    tier_badge(tier, color),
                ],
            ),
        ),
    ])

    # ── Factor bars ───────────────────────────────────────────────
    factors = [
        ("Fatigue",     sensor.fatigue / 10, COLORS["danger"]),
        ("Stress",      sensor.stress / 100,  COLORS["warning"]),
        ("Familiarity", 1 - (sensor.familiar - 1) / 4, COLORS["primary"]),
        ("Nighttime",   1.0 if sensor.night else 0.1, "#7B68EE"),
        ("Rain",        1.0 if sensor.raining else 0.1, "#4A9EFF"),
    ]

    def factor_row(name, val, c):
        return ft.Column(spacing=4, controls=[
            ft.Row(controls=[
                ft.Text(name, size=12, color=COLORS["text_dim"], expand=True),
                ft.Text(f"{val*10:.1f}", size=12, color=c, font_family="monospace"),
            ]),
            ft.Container(
                height=5, border_radius=3, bgcolor=COLORS["surface2"],
                content=ft.Container(
                    width=200 * val, height=5, border_radius=3, bgcolor=c,
                ),
            ),
        ])

    # ── Trip card ─────────────────────────────────────────────────
    mode_icon = {"walking": ft.icons.DIRECTIONS_WALK,
                 "cycling": ft.icons.DIRECTIONS_BIKE,
                 "vehicle": ft.icons.DIRECTIONS_CAR}.get(sensor.mode, ft.icons.DIRECTIONS_WALK)

    trip_card = card(ft.Row(controls=[
        ft.Icon(mode_icon, color=COLORS["primary"], size=22),
        ft.Column(spacing=2, expand=True, controls=[
            ft.Text("Trip in progress", size=13, weight=ft.FontWeight.W_600, color=COLORS["text"]),
            ft.Text(f"{sensor.mode.capitalize()} · {sensor.trip_min:.0f} min · {sensor.speed:.1f} m/s",
                    size=11, color=COLORS["text_dim"]),
        ]),
        ft.Container(width=8, height=8, border_radius=4, bgcolor=COLORS["primary"]),
    ]), border_color=COLORS["primary"] + "44")

    # ── Nudge banner ──────────────────────────────────────────────
    nudge_msgs = {
        "HIGH":     "⚠  Multiple risks detected. Slow down and stay alert.",
        "CRITICAL": "🚨  Critical risk. Stop, find a safe place, and wait.",
    }
    nudge = ft.Container(
        visible=tier in nudge_msgs,
        padding=ft.padding.all(14),
        border_radius=12,
        bgcolor=color + "18",
        border=ft.border.all(1.5, color + "66"),
        content=ft.Text(nudge_msgs.get(tier, ""), size=13, color=color),
    )

    return ft.Container(
        expand=True,
        bgcolor=COLORS["bg"],
        padding=ft.padding.symmetric(horizontal=18, vertical=16),
        content=ft.Column(
            scroll=ft.ScrollMode.AUTO,
            spacing=14,
            controls=[
                ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[
                    ft.Column(spacing=2, controls=[
                        heading("SafeRoute", 22),
                        label(now),
                    ]),
                    ft.IconButton(ft.icons.NOTIFICATIONS_NONE,
                                  icon_color=COLORS["text_dim"]),
                ]),
                ft.Container(alignment=ft.alignment.center, content=ring),
                nudge,
                card(ft.Column(spacing=10, controls=[
                    label("Active risk factors", bold=True),
                    *[factor_row(n, v, c) for n, v, c in factors],
                ])),
                trip_card,
                card(ft.Row(controls=[
                    ft.Icon(ft.icons.ASSIGNMENT_OUTLINED, color=COLORS["warning"], size=20),
                    ft.Column(spacing=1, expand=True, controls=[
                        ft.Text("EMA Survey available", size=13,
                                weight=ft.FontWeight.W_600, color=COLORS["text"]),
                        label("Tap to complete your next survey"),
                    ]),
                    ft.TextButton("Start →",
                                  on_click=lambda _: navigate("ema"),
                                  style=ft.ButtonStyle(color=COLORS["warning"])),
                ])),
            ],
        ),
    )

# ══════════════════════════════════════════════════════════════════
# SCREEN 2: EMA SURVEY
# ══════════════════════════════════════════════════════════════════

def build_ema(page: ft.Page, navigate):
    state = {"q": 0, "answers": {}, "slider_val": 5}

    def render():
        q   = EMA_QUESTIONS[state["q"]]
        idx = state["q"]
        tot = len(EMA_QUESTIONS)
        color = COLORS["primary"]

        # Progress
        pct = (idx + 1) / tot
        progress = ft.Column(spacing=4, controls=[
            ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[
                label(f"Question {idx+1} of {tot}"),
                label(f"{int(pct*100)}%", color=color),
            ]),
            ft.Container(height=3, border_radius=2, bgcolor=COLORS["surface2"],
                         content=ft.Container(
                             width=330 * pct, height=3, border_radius=2, bgcolor=color)),
        ])

        domain_badge = ft.Container(
            padding=ft.padding.symmetric(horizontal=12, vertical=4),
            border_radius=20, bgcolor=color + "20",
            border=ft.border.all(1, color + "44"),
            content=label(q["domain"], color=color, bold=True),
        )

        qtext = ft.Text(q["text"], size=19, weight=ft.FontWeight.W_600,
                        color=COLORS["text"])

        # Build response widget
        if q["type"] == "slider":
            val_text = ft.Text(str(state["slider_val"]), size=34,
                               weight=ft.FontWeight.W_700, color=color,
                               font_family="monospace")
            def on_slide(e):
                state["slider_val"] = int(e.control.value)
                state["answers"][q["id"]] = state["slider_val"]
                val_text.value = str(state["slider_val"])
                page.update()

            response = ft.Column(spacing=12, controls=[
                ft.Container(alignment=ft.alignment.center, content=val_text),
                ft.Slider(min=0, max=q["max"], value=state["slider_val"],
                          active_color=color, inactive_color=color + "30",
                          on_change=on_slide),
                ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[
                    label("0"), label(str(q["max"])),
                ]),
            ])

        elif q["type"] in ("likert", "choice"):
            sel = state["answers"].get(q["id"])
            opts = []
            for i, opt in enumerate(q["opts"]):
                is_sel = sel == i
                def on_pick(e, idx_=i, qid=q["id"]):
                    state["answers"][qid] = idx_
                    page.update()
                opts.append(ft.Container(
                    padding=ft.padding.all(13),
                    border_radius=10,
                    bgcolor=color + "22" if is_sel else COLORS["surface2"],
                    border=ft.border.all(1.5 if is_sel else 1,
                                         color if is_sel else COLORS["border"]),
                    on_click=on_pick,
                    content=ft.Row(spacing=12, controls=[
                        ft.Container(width=18, height=18, border_radius=9,
                                     bgcolor=color if is_sel else "transparent",
                                     border=ft.border.all(1.5, color if is_sel
                                                          else COLORS["border"])),
                        ft.Text(opt, size=14,
                                color=COLORS["text"] if is_sel else COLORS["text_dim"]),
                    ]),
                ))
            response = ft.Column(spacing=8, controls=opts)

        elif q["type"] == "yesno":
            sel = state["answers"].get(q["id"])
            def pick_yes(e): state["answers"][q["id"]] = "yes"; page.update()
            def pick_no(e):  state["answers"][q["id"]] = "no";  page.update()
            response = ft.Row(spacing=12, controls=[
                ft.ElevatedButton("Yes", bgcolor=color if sel=="yes" else COLORS["surface2"],
                                  color="#000" if sel=="yes" else COLORS["text_dim"],
                                  on_click=pick_yes,
                                  style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=10))),
                ft.ElevatedButton("No",  bgcolor=color if sel=="no"  else COLORS["surface2"],
                                  color="#000" if sel=="no"  else COLORS["text_dim"],
                                  on_click=pick_no,
                                  style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=10))),
            ])
        else:
            response = ft.Text("N/A", color=COLORS["text_dim"])

        # Nav buttons
        def go_back(e):
            state["q"] = max(0, state["q"] - 1)
            state["slider_val"] = 5
            page.update()

        def go_next(e):
            if state["q"] < len(EMA_QUESTIONS) - 1:
                state["q"] += 1
                state["slider_val"] = 5
                page.update()
            else:
                save_ema(state["answers"])
                page.snack_bar = ft.SnackBar(
                    content=ft.Text("Survey submitted ✓", color="#000"),
                    bgcolor=COLORS["primary"])
                page.snack_bar.open = True
                state["q"] = 0
                state["answers"] = {}
                state["slider_val"] = 5
                navigate("dashboard")

        nav = ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[
            ft.OutlinedButton("← Back", visible=idx > 0, on_click=go_back,
                              style=ft.ButtonStyle(color=COLORS["text_dim"],
                                                   side=ft.BorderSide(1, COLORS["border"]))),
            ft.ElevatedButton(
                "Submit ✓" if idx == tot - 1 else "Next →",
                bgcolor=color, color="#000",
                on_click=go_next,
                style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=10))),
        ])

        main_col.controls = [
            ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[
                heading("EMA Survey", 20),
                label(datetime.now().strftime("%H:%M")),
            ]),
            progress,
            ft.Container(height=6),
            domain_badge,
            qtext,
            ft.Container(expand=True, content=response),
            nav,
        ]
        page.update()

    main_col = ft.Column(expand=True, spacing=18)
    render()

    return ft.Container(
        expand=True,
        bgcolor=COLORS["bg"],
        padding=ft.padding.symmetric(horizontal=18, vertical=20),
        content=main_col,
    )

# ══════════════════════════════════════════════════════════════════
# SCREEN 3: HISTORY
# ══════════════════════════════════════════════════════════════════

def build_history(page: ft.Page, navigate):
    rows = get_risk_history(30)
    n_ema, n_risk, avg_score = get_stats()
    _, avg_color = get_tier(avg_score)

    stat_cards = ft.Row(spacing=10, controls=[
        card(ft.Column(spacing=2, horizontal_alignment=ft.CrossAxisAlignment.CENTER, controls=[
            ft.Text(str(n_ema), size=28, weight=ft.FontWeight.W_700, color=COLORS["primary"]),
            label("EMA surveys"),
        ]), padding=12),
        card(ft.Column(spacing=2, horizontal_alignment=ft.CrossAxisAlignment.CENTER, controls=[
            ft.Text(str(n_risk), size=28, weight=ft.FontWeight.W_700, color=COLORS["warning"]),
            label("Risk readings"),
        ]), padding=12),
        card(ft.Column(spacing=2, horizontal_alignment=ft.CrossAxisAlignment.CENTER, controls=[
            ft.Text(f"{avg_score}", size=28, weight=ft.FontWeight.W_700, color=avg_color),
            label("Avg risk score"),
        ]), padding=12),
    ])

    if not rows:
        history_list = ft.Container(
            alignment=ft.alignment.center,
            height=200,
            content=ft.Column(
                alignment=ft.MainAxisAlignment.CENTER,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    ft.Icon(ft.icons.HISTORY, color=COLORS["text_dim"], size=40),
                    ft.Container(height=8),
                    label("No history yet. Start the app to collect data."),
                ],
            ),
        )
    else:
        items = []
        for ts, score, tier in rows:
            _, c = get_tier(score)
            try:
                dt = datetime.fromisoformat(ts)
                ts_str = dt.strftime("%d %b %H:%M")
            except:
                ts_str = ts[:16]
            items.append(ft.Container(
                padding=ft.padding.symmetric(horizontal=14, vertical=10),
                border_radius=8,
                bgcolor=COLORS["surface2"],
                content=ft.Row(controls=[
                    ft.Container(width=4, height=36, border_radius=2, bgcolor=c),
                    ft.Container(width=10),
                    ft.Column(spacing=2, expand=True, controls=[
                        ft.Text(ts_str, size=12, color=COLORS["text"]),
                        label(tier, color=c),
                    ]),
                    ft.Text(f"{score:.1f}", size=22, weight=ft.FontWeight.W_700,
                            color=c, font_family="monospace"),
                ]),
            ))
        history_list = ft.Column(spacing=8, controls=items)

    return ft.Container(
        expand=True,
        bgcolor=COLORS["bg"],
        padding=ft.padding.symmetric(horizontal=18, vertical=16),
        content=ft.Column(
            scroll=ft.ScrollMode.AUTO,
            spacing=16,
            controls=[
                heading("History", 22),
                stat_cards,
                label("Recent risk readings", bold=True),
                history_list,
            ],
        ),
    )

# ══════════════════════════════════════════════════════════════════
# SCREEN 4: PROFILE
# ══════════════════════════════════════════════════════════════════

def build_profile(page: ft.Page, navigate):
    fields = [
        ("Name",              "e.g. Kwame Mensah",      False),
        ("Country of origin", "e.g. Nigeria",            False),
        ("University",        "e.g. Central South Univ.","False"),
        ("Years in China",    "e.g. 2.5",               False),
    ]
    dropdowns = [
        ("Academic level",   ["Undergraduate","Masters","PhD","Postdoc"]),
        ("Transport mode",   ["Walking","Cycling","Bus","E-scooter","Car"]),
        ("Housing",          ["On-campus","Off-campus"]),
    ]

    def saved(e):
        page.snack_bar = ft.SnackBar(
            content=ft.Text("Profile saved ✓", color="#000"),
            bgcolor=COLORS["primary"])
        page.snack_bar.open = True
        page.update()

    inputs = [
        card(ft.Column(spacing=12, controls=[
            label(name, bold=True),
            ft.TextField(hint_text=hint, bgcolor=COLORS["surface2"],
                         border_color=COLORS["border"],
                         focused_border_color=COLORS["primary"],
                         color=COLORS["text"],
                         hint_style=ft.TextStyle(color=COLORS["text_dim"]),
                         border_radius=8),
        ]))
        for name, hint, _ in fields
    ] + [
        card(ft.Column(spacing=12, controls=[
            label(name, bold=True),
            ft.Dropdown(
                options=[ft.dropdown.Option(o) for o in opts],
                bgcolor=COLORS["surface2"],
                border_color=COLORS["border"],
                focused_border_color=COLORS["primary"],
                color=COLORS["text"],
                border_radius=8,
            ),
        ]))
        for name, opts in dropdowns
    ]

    return ft.Container(
        expand=True,
        bgcolor=COLORS["bg"],
        padding=ft.padding.symmetric(horizontal=18, vertical=16),
        content=ft.Column(
            scroll=ft.ScrollMode.AUTO,
            spacing=14,
            controls=[
                heading("Profile", 22),
                label("This data is stored locally and never shared without consent."),
                *inputs,
                ft.ElevatedButton(
                    "Save profile",
                    bgcolor=COLORS["primary"], color="#000",
                    width=float("inf"),
                    on_click=saved,
                    style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=12)),
                ),
                ft.Container(height=10),
            ],
        ),
    )

# ══════════════════════════════════════════════════════════════════
# MAIN APP
# ══════════════════════════════════════════════════════════════════

def main(page: ft.Page):
    init_db()
    sensor.start()

    page.title        = "SafeRoute"
    page.theme_mode   = ft.ThemeMode.DARK
    page.bgcolor      = COLORS["bg"]
    page.padding      = 0
    page.window_width  = 390
    page.window_height = 820

    # ── Content area ──────────────────────────────────────────────
    content = ft.Container(expand=True)
    nav_bar = ft.Ref[ft.NavigationBar]()

    def navigate(screen: str):
        screens = {
            "dashboard": build_dashboard,
            "ema":       build_ema,
            "history":   build_history,
            "profile":   build_profile,
        }
        idx_map = {"dashboard": 0, "ema": 1, "history": 2, "profile": 3}
        builder = screens.get(screen, build_dashboard)
        content.content = builder(page, navigate)
        if nav_bar.current:
            nav_bar.current.selected_index = idx_map.get(screen, 0)
        page.update()

    def on_nav(e):
        names = ["dashboard", "ema", "history", "profile"]
        navigate(names[e.control.selected_index])

    # ── Auto-refresh dashboard every 5s ──────────────────────────
    def auto_refresh():
        while True:
            time.sleep(5)
            if nav_bar.current and nav_bar.current.selected_index == 0:
                try:
                    content.content = build_dashboard(page, navigate)
                    page.update()
                except:
                    pass
    threading.Thread(target=auto_refresh, daemon=True).start()

    sensor.add_callback(lambda: None)  # hook for future live callbacks

    page.add(ft.Column(
        expand=True,
        spacing=0,
        controls=[
            content,
            ft.NavigationBar(
                ref=nav_bar,
                bgcolor=COLORS["surface"],
                indicator_color=COLORS["primary"] + "22",
                selected_index=0,
                on_change=on_nav,
                destinations=[
                    ft.NavigationBarDestination(icon=ft.icons.SHIELD_OUTLINED,
                                                selected_icon=ft.icons.SHIELD,
                                                label="Dashboard"),
                    ft.NavigationBarDestination(icon=ft.icons.ASSIGNMENT_OUTLINED,
                                                selected_icon=ft.icons.ASSIGNMENT,
                                                label="Survey"),
                    ft.NavigationBarDestination(icon=ft.icons.HISTORY,
                                                label="History"),
                    ft.NavigationBarDestination(icon=ft.icons.PERSON_OUTLINE,
                                                selected_icon=ft.icons.PERSON,
                                                label="Profile"),
                ],
            ),
        ],
    ))

    navigate("dashboard")


ft.app(target=main)
