import asyncio
import json
import random
import math
import openpyxl
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional

import aiohttp
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from ai_model import predict_fire_risk

app = FastAPI(title="АПК ЭкоСеть (Новороссийск)")

MSK = timezone(timedelta(hours=3), name="MSK")

def get_msk_time():
    return datetime.now(MSK).strftime("%H:%M:%S")

FOREST_SECTORS = [
    {"id": "УЗЕЛ-01", "name": "Полигон г. Щелба", "lat": 44.7558, "lng": 37.7025, "is_critical": True, "io_name": "Иванов А.В.", "io_phone": "+7 (928) 111-22-33"},
    {"id": "УЗЕЛ-02", "name": "Сухая Щель", "lat": 44.6780, "lng": 37.6040, "is_critical": True, "io_name": "Петров С.Н.", "io_phone": "+7 (928) 222-33-44"},
    {"id": "УЗЕЛ-03", "name": "Карьер Пролетарий", "lat": 44.7340, "lng": 37.8180, "is_critical": True, "io_name": "Смирнов Д.И.", "io_phone": "+7 (928) 333-44-55"},
    {"id": "УЗЕЛ-04", "name": "Волчьи Ворота", "lat": 44.8052, "lng": 37.7341, "is_critical": True, "io_name": "Кузнецов В.П.", "io_phone": "+7 (928) 444-55-66"},
    {"id": "УЗЕЛ-05", "name": "Семь Ветров", "lat": 44.7380, "lng": 37.8480, "is_critical": True, "io_name": "Соколов И.А.", "io_phone": "+7 (928) 555-66-77"},
    {"id": "УЗЕЛ-06", "name": "Маркотх Север", "lat": 44.7720, "lng": 37.8210, "is_critical": False, "io_name": "Попов Алексей", "io_phone": "+7 (918) 123-00-11"},
    {"id": "УЗЕЛ-07", "name": "Гайдук (База)", "lat": 44.7780, "lng": 37.7120, "is_critical": False, "io_name": "Волков М.Д.", "io_phone": "+7 (918) 123-00-22"},
    {"id": "УЗЕЛ-08", "name": "Кирилловка", "lat": 44.7540, "lng": 37.7410, "is_critical": False, "io_name": "Лебедев К.С.", "io_phone": "+7 (918) 123-00-33"},
    {"id": "УЗЕЛ-09", "name": "Васильевка", "lat": 44.7390, "lng": 37.6680, "is_critical": False, "io_name": "Новиков А.А.", "io_phone": "+7 (918) 123-00-44"},
    {"id": "УЗЕЛ-10", "name": "Глебовское", "lat": 44.7210, "lng": 37.6520, "is_critical": False, "io_name": "Морозов П.И.", "io_phone": "+7 (918) 123-00-55"},
]

class Telemetry(BaseModel):
    node_id: str
    lat: float
    lng: float
    temp: float
    humidity: float
    co2: int
    battery: int

class CitizenReportIn(BaseModel):
    location_name: str
    target_sector_id: Optional[str] = None
    description: str

class DispatchActionIn(BaseModel):
    incident_id: str
    assigned_unit: str

class RejectActionIn(BaseModel):
    incident_id: str
    reason: str = "Ложный вызов (проверено по телеметрии)"

nodes: Dict[str, dict] = {}
events: List[dict] = []
incidents: List[dict] = []
active_fires: set = set()

likes_db = {"count": 184, "voted_ips": set()}

current_weather = {
    "temp": 26.5,
    "humidity": 42.0,
    "wind_speed": 14.0,
    "wind_direction": 45.0,
}

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active_connections.append(ws)

    def disconnect(self, ws: WebSocket):
        if ws in self.active_connections:
            self.active_connections.remove(ws)

    async def broadcast(self, message: dict):
        dead = []
        for conn in self.active_connections:
            try:
                await conn.send_text(json.dumps(message))
            except Exception:
                dead.append(conn)
        for conn in dead:
            self.disconnect(conn)

manager = ConnectionManager()

async def update_weather():
    url = "https://api.open-meteo.com/v1/forecast?latitude=44.7238&longitude=37.7688&current=temperature_2m,relative_humidity_2m,wind_speed_10m,wind_direction_10m&wind_speed_unit=ms"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=5) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    cur = data.get("current", {})
                    current_weather["temp"] = cur.get("temperature_2m", current_weather["temp"])
                    current_weather["humidity"] = cur.get("relative_humidity_2m", current_weather["humidity"])
                    current_weather["wind_speed"] = cur.get("wind_speed_10m", current_weather["wind_speed"])
                    current_weather["wind_direction"] = cur.get("wind_direction_10m", current_weather["wind_direction"])
    except Exception as e:
        print("Ошибка погоды:", e)

@app.get("/api/ai-forecast")
async def get_ai_forecast():
    ai_res = predict_fire_risk(
        temp=current_weather["temp"],
        humidity=current_weather["humidity"],
        wind_speed=current_weather["wind_speed"]
    )
    mchs_warning = f"⚠️ ГУ МЧС по Краснодарскому краю: В МО г. Новороссийск действует экстренное предупреждение. Модель ИИ [{ai_res['model_info']}] фиксирует повышенный риск из-за норд-оста ({current_weather['wind_speed']} м/с)."
    return {
        "risk_level": ai_res["risk_level"],
        "mchs_text": mchs_warning,
        "hours": ai_res["hours"],
        "trends": ai_res["trends"],
        "model_info": ai_res["model_info"]
    }

@app.get("/api/likes")
async def get_likes(request: Request):
    client_ip = request.client.host
    already_voted = client_ip in likes_db["voted_ips"]
    return {"count": likes_db["count"], "voted": already_voted}

@app.post("/api/like")
async def post_like(request: Request):
    client_ip = request.client.host
    if client_ip in likes_db["voted_ips"]:
        return {"ok": False, "message": "Вы уже поддержали проект с этого IP!", "count": likes_db["count"]}
    likes_db["voted_ips"].add(client_ip)
    likes_db["count"] += 1
    return {"ok": True, "count": likes_db["count"]}

@app.post("/api/telemetry")
async def post_telemetry(data: Telemetry):
    mod_temp = data.temp
    mod_co2 = data.co2

    if data.node_id in active_fires:
        mod_temp = max(mod_temp, 86.0)
        mod_co2 = max(mod_co2, 2650)
    elif active_fires:
        wind_rad = math.radians(current_weather["wind_direction"])
        wind_vector_x = -math.sin(wind_rad) * (current_weather["wind_speed"] / 1000.0)
        wind_vector_y = -math.cos(wind_rad) * (current_weather["wind_speed"] / 1000.0)

        for fire_id in active_fires:
            if fire_id in nodes:
                f_node = nodes[fire_id]
                eff_fire_lat = f_node["lat"] + wind_vector_y
                eff_fire_lng = f_node["lng"] + wind_vector_x
                dist = math.sqrt((data.lat - eff_fire_lat)**2 + (data.lng - eff_fire_lng)**2)
                if dist < 0.035:
                    heat = (0.035 - dist) * 750
                    mod_temp += heat * 1.8
                    mod_co2 += int(heat * 45)

    is_alarm = mod_temp > 48.0 or (mod_temp > 36.0 and mod_co2 > 950)
    status = "ТРЕВОГА" if is_alarm else ("ВНИМАНИЕ" if data.battery < 20 else "НОРМА")

    if is_alarm:
        active_fires.add(data.node_id)

    sector = next((s for s in FOREST_SECTORS if s["id"] == data.node_id), None)
    node_rec = {
        "node_id": data.node_id,
        "name": sector["name"] if sector else data.node_id,
        "lat": data.lat,
        "lng": data.lng,
        "is_critical": sector["is_critical"] if sector else False,
        "temp": round(mod_temp, 1),
        "co2": mod_co2,
        "humidity": data.humidity,
        "battery": data.battery,
        "status": status,
        "io_name": sector["io_name"] if sector else "Не назначен",
        "io_phone": sector["io_phone"] if sector else "-",
    }

    was_alarm = nodes.get(data.node_id, {}).get("status") == "ТРЕВОГА"
    nodes[data.node_id] = node_rec
    await manager.broadcast({"type": "telemetry", "node": node_rec})

    if is_alarm and not was_alarm:
        event = {
            "type": "event",
            "level": "ALARM",
            "message": f"КРИТИЧЕСКИЙ РОСТ ТЕМПЕРАТУРЫ: {node_rec['name']} (T: {int(mod_temp)}°C)",
            "timestamp": get_msk_time()
        }
        events.append(event)
        await manager.broadcast(event)

    return {"ok": True}

@app.post("/api/citizen-report")
async def handle_citizen_report(report: CitizenReportIn):
    inc_id = f"ОБР-{len(incidents) + 101}"
    matched_node = nodes.get(report.target_sector_id) or nodes.get("УЗЕЛ-01")

    public_event = {
        "type": "event",
        "level": "CITIZEN",
        "message": f"Сигнал от жителя: {report.location_name} ({report.description}). Проверка телеметрии.",
        "timestamp": get_msk_time()
    }
    events.append(public_event)
    await manager.broadcast(public_event)

    incident = {
        "id": inc_id,
        "timestamp": get_msk_time(),
        "location_name": report.location_name,
        "nearest_node": matched_node["name"],
        "sensor_telemetry": f"T: {matched_node['temp']}°C | CO2: {matched_node['co2']} ppm",
        "io_name": matched_node["io_name"],
        "io_phone": matched_node["io_phone"],
        "status": "ОЖИДАЕТ",
    }
    incidents.insert(0, incident)
    await manager.broadcast({"type": "new_incident", "incident": incident})
    return {"ok": True}

@app.post("/api/operator/dispatch")
async def dispatch_unit(action: DispatchActionIn):
    target = next((inc for inc in incidents if inc["id"] == action.incident_id), None)
    if target:
        target["status"] = "ВЫПОЛНЯЕТСЯ"
        log = {
            "type": "event",
            "level": "DISPATCH",
            "message": f"ОПЕРАТИВНОЕ РЕАГИРОВАНИЕ: {action.assigned_unit} направлен в сектор '{target['location_name']}'",
            "timestamp": get_msk_time()
        }
        events.append(log)
        await manager.broadcast({"type": "incident_updated", "incident": target})
        await manager.broadcast(log)
    return {"ok": True}

@app.post("/api/operator/reject")
async def reject_incident(action: RejectActionIn):
    target = next((inc for inc in incidents if inc["id"] == action.incident_id), None)
    if target:
        target["status"] = "ОТКЛОНЕН (ЛОЖНЫЙ)"
        log = {
            "type": "event",
            "level": "INFO",
            "message": f"ОТКЛОНЕН ВЫЗОВ № {target['id']} ({target['location_name']}): {action.reason}",
            "timestamp": get_msk_time()
        }
        events.append(log)
        await manager.broadcast({"type": "incident_updated", "incident": target})
        await manager.broadcast(log)
    return {"ok": True}

@app.post("/api/simulate-fire")
async def simulate_fire():
    candidates = [s["id"] for s in FOREST_SECTORS if s["is_critical"]]
    target_id = random.choice(candidates)
    node = nodes[target_id]
    reading = Telemetry(node_id=target_id, lat=node["lat"], lng=node["lng"], temp=75.0, humidity=12.0, co2=2350, battery=node["battery"])
    return await post_telemetry(reading)

@app.post("/api/reset")
async def reset_simulation():
    active_fires.clear()
    events.clear()
    incidents.clear()
    for s in FOREST_SECTORS:
        nodes[s["id"]] = {
            "node_id": s["id"],
            "name": s["name"],
            "lat": s["lat"],
            "lng": s["lng"],
            "is_critical": s["is_critical"],
            "temp": round(random.uniform(22.0, 25.0), 1),
            "humidity": round(random.uniform(40.0, 50.0), 1),
            "co2": random.randint(380, 420),
            "battery": random.randint(80, 100),
            "status": "НОРМА",
            "io_name": s["io_name"],
            "io_phone": s["io_phone"]
        }
    await manager.broadcast({"type": "init", "nodes": list(nodes.values()), "events": [], "incidents": incidents, "weather": current_weather})
    return {"ok": True}

@app.get("/api/export-pdf/{incident_id}")
async def export_incident_pdf(incident_id: str):
    target = next((inc for inc in incidents if inc["id"] == incident_id), None)
    if not target:
        target = incidents[0] if incidents else {
            "id": "ОБР-101",
            "timestamp": get_msk_time(),
            "location_name": "Полигон ТКО г. Щелба",
            "nearest_node": "Полигон ТКО г. Щелба",
            "sensor_telemetry": "T: 75°C | CO2: 2350 ppm",
            "io_name": "Иванов А.В.",
            "io_phone": "+7 (928) 111-22-33"
        }

    pdf_content = f"""
    КУРСОВАЯ / ПРОЕКТНАЯ СВОДКА ЕДДС-112
    АПК «ЭкоСеть» — МО город Новороссийск
    --------------------------------------------------
    ОФИЦИАЛЬНЫЙ АКТ РЕАГИРОВАНИЯ НА ИНЦИДЕНТ № {target['id']}
    Время фиксации: {target['timestamp']} МСК
    
    1. ДАННЫЕ ОБЪЕКТА И ЛОКАЦИИ:
       - Наименование: {target['location_name']}
       - Ближайший датчик LoRa-mesh: {target['nearest_node']}
       - Телеметрия узла: {target['sensor_telemetry']}
       - Роза ветров (Маркотх): Северо-Восточный (Норд-ост), {current_weather['wind_speed']} м/с
    
    2. ОПЕРАТИВНЫЙ СТАТУС:
       - Статус реагирования: {target['status']}
       - Ответственный дежурный инспектор (ИО): {target['io_name']} ({target['io_phone']})
    
    3. ЗАКЛЮЧЕНИЕ СИТУАЦИОННОГО ЦЕНТРА:
       Параметры подтверждены автоматическим комплексом раннего обнаружения. 
       Наряд задействован согласно регламенту межведомственного взаимодействия.
       
    --------------------------------------------------
    Документ сформирован автоматически в системе АПК «ЭкоСеть».
    Электронная подпись оператора ЕДДС действительна.
    """
    return Response(
        content=pdf_content.encode("utf-8"),
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename=Akt_KCHS_{target['id']}.txt"}
    )

@app.get("/api/export")
async def export_excel():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Сводка ЕДДС Новороссийск"
    
    ws.append(["ID", "Сектор / Объект", "Категория", "Статус", "T (°C)", "CO2 (ppm)", "Влажность", "Заряд"])
    for cell in ws[1]:
        cell.font = openpyxl.styles.Font(bold=True)
    
    for s in nodes.values():
        ws.append([
            s["node_id"],
            s["name"],
            "Объект риска" if s["is_critical"] else "Лесной массив",
            s["status"],
            s["temp"],
            s["co2"],
            f"{s['humidity']}%",
            f"{s['battery']}%"
        ])

    ws_inc = wb.create_sheet(title="Журнал выездов расчетов")
    ws_inc.append(["№ Вызова", "Время", "Локация", "Статус"])
    for cell in ws_inc[1]:
        cell.font = openpyxl.styles.Font(bold=True)

    for inc in incidents:
        ws_inc.append([
            inc["id"],
            inc["timestamp"],
            inc["location_name"],
            inc["status"]
        ])

    file_path = "mchs_summary.xlsx"
    wb.save(file_path)
    return FileResponse(file_path, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", filename=f"EcoNet_EDDS_{datetime.now().strftime('%d_%m_%Y')}.xlsx")

@app.on_event("startup")
async def startup_event():
    await reset_simulation()
    asyncio.create_task(background_loop())

async def background_loop():
    weather_timer = 0
    while True:
        await asyncio.sleep(4)
        weather_timer += 4
        
        if weather_timer >= 300:
            await update_weather()
            weather_timer = 0

        if not active_fires and random.random() < 0.02:
            await simulate_fire()

        for node_id, node in list(nodes.items()):
            if node_id not in active_fires:
                node["temp"] = round(random.uniform(22.0, 25.0), 1)
                node["battery"] = max(5, node["battery"] - random.choice([0, 0, 0, 1]))
                await post_telemetry(Telemetry(**node))

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        await websocket.send_text(json.dumps({
            "type": "init",
            "nodes": list(nodes.values()),
            "events": events[-40:],
            "incidents": incidents,
            "weather": current_weather
        }))
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)

@app.get("/")
async def index():
    return FileResponse("static/index.html")

app.mount("/static", StaticFiles(directory="static"), name="static")
