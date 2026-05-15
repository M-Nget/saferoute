import flet as ft, threading, time, random, sqlite3, json
from datetime import datetime
from pathlib import Path

def border_all(w,c):
    s=ft.BorderSide(w,c)
    return ft.Border(top=s,bottom=s,left=s,right=s)
def pad(l=0,r=0,t=0,b=0): return ft.Padding(left=l,right=r,top=t,bottom=b)
def pad_all(v): return pad(v,v,v,v)
def pad_hv(h,v): return pad(h,h,v,v)
def mar_all(v): return ft.Margin(left=v,right=v,top=v,bottom=v)
CENTER=ft.Alignment(0,0)
DB=Path("saferoute.db")
C=dict(bg="#0D1117",surf="#161B22",surf2="#21262D",bord="#30363D",
       pri="#00D4AA",warn="#F4A261",dang="#E76F51",crit="#C1121F",
       txt="#E6EDF3",dim="#7D8590")

def tier(s):
    if s<3: return "LOW","#00D4AA"
    if s<6: return "MODERATE","#F4A261"
    if s<8: return "HIGH","#E76F51"
    return "CRITICAL","#C1121F"

EMA=[
    {"id":"fatigue","dom":"Fatigue","q":"How tired are you right now?","t":"slider","max":10},
    {"id":"stress","dom":"Stress","q":"Rate your current stress level.","t":"slider","max":100},
    {"id":"safety","dom":"Perceived Safety","q":"How safe do you feel right now?","t":"lik","o":["Very unsafe","Unsafe","Neutral","Safe","Very safe"]},
    {"id":"dist","dom":"Distraction","q":"Were you using your phone while walking?","t":"lik","o":["Yes","Partially","No"]},
    {"id":"fam","dom":"Familiarity","q":"How familiar are you with this area?","t":"lik","o":["Not at all","Slightly","Somewhat","Mostly","Very well"]},
    {"id":"nm","dom":"Near-miss","q":"Did anything almost happen just now?","t":"yn"},
    {"id":"cult","dom":"Cultural","q":"Do local traffic norms confuse you?","t":"lik","o":["Not at all","Slightly","Somewhat","Quite","Very much"]},
    {"id":"acad","dom":"Academic stress","q":"How stressed are you about your studies today?","t":"lik","o":["None","Low","Moderate","High","Extreme"]},
]

# ══ DATABASE ═══════════════════════════════════════════════════
def init_db():
    conn=sqlite3.connect(DB)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS ema(id INTEGER PRIMARY KEY AUTOINCREMENT,ts TEXT,ans TEXT);
        CREATE TABLE IF NOT EXISTS risk(id INTEGER PRIMARY KEY AUTOINCREMENT,ts TEXT,score REAL,tier TEXT,fatigue REAL,stress REAL,familiarity REAL,distraction TEXT,cultural REAL,near_miss INTEGER);
        CREATE TABLE IF NOT EXISTS profile(id INTEGER PRIMARY KEY AUTOINCREMENT,ts TEXT,full_name TEXT,country TEXT,university TEXT,years_in_china TEXT,academic_level TEXT,transport TEXT,housing TEXT);
    """)
    conn.commit();conn.close()

def db_save_ema(ans):
    conn=sqlite3.connect(DB)
    conn.execute("INSERT INTO ema(ts,ans)VALUES(?,?)",(datetime.now().isoformat(),json.dumps(ans)))
    conn.commit();conn.close()

def db_save_risk(score,t,fat=0,str_=0,fam=4,dist="no",cult=1,nm=0):
    conn=sqlite3.connect(DB)
    conn.execute("INSERT INTO risk(ts,score,tier,fatigue,stress,familiarity,distraction,cultural,near_miss)VALUES(?,?,?,?,?,?,?,?,?)",
                 (datetime.now().isoformat(),score,t,fat,str_,fam,dist,cult,nm))
    conn.commit();conn.close()

def db_save_profile(data):
    conn=sqlite3.connect(DB)
    # Delete old entries for same name to prevent duplicates
    conn.execute("DELETE FROM profile WHERE full_name=?",(data.get("name",""),))
    conn.execute("INSERT INTO profile(ts,full_name,country,university,years_in_china,academic_level,transport,housing)VALUES(?,?,?,?,?,?,?,?)",
                 (datetime.now().isoformat(),data.get("name",""),data.get("country",""),
                  data.get("university",""),data.get("years",""),data.get("level",""),
                  data.get("transport",""),data.get("housing","")))
    conn.commit();conn.close()

def db_load_profile():
    conn=sqlite3.connect(DB)
    row=conn.execute("SELECT full_name,country,university,years_in_china,academic_level,transport,housing FROM profile ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    if row: return {"name":row[0],"country":row[1],"university":row[2],"years":row[3],"level":row[4],"transport":row[5],"housing":row[6]}
    return {}

def db_last_ema():
    conn=sqlite3.connect(DB)
    row=conn.execute("SELECT ans,ts FROM ema ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    if row:
        try: return json.loads(row[0]),row[1]
        except: pass
    return {},None

def db_history(n=25):
    conn=sqlite3.connect(DB)
    rows=conn.execute("SELECT ts,score,tier FROM risk ORDER BY id DESC LIMIT ?",(n,)).fetchall()
    conn.close();return rows

def db_stats():
    conn=sqlite3.connect(DB)
    n1=conn.execute("SELECT COUNT(*) FROM ema").fetchone()[0]
    n2=conn.execute("SELECT COUNT(*) FROM risk").fetchone()[0]
    av=conn.execute("SELECT AVG(score) FROM risk").fetchone()[0]
    conn.close();return n1,n2,round(av or 0.0,1)

def db_minutes_since_last_ema():
    conn=sqlite3.connect(DB)
    row=conn.execute("SELECT ts FROM ema ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    if not row: return 9999
    try:
        last=datetime.fromisoformat(row[0])
        return (datetime.now()-last).total_seconds()/60
    except: return 9999

# ══ SENSOR ENGINE (reads from last EMA) ════════════════════════
class Sensor:
    def __init__(self):
        self.risk=2.1;self.fat=3;self.str_=25;self.fam=4
        self.night=False;self.rain=False;self.mode="walking"
        self.spd=1.2;self.min=0.0;self._on=False
        self.dist="no";self.cult=1;self.nm=0

    def start(self):
        self._on=True;threading.Thread(target=self._loop,daemon=True).start()

    def update_from_ema(self,ans):
        """Update sensor state from latest EMA response"""
        if "fatigue" in ans:   self.fat   = int(ans["fatigue"])
        if "stress"  in ans:   self.str_  = int(ans["stress"])
        if "fam"     in ans:   self.fam   = int(ans["fam"])+1
        if "dist"    in ans:   self.dist  = ans["dist"]
        if "cult"    in ans:   self.cult  = int(ans["cult"])+1
        if "nm"      in ans:   self.nm    = 1 if ans["nm"]=="yes" else 0

    def _loop(self):
        while self._on:
            # Load latest EMA every cycle
            ans,_ = db_last_ema()
            if ans: self.update_from_ema(ans)

            self.spd=abs(random.gauss(1.3,0.4))
            self.mode="walking" if self.spd<2 else "cycling" if self.spd<8 else "vehicle"
            self.min+=5/60

            # Check if night (22:00-06:00)
            h=datetime.now().hour
            self.night = h>=22 or h<=6

            # Compute risk from real EMA values
            base=(
                self.fat*0.35 +
                self.str_/100*2.5 +
                (6-self.fam)*0.50 +
                (1.5 if self.night else 0) +
                (1.0 if self.rain  else 0) +
                (1.5 if self.nm    else 0) +
                (self.cult-1)*0.30 +
                (1.2 if self.dist=="yes" else 0.5 if self.dist=="partially" else 0) +
                random.gauss(0,0.4)
            )
            self.risk=round(max(0.0,min(10.0,base)),1)
            t,_=tier(self.risk)
            db_save_risk(self.risk,t,self.fat,self.str_,self.fam,self.dist,self.cult,self.nm)
            time.sleep(5)

S=Sensor()

# ══ UI ATOMS ═══════════════════════════════════════════════════
def T(t,sz=14,col=None,bold=False,mono=False):
    return ft.Text(t,size=sz,color=col or C["txt"],
                   weight=ft.FontWeight.W_700 if bold else ft.FontWeight.W_400,
                   font_family="monospace" if mono else None)
def Dim(t,sz=12): return ft.Text(t,size=sz,color=C["dim"])
def Card(content,bc=None,p=14):
    return ft.Container(content=content,bgcolor=C["surf"],border_radius=12,
                        padding=pad_all(p),border=border_all(1,bc or C["bord"]))
def Badge(label,col):
    return ft.Container(content=ft.Text(label,size=10,weight=ft.FontWeight.W_700,color=col),
                        padding=pad(10,10,3,3),border_radius=20,
                        bgcolor=col+"22",border=border_all(1,col+"55"))
def Btn(label,col,on_click,width=None):
    return ft.Button(label,bgcolor=col,color="#000000",width=width,on_click=on_click,
                     style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=10)))
def GhostBtn(label,on_click):
    return ft.OutlinedButton(label,on_click=on_click,
                             style=ft.ButtonStyle(color=C["dim"],side=ft.BorderSide(1,C["bord"])))

# ══ EMA REMINDER POPUP ═════════════════════════════════════════
def show_ema_reminder(page,navigate):
    """Show full-screen EMA reminder that must be dismissed"""
    mins=db_minutes_since_last_ema()
    if mins < 30: return  # Don't show if survey done < 30 min ago

    def go_survey(e):
        page.dialog.open=False
        page.update()
        navigate("ema")

    def remind_later(e):
        page.dialog.open=False
        page.update()

    page.dialog=ft.AlertDialog(
        modal=True,
        bgcolor=C["surf"],
        title=ft.Text("⏰ Time for your EMA Survey",
                      size=18,weight=ft.FontWeight.W_700,color=C["warn"]),
        content=ft.Column(spacing=12,tight=True,controls=[
            ft.Text("You haven't completed a survey in the last 30 minutes.",
                    size=14,color=C["txt"]),
            ft.Text("Your response helps track your real risk factors accurately.",
                    size=13,color=C["dim"]),
            ft.Container(
                padding=pad_all(12),border_radius=8,
                bgcolor=C["warn"]+"18",border=border_all(1,C["warn"]+"44"),
                content=ft.Text(
                    f"Last survey: {int(mins)} min ago" if mins<9999 else "No survey completed yet",
                    size=12,color=C["warn"])),
        ]),
        actions=[
            ft.TextButton("Remind me later",on_click=remind_later,
                          style=ft.ButtonStyle(color=C["dim"])),
            ft.Button("Start Survey Now",bgcolor=C["warn"],color="#000",
                      on_click=go_survey,
                      style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=8))),
        ],
        actions_alignment=ft.MainAxisAlignment.END,
    )
    page.dialog.open=True
    page.update()

# ══ DASHBOARD ══════════════════════════════════════════════════
def dashboard(page,navigate):
    sc=S.risk;t,col=tier(sc)
    now=datetime.now().strftime("%H:%M · %d %b %Y")
    ans,last_ts=db_last_ema()
    mins=db_minutes_since_last_ema()

    ring=ft.Stack(width=180,height=180,controls=[
        ft.Container(width=180,height=180,border_radius=90,border=border_all(6,col+"33")),
        ft.Container(width=148,height=148,border_radius=74,margin=mar_all(16),
                     bgcolor=col+"18",border=border_all(2.5,col),
                     content=ft.Column(alignment=ft.MainAxisAlignment.CENTER,
                                       horizontal_alignment=ft.CrossAxisAlignment.CENTER,spacing=2,
                                       controls=[T(f"{sc:.1f}",sz=44,col=col,bold=True,mono=True),
                                                 Dim("/ 10.0"),ft.Container(height=4),Badge(t,col)]))])

    factors=[
        ("Fatigue",    S.fat/10,                              C["dang"]),
        ("Stress",     S.str_/100,                            C["warn"]),
        ("Familiarity",1-(S.fam-1)/4,                        C["pri"]),
        ("Night",      1.0 if S.night else 0.05,             "#7B68EE"),
        ("Near-miss",  1.0 if S.nm else 0.05,                C["crit"]),
    ]
    def fbar(name,val,fc):
        return ft.Column(spacing=3,controls=[
            ft.Row(controls=[ft.Text(name,size=12,color=C["dim"],expand=True),
                             ft.Text(f"{val*10:.1f}",size=12,color=fc,font_family="monospace")]),
            ft.Container(height=5,border_radius=3,bgcolor=C["surf2"],
                         content=ft.Container(width=max(4.0,280.0*float(val)),
                                              height=5,border_radius=3,bgcolor=fc))])

    nudge_map={"HIGH":"⚠  Multiple risks. Slow down and stay alert.",
               "CRITICAL":"🚨  Critical risk. Stop and find safety now."}
    nudge=ft.Container(visible=t in nudge_map,padding=pad_all(14),border_radius=12,
                       bgcolor=col+"18",border=border_all(1.5,col+"66"),
                       content=ft.Text(nudge_map.get(t,""),size=13,color=col))

    sym={"walking":"🚶","cycling":"🚴","vehicle":"🚗"}.get(S.mode,"🚶")

    # EMA status card — red if overdue
    ema_overdue = mins > 30
    ema_col = C["dang"] if ema_overdue else C["warn"]
    ema_msg  = f"⚠ Overdue! Last survey {int(mins)} min ago" if ema_overdue else \
               f"Last survey {int(mins)} min ago" if mins<9999 else "No survey yet — please start!"

    return ft.Container(expand=True,bgcolor=C["bg"],padding=pad_hv(18,16),
        content=ft.Column(scroll=ft.ScrollMode.AUTO,spacing=14,controls=[
            ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN,controls=[
                ft.Column(spacing=2,controls=[T("SafeRoute",sz=22,bold=True),Dim(now)]),
                ft.IconButton(ft.Icons.NOTIFICATIONS,icon_color=C["dim"])]),
            ft.Container(alignment=CENTER,content=ring),
            nudge,
            Card(ft.Column(spacing=10,controls=[
                T("Risk factors (from your last EMA)",sz=13,col=C["dim"],bold=True),
                *[fbar(n,v,c) for n,v,c in factors]])),
            Card(ft.Row(controls=[
                ft.Text(sym,size=22),ft.Container(width=10),
                ft.Column(spacing=2,expand=True,controls=[
                    T("Trip in progress",sz=13,bold=True),
                    Dim(f"{S.mode.capitalize()} · {S.min:.0f} min · {S.spd:.1f} m/s")]),
                ft.Container(width=8,height=8,border_radius=4,bgcolor=C["pri"])]),
                bc=C["pri"]+"44"),
            Card(ft.Row(controls=[
                ft.Text("📋",size=20),ft.Container(width=10),
                ft.Column(spacing=2,expand=True,controls=[
                    T("EMA Survey",sz=13,bold=True),
                    ft.Text(ema_msg,size=11,color=ema_col)]),
                ft.Button("Start",bgcolor=ema_col,color="#000",
                          on_click=lambda _:navigate("ema"),
                          style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=8)))]),
                bc=ema_col+"44"),
        ]))

# ══ EMA SURVEY ═════════════════════════════════════════════════
def ema_screen(page,navigate):
    st={"q":0,"ans":{},"sv":5};col_ref=ft.Column(expand=True,spacing=16)
    def render():
        q=EMA[st["q"]];idx=st["q"];tot=len(EMA);pct=(idx+1)/tot;col=C["pri"]
        prog=ft.Column(spacing=4,controls=[
            ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                   controls=[Dim(f"Q {idx+1}/{tot}"),ft.Text(f"{int(pct*100)}%",size=12,color=col)]),
            ft.Container(height=3,border_radius=2,bgcolor=C["surf2"],
                         content=ft.Container(width=max(8.0,340.0*pct),height=3,border_radius=2,bgcolor=col))])
        pill=ft.Container(content=ft.Text(q["dom"],size=11,weight=ft.FontWeight.W_700,color=col),
                          padding=pad(12,12,4,4),border_radius=20,bgcolor=col+"20",
                          border=border_all(1,col+"44"))
        if q["t"]=="slider":
            vd=ft.Text(str(st["sv"]),size=36,weight=ft.FontWeight.W_700,color=col,font_family="monospace")
            def onsl(e): st["sv"]=int(e.control.value);st["ans"][q["id"]]=st["sv"];vd.value=str(st["sv"]);page.update()
            resp=ft.Column(spacing=10,controls=[
                ft.Container(alignment=CENTER,content=vd),
                ft.Slider(min=0,max=q["max"],value=float(st["sv"]),active_color=col,inactive_color=col+"30",on_change=onsl),
                ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN,controls=[Dim("0"),Dim(str(q["max"]))])])
        elif q["t"]=="lik":
            sel=st["ans"].get(q["id"]);opts=[]
            for i,o in enumerate(q["o"]):
                is_s=sel==i
                def pick(e,i_=i,qid=q["id"]): st["ans"][qid]=i_;render()
                opts.append(ft.Container(padding=pad_all(12),border_radius=10,
                    bgcolor=col+"22" if is_s else C["surf2"],
                    border=border_all(1.5 if is_s else 1,col if is_s else C["bord"]),
                    on_click=pick,
                    content=ft.Row(spacing=12,controls=[
                        ft.Container(width=18,height=18,border_radius=9,
                                     bgcolor=col if is_s else "transparent",
                                     border=border_all(1.5,col if is_s else C["bord"])),
                        ft.Text(o,size=14,color=C["txt"] if is_s else C["dim"])])))
            resp=ft.Column(spacing=8,controls=opts)
        elif q["t"]=="yn":
            sel=st["ans"].get(q["id"])
            def yes(e): st["ans"][q["id"]]="yes";render()
            def no(e):  st["ans"][q["id"]]="no"; render()
            resp=ft.Row(spacing=12,controls=[
                Btn("Yes",col if sel=="yes" else C["surf2"],yes),
                Btn("No", col if sel=="no"  else C["surf2"],no)])
        else: resp=ft.Container()
        def back(e): st["q"]=max(0,st["q"]-1);st["sv"]=5;render()
        def nxt(e):
            if st["q"]<tot-1: st["q"]+=1;st["sv"]=5;render()
            else:
                db_save_ema(st["ans"])
                # Update sensor immediately
                S.update_from_ema(st["ans"])
                page.snack_bar=ft.SnackBar(
                    content=ft.Text("Survey submitted ✓ Risk score updated!",color="#000"),
                    bgcolor=C["pri"])
                page.snack_bar.open=True
                st["q"]=0;st["ans"]={};st["sv"]=5;navigate("dashboard")
        col_ref.controls=[
            ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                   controls=[T("EMA Survey",sz=20,bold=True),Dim(datetime.now().strftime("%H:%M"))]),
            prog,ft.Container(height=4),pill,
            T(q["q"],sz=17,bold=True),
            ft.Container(expand=True,content=resp),
            ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN,controls=[
                GhostBtn("Back",back) if idx>0 else ft.Container(),
                Btn("Submit ✓" if idx==tot-1 else "Next →",col,nxt)])]
        page.update()
    render()
    return ft.Container(expand=True,bgcolor=C["bg"],padding=pad_hv(18,20),content=col_ref)

# ══ HISTORY ════════════════════════════════════════════════════
def history(page,navigate):
    rows=db_history(30);n1,n2,av=db_stats();_,ac=tier(av)
    def sc(val,lbl,col): return Card(ft.Column(spacing=2,
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        controls=[T(str(val),sz=26,col=col,bold=True,mono=True),Dim(lbl)]),p=12)
    body=[]
    if not rows:
        body=[ft.Container(height=180,alignment=CENTER,
            content=ft.Column(alignment=ft.MainAxisAlignment.CENTER,
                              horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                              controls=[ft.Text("No data yet",size=16,color=C["dim"])]))]
    else:
        for ts,score,t in rows:
            _,col=tier(score)
            try: ds=datetime.fromisoformat(ts).strftime("%d %b  %H:%M")
            except: ds=ts[:16]
            body.append(ft.Container(padding=pad(14,14,10,10),border_radius=8,bgcolor=C["surf2"],
                content=ft.Row(controls=[
                    ft.Container(width=4,height=36,border_radius=2,bgcolor=col),ft.Container(width=10),
                    ft.Column(spacing=2,expand=True,controls=[
                        ft.Text(ds,size=12,color=C["txt"]),
                        ft.Text(t,size=11,color=col,weight=ft.FontWeight.W_600)]),
                    T(f"{score:.1f}",sz=22,col=col,bold=True,mono=True)])))
    return ft.Container(expand=True,bgcolor=C["bg"],padding=pad_hv(18,16),
        content=ft.Column(scroll=ft.ScrollMode.AUTO,spacing=14,controls=[
            T("History",sz=22,bold=True),
            ft.Row(spacing=10,controls=[sc(n1,"EMA",C["pri"]),sc(n2,"Readings",C["warn"]),sc(av,"Avg",ac)]),
            T("Recent readings",sz=13,col=C["dim"],bold=True),
            ft.Column(spacing=8,controls=body)]))

# ══ PROFILE ════════════════════════════════════════════════════
def profile(page,navigate):
    existing=db_load_profile()
    f_name=ft.TextField(hint_text="e.g. Kwame Mensah",value=existing.get("name",""),
        bgcolor=C["surf2"],border_color=C["bord"],focused_border_color=C["pri"],
        color=C["txt"],hint_style=ft.TextStyle(color=C["dim"]),border_radius=8)
    f_country=ft.TextField(hint_text="e.g. Nigeria",value=existing.get("country",""),
        bgcolor=C["surf2"],border_color=C["bord"],focused_border_color=C["pri"],
        color=C["txt"],hint_style=ft.TextStyle(color=C["dim"]),border_radius=8)
    f_university=ft.TextField(hint_text="e.g. Central South University",value=existing.get("university",""),
        bgcolor=C["surf2"],border_color=C["bord"],focused_border_color=C["pri"],
        color=C["txt"],hint_style=ft.TextStyle(color=C["dim"]),border_radius=8)
    f_years=ft.TextField(hint_text="e.g. 2.5",value=existing.get("years",""),
        bgcolor=C["surf2"],border_color=C["bord"],focused_border_color=C["pri"],
        color=C["txt"],hint_style=ft.TextStyle(color=C["dim"]),border_radius=8)
    f_level=ft.Dropdown(value=existing.get("level",""),
        options=[ft.dropdown.Option(o) for o in ["Undergraduate","Masters","PhD","Postdoc"]],
        bgcolor=C["surf2"],border_color=C["bord"],focused_border_color=C["pri"],color=C["txt"],border_radius=8)
    f_transport=ft.Dropdown(value=existing.get("transport",""),
        options=[ft.dropdown.Option(o) for o in ["Walking","Cycling","Bus","E-scooter","Car"]],
        bgcolor=C["surf2"],border_color=C["bord"],focused_border_color=C["pri"],color=C["txt"],border_radius=8)
    f_housing=ft.Dropdown(value=existing.get("housing",""),
        options=[ft.dropdown.Option(o) for o in ["On-campus","Off-campus"]],
        bgcolor=C["surf2"],border_color=C["bord"],focused_border_color=C["pri"],color=C["txt"],border_radius=8)
    status=ft.Text("",size=13,color=C["pri"])

    def saved(e):
        if not f_name.value or not f_country.value:
            status.value="Please fill in at least Name and Country."
            status.color=C["dang"];page.update();return
        db_save_profile({"name":f_name.value,"country":f_country.value,
                         "university":f_university.value,"years":f_years.value,
                         "level":f_level.value or "","transport":f_transport.value or "",
                         "housing":f_housing.value or ""})
        status.value="✓ Profile saved!"
        status.color=C["pri"]
        page.snack_bar=ft.SnackBar(content=ft.Text("Profile saved ✓",color="#000"),bgcolor=C["pri"])
        page.snack_bar.open=True;page.update()

    def fc(lbl,widget):
        return Card(ft.Column(spacing=8,controls=[T(lbl,sz=13,col=C["dim"],bold=True),widget]))

    return ft.Container(expand=True,bgcolor=C["bg"],padding=pad_hv(18,16),
        content=ft.Column(scroll=ft.ScrollMode.AUTO,spacing=12,controls=[
            T("Profile",sz=22,bold=True),
            Dim("Stored locally. Never shared without consent."),
            fc("Full name",f_name),fc("Country of origin",f_country),
            fc("University",f_university),fc("Years in China",f_years),
            fc("Academic level",f_level),fc("Primary transport",f_transport),
            fc("Housing",f_housing),status,
            ft.Button("Save Profile",bgcolor=C["pri"],color="#000",width=float("inf"),
                      on_click=saved,style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=12))),
            ft.Container(height=16)]))

# ══ MAIN ═══════════════════════════════════════════════════════
def main(page:ft.Page):
    import os
    init_db();S.start()
    page.title="SafeRoute"
    page.theme_mode=ft.ThemeMode.DARK
    page.bgcolor=C["bg"];page.padding=0
    page.window_width=390;page.window_height=820

    content=ft.Container(expand=True)
    nav_ref=ft.Ref[ft.NavigationBar]()
    names=["dashboard","ema","history","profile"]
    builders=[dashboard,ema_screen,history,profile]

    def navigate(screen):
        idx=names.index(screen) if screen in names else 0
        content.content=builders[idx](page,navigate)
        if nav_ref.current: nav_ref.current.selected_index=idx
        page.update()

    def on_nav(e): navigate(names[e.control.selected_index])

    # Auto-refresh dashboard every 5s
    def auto_refresh():
        while True:
            time.sleep(5)
            try:
                if nav_ref.current and nav_ref.current.selected_index==0:
                    content.content=dashboard(page,navigate);page.update()
            except: pass

    # EMA reminder every 30 min
    def ema_reminder():
        time.sleep(60)  # Wait 1 min before first check
        while True:
            try:
                if nav_ref.current and nav_ref.current.selected_index==0:
                    show_ema_reminder(page,navigate)
            except: pass
            time.sleep(1800)  # Check every 30 min

    threading.Thread(target=auto_refresh,daemon=True).start()
    threading.Thread(target=ema_reminder,daemon=True).start()

    page.add(ft.Column(expand=True,spacing=0,controls=[
        content,
        ft.NavigationBar(ref=nav_ref,bgcolor=C["surf"],
                         indicator_color=C["pri"]+"22",selected_index=0,on_change=on_nav,
                         destinations=[
                             ft.NavigationBarDestination(icon=ft.Icons.HOME,selected_icon=ft.Icons.HOME,label="Dashboard"),
                             ft.NavigationBarDestination(icon=ft.Icons.EDIT,selected_icon=ft.Icons.EDIT,label="Survey"),
                             ft.NavigationBarDestination(icon=ft.Icons.BAR_CHART,selected_icon=ft.Icons.BAR_CHART,label="History"),
                             ft.NavigationBarDestination(icon=ft.Icons.PERSON,selected_icon=ft.Icons.PERSON,label="Profile"),
                         ])]))
    navigate("dashboard")

PORT=int(__import__('os').environ.get("PORT",8000))
ft.app(target=main,view=ft.AppView.WEB_BROWSER,port=PORT,host="0.0.0.0")
