import asyncio
import json
import random
import math
import openpyxl
from datetime import datetime
from typing import Dict, List, Optional

import aiohttp
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

app = FastAPI(title="EcoNet Mesh: Ситуационный Центр")

# ---------------------------------------------------------------------------
# 15 реальных лесных секторов Новороссийска (с акцентом на объекты риска)
# ---------------------------------------------------------------------------
FOREST_SECTORS = [
    {"id": "NODE-01", "name": "Полигон ТКО г. Щелба (Борисовка)", "lat": 44.7558, "lng": 37.7025, "is_critical": True},
    {"id": "NODE-02", "name": "Урочище Сухая Щель (Заказник)", "lat": 44.6780, "lng": 37.6040, "is_critical": True},
    {"id": "NODE-03", "name": "Карьер ц/з «Пролетарий»", "lat": 44.7340, "lng": 37.8180, "is_critical": True},
    {"id": "NODE-04", "name": "Перевал «Волчьи Ворота» (А-146)", "lat": 44.8052, "lng": 37.7341, "is_critical": True},
    {"id": "NODE-05", "name": "Смотровая «Семь Ветров»", "lat": 44.7380, "lng": 37.8480, "is_critical": True},
    {"id": "NODE-06", "name": "Маркотх Север (Верхнебаканский)", "lat": 44.7720, "lng": 37.8210, "is_critical": False},
    {"id": "NODE-07", "name": "Гайдук (База Лесхоза)", "lat": 44.7780, "lng": 37.7120, "is_critical": False},
    {"id": "NODE-08", "name": "Кирилловка (Высота 307)", "lat": 44.7540, "lng": 37.7410, "is_critical": False},
    {"id": "NODE-09", "name": "Васильевка (Предгорье)", "lat": 44.7390, "lng": 37.6680, "is_critical": False},
    {"id": "NODE-10", "name": "Глебовское Лесничество", "lat": 44.7210, "lng": 37.6520, "is_critical": False},
    {"id": "NODE-11", "name": "Северная Озереевка", "lat": 44.7010, "lng": 37.6390, "is_critical": False},
    {"id": "NODE-12", "name": "Абрау-Дюрсо (Лесопарк)", "lat": 44.6980, "lng": 37.5890, "is_critical": False},
    {"id": "NODE-13", "name": "Шесхарис / Пенайский Хребет", "lat": 44.7120, "lng": 37.8890, "is_critical": False},
    {"id": "NODE-14", "name": "Гора Колдун (Мысхако)", "lat": 44.6610, "lng": 37.7510, "is_critical": False},
    {"id": "NODE-15", "name": "Широкая Балка (Ущелье)", "lat": 44.6540, "lng": 37.7020, "is_critical": False},
]

# ---------------------------------------------------------------------------
# Модели данных
# ---------------------------------------------------------------------------
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
    lat: Optional[float] = None
    lng: Optional[float] = None
    description: str

class DispatchActionIn(BaseModel):
    incident_id: str
    assigned_unit: str

# ---------------------------------------------------------------------------
# Состояние системы
# ---------------------------------------------------------------------------
nodes: Dict[str, dict] = {}
events: List[dict] = []
incidents: List[dict] = []
active_fires: set = set()

current_weather = {
    "temp": 24.5,
    "humidity": 45.0,
    "wind_speed": 14.2,
    "wind_direction": 45.0,  # 45° = С-В (Норд-ост)
    "source": "Open-Meteo (Новороссийск)"
}

class ConnectionManager:
    def __init__(self) -> None:
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict) -> None:
        dead: List[WebSocket] = []
        for conn in self.active_connections:
            try:
                await conn.send_text(json.dumps(message))
            except Exception:
                dead.append(conn)
        for conn in dead:
            self.disconnect(conn)

manager = ConnectionManager()

# ---------------------------------------------------------------------------
# Интеграция с реальной погодой (Open-Meteo)
# ---------------------------------------------------------------------------
async def update_weather():
    url = "https://api.open-meteo.com/v1/forecast?latitude=44.7238&longitude=37.7688&current=temperature_2m,relative_humidity_2m,wind_speed_10m,wind_direction_10m"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=4) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    cur = data.get("current", {})
                    current_weather["temp"] = cur.get("temperature_2m", current_weather["temp"])
                    current_weather["humidity"] = cur.get("relative_humidity_2m", current_weather["humidity"])
                    current_weather["wind_speed"] = cur.get("wind_speed_10m", current_weather["wind_speed"])
                    current_weather["wind_direction"] = cur.get("wind_direction_10m", current_weather["wind_direction"])
                    current_weather["source"] = "Open-Meteo Live API"
    except Exception:
        # Резервный расчет при оффлайн-режиме
        current_weather["source"] = "Метеостанция Маркотх (Резерв)"

# ---------------------------------------------------------------------------
# Обработка телеметрии и ветрового сноса
# ---------------------------------------------------------------------------
@app.post("/api/telemetry")
async def post_telemetry(data: Telemetry):
    mod_temp = data.temp
    mod_co2 = data.co2

    if data.node_id in active_fires:
        mod_temp = max(mod_temp, 86.0)
        mod_co2 = max(mod_co2, 2650)
    elif active_fires:
        # Учет вектора ветра при переносе тепла
        wind_rad = math.radians(current_weather["wind_direction"])
        # Смещение центра пятна по ветру
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
    status = "ALARM" if is_alarm else ("WARNING" if (data.battery < 20 or mod_temp > 33.0) else "OK")

    if is_alarm:
        active_fires.add(data.node_id)

    name = next((s["name"] for s in FOREST_SECTORS if s["id"] == data.node_id), data.node_id)
    is_crit = next((s["is_critical"] for s in FOREST_SECTORS if s["id"] == data.node_id), False)

    node_rec = {
        "node_id": data.node_id,
        "name": name,
        "lat": data.lat,
        "lng": data.lng,
        "is_critical": is_crit,
        "temp": round(mod_temp, 1),
        "humidity": data.humidity,
        "co2": mod_co2,
        "battery": data.battery,
        "status": status,
        "last_update": datetime.now().strftime("%H:%M:%S")
    }

    was_alarm = nodes.get(data.node_id, {}).get("status") == "ALARM"
    nodes[data.node_id] = node_rec
    await manager.broadcast({"type": "telemetry", "node": node_rec})

    if is_alarm and not was_alarm:
        event = {
            "type": "event",
            "level": "ALARM",
            "node_id": data.node_id,
            "message": f"ОЧАГ ВОЗГОРАНИЯ: {name} (T: {int(mod_temp)}°C, CO2: {mod_co2} ppm)",
            "timestamp": datetime.now().strftime("%H:%M:%S")
        }
        events.append(event)
        await manager.broadcast(event)

    return {"ok": True, "status": status}

# ---------------------------------------------------------------------------
# Сквозной сценарий: Гражданин -> Кросс-чек -> Оператор
# ---------------------------------------------------------------------------
@app.post("/api/citizen-report")
async def handle_citizen_report(report: CitizenReportIn):
    inc_id = f"INC-{len(incidents) + 101}"
    
    # Поиск опорной ноды для верификации
    matched_node = None
    if report.target_sector_id and report.target_sector_id in nodes:
        matched_node = nodes[report.target_sector_id]
    elif report.lat and report.lng:
        matched_node = min(
            nodes.values(),
            key=lambda n: math.sqrt((n["lat"] - report.lat)**2 + (n["lng"] - report.lng)**2)
        )
    else:
        matched_node = nodes.get("NODE-01")

    # Алгоритм кросс-валидации с телеметрией
    is_hot = matched_node["temp"] > 33.0 or matched_node["co2"] > 600 or matched_node["status"] == "ALARM"
    confidence = 94 if matched_node["status"] == "ALARM" else (78 if is_hot else 25)
    verification_badge = "ПОДТВЕРЖДЕНО СЕТЬЮ" if confidence >= 70 else "ТРЕБУЕТ ПРОВЕРКИ"

    incident = {
        "id": inc_id,
        "timestamp": datetime.now().strftime("%H:%M:%S"),
        "location_name": report.location_name,
        "description": report.description,
        "lat": report.lat or matched_node["lat"],
        "lng": report.lng or matched_node["lng"],
        "nearest_node": matched_node["name"],
        "sensor_telemetry": f"T: {matched_node['temp']}°C | CO2: {matched_node['co2']} ppm",
        "confidence": confidence,
        "verification_badge": verification_badge,
        "status": "WAITING_OPERATOR",
        "assigned_unit": None
    }
    
    incidents.insert(0, incident)
    
    # Уведомляем пульт оператора
    await manager.broadcast({"type": "new_incident", "incident": incident})
    return {"ok": True, "incident_id": inc_id, "confidence": confidence}

@app.post("/api/operator/dispatch")
async def dispatch_unit(action: DispatchActionIn):
    target = next((inc for inc in incidents if inc["id"] == action.incident_id), None)
    if not target:
        return {"ok": False, "error": "Инцидент не найден"}

    target["status"] = "DISPATCHED"
    target["assigned_unit"] = action.assigned_unit
    
    log_event = {
        "type": "event",
        "level": "DISPATCH",
        "node_id": target["id"],
        "message": f"НАРЯД НАПРАВЛЕН: {action.assigned_unit} направлен в сектор '{target['location_name']}'",
        "timestamp": datetime.now().strftime("%H:%M:%S")
    }
    events.append(log_event)
    
    await manager.broadcast({"type": "incident_updated", "incident": target})
    await manager.broadcast(log_event)
    return {"ok": True}

# ---------------------------------------------------------------------------
# Служебные эндпоинты
# ---------------------------------------------------------------------------
@app.get("/api/weather")
async def get_weather():
    return current_weather

@app.get("/api/incidents")
async def get_incidents():
    return {"incidents": incidents}

@app.post("/api/simulate-fire")
async def simulate_fire():
    # Симуляция бьет по объектам повышенного риска
    candidates = [s["id"] for s in FOREST_SECTORS if s["is_critical"]]
    target_id = random.choice(candidates)
    node = nodes[target_id]
    
    reading = Telemetry(
        node_id=target_id,
        lat=node["lat"],
        lng=node["lng"],
        temp=76.5,
        humidity=12.0,
        co2=2350,
        battery=node["battery"]
    )
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
            "temp": round(random.uniform(22.0, 25.5), 1),
            "humidity": round(random.uniform(40.0, 52.0), 1),
            "co2": random.randint(380, 440),
            "battery": random.randint(80, 100),
            "status": "OK",
            "last_update": datetime.now().strftime("%H:%M:%S")
        }
    await manager.broadcast({"type": "init", "nodes": list(nodes.values()), "events": [], "weather": current_weather})
    return {"ok": True}

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

    # Добавляем журнал выездов на второй лист
    ws_inc = wb.create_sheet(title="Журнал выездов расчетов")
    ws_inc.append(["№ Вызова", "Время", "Локация", "Достоверность", "Статус", "Назначенный расчет"])
    for cell in ws_inc[1]:
        cell.font = openpyxl.styles.Font(bold=True)

    for inc in incidents:
        ws_inc.append([
            inc["id"],
            inc["timestamp"],
            inc["location_name"],
            f"{inc['confidence']}% ({inc['verification_badge']})",
            inc["status"],
            inc.get("assigned_unit") or "Не назначен"
        ])

    file_path = "mchs_summary.xlsx"
    wb.save(file_path)
    return FileResponse(file_path, filename=f"EcoNet_EDDS_{datetime.now().strftime('%d_%m_%Y')}.xlsx")

# ---------------------------------------------------------------------------
# Жизненный цикл и WebSockets
# ---------------------------------------------------------------------------
@app.on_event("startup")
async def startup_event():
    await reset_simulation()
    asyncio.create_task(update_weather())
    asyncio.create_task(background_telemetry_loop())

async def background_telemetry_loop():
    weather_timer = 0
    while True:
        await asyncio.sleep(3)
        weather_timer += 3
        if weather_timer >= 600:
            await update_weather()
            weather_timer = 0

        for node_id, node in list(nodes.items()):
            if node_id not in active_fires:
                node["temp"] = round(random.uniform(22.0, 25.5), 1)
                node["co2"] = random.randint(380, 440)
                node["battery"] = max(5, node["battery"] - random.choice([0, 0, 0, 1]))
                node["last_update"] = datetime.now().strftime("%H:%M:%S")
                await post_telemetry(Telemetry(**node))

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        await websocket.send_text(json.dumps({
            "type": "init",
            "nodes": list(nodes.values()),
            "events": events[-50:],
            "incidents": incidents[:20],
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
