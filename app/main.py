import os
import asyncio
import datetime
import requests
import secrets
from fastapi import FastAPI, Request, Form, Depends, BackgroundTasks, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from playwright.async_api import async_playwright
from apscheduler.schedulers.background import BackgroundScheduler

# --- CONFIG & DB SETUP ---
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK")
ADMIN_USER = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASS = os.getenv("ADMIN_PASSWORD", "password")
DATABASE_URL = "sqlite:///./data/monitor.db"

os.makedirs("screenshots", exist_ok=True)
os.makedirs("data", exist_ok=True)

Base = declarative_base()
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

class Site(Base):
    __tablename__ = "sites"
    id = Column(Integer, primary_key=True, index=True)
    url = Column(String)
    search_string = Column(String)
    frequency = Column(Integer)
    device_type = Column(String, default="desktop") # 'desktop' or 'mobile'
    last_status = Column(String, default="Pending")
    last_check = Column(DateTime)
    screenshot_path = Column(String)

class CheckLog(Base):
    __tablename__ = "check_logs"
    id = Column(Integer, primary_key=True, index=True)
    site_id = Column(Integer, ForeignKey("sites.id"))
    timestamp = Column(DateTime, default=datetime.datetime.now)
    status = Column(String)
    screenshot_path = Column(String)

Base.metadata.create_all(bind=engine)

# --- SECURITY ---
security = HTTPBasic()
def authenticate(credentials: HTTPBasicCredentials = Depends(security)):
    if not (secrets.compare_digest(credentials.username, ADMIN_USER) and 
            secrets.compare_digest(credentials.password, ADMIN_PASS)):
        raise HTTPException(status_code=401, detail="Unauthorized", headers={"WWW-Authenticate": "Basic"})
    return credentials.username

# --- APP & SCHEDULER ---
app = FastAPI()
app.mount("/screenshots", StaticFiles(directory="screenshots"), name="screenshots")
templates = Jinja2Templates(directory="templates")

def cleanup_old_data():
    db = SessionLocal()
    cutoff = datetime.datetime.now() - datetime.timedelta(days=7)
    db.query(CheckLog).filter(CheckLog.timestamp < cutoff).delete()
    db.commit()
    db.close()
    if os.path.exists("screenshots"):
        for f in os.listdir("screenshots"):
            path = os.path.join("screenshots", f)
            if os.path.isfile(path) and datetime.datetime.fromtimestamp(os.path.getmtime(path)) < cutoff:
                os.remove(path)

scheduler = BackgroundScheduler()
scheduler.add_job(cleanup_old_data, 'cron', hour=0, minute=0)
scheduler.start()

def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

def send_notification(message):
    if DISCORD_WEBHOOK_URL:
        try: requests.post(DISCORD_WEBHOOK_URL, json={"content": f"🚨 **Alert**: {message}"}, timeout=5)
        except: pass

# --- MONITORING LOGIC ---
async def perform_check(site_id: int):
    db = SessionLocal()
    site = db.query(Site).filter(Site.id == site_id).first()
    if not site:
        db.close()
        return

    async with async_playwright() as p:
        try:
            browser = await p.chromium.launch(headless=True)
            
            # Set Viewport based on Device Type
            if site.device_type == "mobile":
                viewport = {'width': 375, 'height': 812}
                user_agent = "Mozilla/5.0 (iPhone; CPU iPhone OS 14_7_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.2 Mobile/15E148 Safari/604.1"
            else:
                viewport = {'width': 1920, 'height': 1080}
                user_agent = None

            context = await browser.new_context(viewport=viewport, user_agent=user_agent)
            page = await context.new_page()
            
            response = await page.goto(site.url, wait_until="networkidle", timeout=30000)
            is_up = response.status < 400
            content = await page.content()
            string_found = site.search_string in content
            
            filename = f"site_{site.id}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            # FULL PAGE Screenshot
            await page.screenshot(path=f"screenshots/{filename}", full_page=True)

            status_text = "✅ Healthy"
            if not is_up: status_text = f"❌ Down ({response.status})"
            elif not string_found: status_text = "🔍 String Missing"

            site.last_status, site.last_check, site.screenshot_path = status_text, datetime.datetime.now(), filename
            db.add(CheckLog(site_id=site.id, status=status_text, screenshot_path=filename))
            db.commit()
            
            if "Healthy" not in status_text: send_notification(f"{site.url} ({site.device_type}): {status_text}")
            await browser.close()
        except Exception as e:
            db.add(CheckLog(site_id=site_id, status=f"Error: {str(e)[:30]}"))
            db.commit()
        finally: db.close()

def run_scheduler_check(site_id):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(perform_check(site_id))
    loop.close()

# --- ROUTES ---
@app.get("/", response_class=HTMLResponse)
async def index(request: Request, db: Session = Depends(get_db), user: str = Depends(authenticate)):
    sites = db.query(Site).all()
    logs = db.query(CheckLog).order_by(CheckLog.timestamp.desc()).limit(15).all()
    site_history = {site.id: [r.status for r in reversed(db.query(CheckLog).filter(CheckLog.site_id == site.id).order_by(CheckLog.timestamp.desc()).limit(5).all())] for site in sites}
    return templates.TemplateResponse("index.html", {
        "request": request, "sites": sites, "logs": logs, 
        "site_history": site_history, "site_map": {s.id: s.url for s in sites}
    })

@app.post("/add")
async def add_site(bg: BackgroundTasks, url: str = Form(...), search_string: str = Form(...), frequency: int = Form(...), device_type: str = Form(...), db: Session = Depends(get_db), user: str = Depends(authenticate)):
    if not url.startswith("http"): url = "https://" + url
    site = Site(url=url, search_string=search_string, frequency=frequency, device_type=device_type)
    db.add(site); db.commit(); db.refresh(site)
    scheduler.add_job(run_scheduler_check, 'interval', minutes=site.frequency, args=[site.id], id=f"site_{site.id}")
    bg.add_task(perform_check, site.id)
    return RedirectResponse(url="/", status_code=303)

@app.post("/check/{site_id}")
async def check_now(site_id: int, bg: BackgroundTasks, db: Session = Depends(get_db), user: str = Depends(authenticate)):
    bg.add_task(perform_check, site_id)
    return RedirectResponse(url="/", status_code=303)

@app.post("/delete/{site_id}")
async def delete_site(site_id: int, db: Session = Depends(get_db), user: str = Depends(authenticate)):
    site = db.query(Site).filter(Site.id == site_id).first()
    if site:
        try: scheduler.remove_job(f"site_{site_id}")
        except: pass
        db.query(CheckLog).filter(CheckLog.site_id == site_id).delete()
        db.delete(site); db.commit()
    return RedirectResponse(url="/", status_code=303)