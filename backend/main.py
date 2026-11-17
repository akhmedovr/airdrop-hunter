import os, time, json, logging
from datetime import datetime, timezone
from typing import Any
import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, HttpUrl
from apscheduler.schedulers.asyncio import AsyncIOScheduler

logging.basicConfig(level=os.getenv("LOG_LEVEL","INFO"))
log=logging.getLogger("airdrop-hunter")
SUPABASE_URL=os.getenv("SUPABASE_URL","").rstrip("/")
SUPABASE_ANON_KEY=os.getenv("SUPABASE_ANON_KEY","")
SUPABASE_SERVICE_ROLE_KEY=os.getenv("SUPABASE_SERVICE_ROLE_KEY","")
VAPID_PUBLIC_KEY=os.getenv("VAPID_PUBLIC_KEY","")
VAPID_PRIVATE_KEY=os.getenv("VAPID_PRIVATE_KEY","")
VAPID_SUBJECT=os.getenv("VAPID_SUBJECT","mailto:admin@example.com")
scheduler=AsyncIOScheduler(timezone="UTC")
app=FastAPI(title="Airdrop Hunter API",version="2.0.0")
app.add_middleware(CORSMiddleware,allow_origins=os.getenv("CORS_ORIGINS","*").split(","),allow_credentials=False,allow_methods=["GET","POST","PATCH","DELETE","OPTIONS"],allow_headers=["Authorization","Content-Type"])

async def auth_user(authorization: str|None):
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401,"Authentication required")
    token=authorization.split(" ",1)[1]
    async with httpx.AsyncClient(timeout=12) as c:
        r=await c.get(f"{SUPABASE_URL}/auth/v1/user",headers={"apikey":SUPABASE_ANON_KEY,"Authorization":f"Bearer {token}"})
    if r.status_code!=200: raise HTTPException(401,"Invalid or expired session")
    return r.json()

def db_headers(owner_token: str|None=None):
    key=SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY
    h={"apikey":key,"Content-Type":"application/json"}
    if owner_token: h["Authorization"]=f"Bearer {owner_token}"
    else: h["Authorization"]=f"Bearer {key}"
    return h

async def db_get(table,owner_id,query=""):
    if not SUPABASE_URL or not SUPABASE_ANON_KEY: raise HTTPException(503,"Database is not configured")
    headers=db_headers()
    async with httpx.AsyncClient(timeout=20) as c:
        r=await c.get(f"{SUPABASE_URL}/rest/v1/{table}?owner_id=eq.{owner_id}&{query}",headers=headers)
    if r.status_code>=400: raise HTTPException(502,f"Database read failed: {r.text[:250]}")
    return r.json()

async def db_insert(table,payload):
    if not SUPABASE_SERVICE_ROLE_KEY: raise HTTPException(503,"Server database key is not configured yet")
    async with httpx.AsyncClient(timeout=20) as c:
        r=await c.post(f"{SUPABASE_URL}/rest/v1/{table}",headers={**db_headers(),"Prefer":"return=representation"},json=payload)
    if r.status_code>=300: raise HTTPException(502,f"Database write failed: {r.text[:250]}")
    return r.json()

@app.on_event("startup")
async def startup():
    if os.getenv("ENABLE_SCHEDULER","true").lower()=="true":
        scheduler.add_job(scheduled_health_scan,"interval",minutes=int(os.getenv("SCAN_INTERVAL_MINUTES","360")),id="source-scan",replace_existing=True,max_instances=1)
        scheduler.start()

@app.on_event("shutdown")
async def shutdown():
    if scheduler.running: scheduler.shutdown(wait=False)

@app.get("/api/health")
async def health():
    return {"status":"ok","service":"airdrop-hunter","scheduler_running":scheduler.running,"database_configured":bool(SUPABASE_URL and SUPABASE_ANON_KEY),"worker_write_enabled":bool(SUPABASE_SERVICE_ROLE_KEY),"time":datetime.now(timezone.utc).isoformat()}

@app.get("/api/dashboard")
async def dashboard(authorization: str|None=Header(default=None)):
    user=await auth_user(authorization); uid=user["id"]
    campaigns=await db_get("campaigns",uid,"select=id,status")
    tasks=await db_get("tasks",uid,"select=id,status,due_at")
    rewards=await db_get("rewards",uid,"select=estimated_usd,realized_usd,status")
    notifications=await db_get("notifications",uid,"select=id,read_at")
    return {"active_campaigns":sum(1 for x in campaigns if x["status"] not in ("expired","rejected","realized")),"tasks_today":sum(1 for x in tasks if x["status"] in ("todo","ready","in_progress","waiting_user")),"claimable_rewards_usd":round(sum(float(x.get("estimated_usd") or 0) for x in rewards if x["status"]=="claimable"),2),"realized_pnl_usd":round(sum(float(x.get("realized_usd") or 0) for x in rewards if x["status"]=="realized"),2),"unread_notifications":sum(1 for x in notifications if not x["read_at"])}

@app.get("/api/notifications")
async def notifications(authorization: str|None=Header(default=None)):
    user=await auth_user(authorization); rows=await db_get("notifications",user["id"],"select=*&order=created_at.desc&limit=100")
    return {"items":rows,"unread_count":sum(1 for x in rows if not x["read_at"])}

@app.get("/api/opportunities")
async def opportunities(authorization: str|None=Header(default=None)):
    user=await auth_user(authorization)
    return {"items":await db_get("campaigns",user["id"],"select=*&order=discovered_at.desc&limit=100")}

@app.get("/api/tasks")
async def tasks(authorization: str|None=Header(default=None)):
    user=await auth_user(authorization)
    return {"items":await db_get("tasks",user["id"],"select=*&order=priority.desc,due_at.asc&limit=100")}

@app.get("/api/wallets")
async def wallets(authorization: str|None=Header(default=None)):
    user=await auth_user(authorization)
    return {"items":await db_get("wallets",user["id"],"select=*&order=created_at.desc")}

@app.get("/api/push/public-key")
async def push_key():
    return {"public_key":VAPID_PUBLIC_KEY or None}

@app.post("/api/push/subscribe")
async def push_subscribe(request:Request,authorization: str|None=Header(default=None)):
    user=await auth_user(authorization); data=await request.json()
    keys=data.get("keys") or {}
    endpoint=data.get("endpoint")
    if not endpoint or not keys.get("p256dh") or not keys.get("auth"): raise HTTPException(400,"Invalid push subscription")
    await db_insert("push_subscriptions",{"owner_id":user["id"],"endpoint":endpoint,"p256dh":keys["p256dh"],"auth_secret":keys["auth"],"user_agent":request.headers.get("user-agent")})
    return {"ok":True}

async def scheduled_health_scan():
    # Worker heartbeat only until official-source connectors and service credentials are configured.
    log.info("Scheduled scan heartbeat: connectors not yet configured; no wallet or transaction actions are performed.")

@app.post("/api/agent/run-scan")
async def run_scan(authorization: str|None=Header(default=None)):
    user=await auth_user(authorization)
    if not SUPABASE_SERVICE_ROLE_KEY: raise HTTPException(503,"Background worker storage is not configured")
    await db_insert("agent_runs",{"owner_id":user["id"],"job_type":"manual_scan","status":"queued","summary":"Scan queued; source connectors are being configured."})
    return {"accepted":True,"message":"Scan queued"}

class WalletInput(BaseModel):
    label:str
    address:str
    chain:str

@app.post("/api/wallets")
async def add_wallet(payload:WalletInput,authorization: str|None=Header(default=None)):
    user=await auth_user(authorization)
    address=payload.address.strip()
    if len(address)<10 or len(address)>128: raise HTTPException(400,"Invalid public wallet address")
    rows=await db_insert("wallets",{"owner_id":user["id"],"label":payload.label[:80],"address":address,"chain":payload.chain[:40]})
    return {"item":rows[0] if rows else None}

@app.get("/api/health/ready")
async def ready():
    return {"ready":bool(SUPABASE_URL and SUPABASE_ANON_KEY),"needs":["SUPABASE_SERVICE_ROLE_KEY","VAPID keys","owner authentication setup"] if not SUPABASE_SERVICE_ROLE_KEY or not VAPID_PUBLIC_KEY else []}
