import asyncio
import json
import random
import math
import openpyxl
from datetime import datetime
from typing import Dict, List

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

app = FastAPI(title="EcoNet Mesh")

# ---------------------------------------------------------------------------
# In-memory state
# ---------------------------------------------------------------------------
nodes: Dict[str, dict] = {}
events: List[dict] = []
active_fires: set = set()

class Telemetry(BaseModel):
    node_id: str
    lat: float
    lng: float
    temp: float
    humidity: float
    co2: int
    battery: int

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
        for connection in self.active_connections:
            try:
                await connection.send_text(json.dumps(message))
            except Exception:
                dead.append(connection)
        for connection in dead:
            self.disconnect(connection)

manager = ConnectionManager()

def detect_fire(temp: float, co2: int) -> bool:
    return temp > 45 or (temp > 35 and co2 > 1000)

def battery_status(battery: int) -> str:
    if battery < 20:
        return "WARNING"
    return "OK"

# ---------------------------------------------------------------------------
# REST endpoints
# ---------------------------------------------------------------------------
@app.post("/api/telemetry")
async def post_telemetry(data: Telemetry):
    mod_temp = data.temp
    mod_co2 = data.co2

    if data.node_id in active_fires:
        mod_temp = max(mod_temp, 85.0)
        mod_co2 = max(mod_co2, 2500)
    elif active_fires:
        for fire_id in active_fires:
            if fire_id in nodes:
                f_node = nodes[fire_id]
                dist = math.sqrt((data.lat - f_node["lat"])**2 + (data.lng - f_node["lng"])**2)
                if dist < 0.015:
                    heat_multiplier = (0.015 - dist) * 1000
                    mod_temp += heat_multiplier * 2
                    mod_co2 += int(heat_multiplier * 50)

    is_fire = detect_fire(mod_temp, mod_co2)
    status = "ALARM" if is_fire else battery_status(data.battery)

    if is_fire:
        active_fires.add(data.node_id)

    node_record = {
        "node_id": data.node_id,
        "lat": data.lat,
        "lng": data.lng,
        "temp": mod_temp,
        "humidity": data.humidity,
        "co2": mod_co2,
        "battery": data.battery,
        "status": status,
        "last_update": datetime.utcnow().isoformat(),
    }

    was_alarm_before = nodes.get(data.node_id, {}).get("status") == "ALARM"
    nodes[data.node_id] = node_record

    payload = {"type": "telemetry", "node": node_record}
    await manager.broadcast(payload)

    if is_fire and not was_alarm_before:
        event = {
            "type": "event",
            "level": "ALARM",
            "node_id": data.node_id,
            "message": f"Обнаружено возгорание на ноде {data.node_id} (T: {int(mod_temp)}°C)",
            "timestamp": datetime.utcnow().strftime("%H:%M:%S"),
        }
        events.append(event)
        await manager.broadcast(event)

    return {"ok": True, "status": status}

@app.get("/api/nodes")
async def get_nodes():
    return {"nodes": list(nodes.values()), "count": len(nodes)}

@app.get("/api/events")
async def get_events():
    return {"events": events}

@app.post("/api/simulate-fire")
async def simulate_fire():
    if not nodes:
        return {"ok": False, "message": "Нет активных нод"}
    node_id = random.choice(list(nodes.keys()))
    node = nodes[node_id]
    fake_reading = Telemetry(
        node_id=node_id,
        lat=node["lat"],
        lng=node["lng"],
        temp=60.0,
        humidity=15.0,
        co2=2000,
        battery=node["battery"],
    )
    result = await post_telemetry(fake_reading)
    return {"ok": True, "node_id": node_id, "result": result}

@app.get("/api/export")
async def export_excel():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Телеметрия лесничества"
    headers = ["ID Датчика", "Статус", "Температура (°C)", "CO2 (ppm)", "Влажность (%)", "Батарея (%)"]
    ws.append(headers)
    for cell in ws[1]:
        cell.font = openpyxl.styles.Font(bold=True)
    for col in ['A', 'B', 'C', 'D', 'E', 'F']:
        ws.column_dimensions[col].width = 18
    for node in nodes.values():
        ws.append([
            node["node_id"], 
            node["status"], 
            round(node["temp"], 1), 
            node["co2"], 
            node["humidity"], 
            node["battery"]
        ])
    file_path = "report.xlsx"
    wb.save(file_path)
    return FileResponse(
        file_path, 
        media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 
        filename=f"EcoNet_Report_{datetime.now().strftime('%d%m%Y')}.xlsx"
    )

# ---------------------------------------------------------------------------
# Background Simulator (Автоматически запускается вместе с сервером)
# ---------------------------------------------------------------------------
@app.on_event("startup")
async def startup_event():
    asyncio.create_task(background_simulator())

async def background_simulator():
    BASE_LAT = 44.7238
    BASE_LNG = 37.7688
    SPREAD = 0.03
    
    virtual_nodes = []
    for i in range(15):
        virtual_nodes.append({
            "node_id": f"NODE-{i+1:02d}",
            "lat": BASE_LAT + random.uniform(-SPREAD, SPREAD),
            "lng": BASE_LNG + random.uniform(-SPREAD, SPREAD),
            "battery": random.randint(60, 100)
        })
    
    while True:
        await asyncio.sleep(random.uniform(2, 3))
        for v_node in virtual_nodes:
            # Имитация разряда батареи
            v_node["battery"] = max(5, v_node["battery"] - random.choice([0, 0, 0, 1]))
            
            reading = Telemetry(
                node_id=v_node["node_id"],
                lat=v_node["lat"],
                lng=v_node["lng"],
                temp=round(random.uniform(18, 25), 1),
                humidity=round(random.uniform(40, 60), 1),
                co2=random.randint(350, 450),
                battery=v_node["battery"]
            )
            # Отправляем данные напрямую в обработчик
            await post_telemetry(reading)

# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        await websocket.send_text(json.dumps({
            "type": "init",
            "nodes": list(nodes.values()),
            "events": events[-50:],
        }))
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)

# ---------------------------------------------------------------------------
# Static frontend
# ---------------------------------------------------------------------------
@app.get("/")
async def index():
    return FileResponse("static/index.html")

app.mount("/static", StaticFiles(directory="static"), name="static")