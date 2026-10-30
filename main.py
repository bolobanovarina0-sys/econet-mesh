import http.server
import socketserver
import json
import random
import urllib.parse
import os
import threading
import time
from datetime import datetime, timezone, timedelta

MSK = timezone(timedelta(hours=3), name="MSK")

def get_msk_time():
    return datetime.now(MSK).strftime("%H:%M:%S")

LIKES_FILE = "likes.json"

def load_likes():
    if os.path.exists(LIKES_FILE):
        try:
            with open(LIKES_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("count", 0), set(data.get("voted_ips", []))
        except Exception:
            pass
    return 0, set()

def save_likes(count, voted_ips):
    try:
        with open(LIKES_FILE, "w", encoding="utf-8") as f:
            json.dump({"count": count, "voted_ips": list(voted_ips)}, f)
    except Exception:
        pass

likes_count, voted_ips = load_likes()

# Базовые значения для старта (Новороссийск, активный норд-ост)
CURRENT_WEATHER = {
    "temp": 28.5,
    "humidity": 38.0,
    "wind_speed": 16.0,
    "wind_direction": 45.0,
}

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

nodes_state = {}
events_list = []
incidents_list = []
active_fires = set()

def reset_simulation_state():
    active_fires.clear()
    events_list.clear()
    incidents_list.clear()
    events_list.append({
        "level": "INFO",
        "message": "Система АПК «ЭкоСеть» инициализирована. Опрос LoRa-периметра активен.",
        "timestamp": get_msk_time()
    })
    for s in FOREST_SECTORS:
        nodes_state[s["id"]] = {
            "node_id": s["id"],
            "name": s["name"],
            "lat": s["lat"],
            "lng": s["lng"],
            "is_critical": s["is_critical"],
            "temp": round(CURRENT_WEATHER["temp"] + random.uniform(-1, 1), 1),
            "humidity": round(CURRENT_WEATHER["humidity"] + random.uniform(-2, 2), 1),
            "co2": random.randint(380, 420),
            "battery": random.randint(85, 100),
            "status": "НОРМА",
            "io_name": s["io_name"],
            "io_phone": s["io_phone"]
        }

reset_simulation_state()

def background_simulation_loop():
    global CURRENT_WEATHER
    while True:
        time.sleep(3) # Обновляем телеметрию каждые 3 секунды
        
        # 1. Живая симуляция метеоусловий (микро-колебания для презентации)
        CURRENT_WEATHER["temp"] = round(CURRENT_WEATHER["temp"] + random.uniform(-0.3, 0.3), 1)
        CURRENT_WEATHER["humidity"] = round(max(20.0, min(100.0, CURRENT_WEATHER["humidity"] + random.uniform(-1.0, 1.0))), 1)
        CURRENT_WEATHER["wind_speed"] = round(max(5.0, CURRENT_WEATHER["wind_speed"] + random.uniform(-0.5, 0.5)), 1)
        
        # Возврат к средним значениям, чтобы показатели не улетели в бесконечность
        if CURRENT_WEATHER["temp"] > 33.0: CURRENT_WEATHER["temp"] -= 0.5
        if CURRENT_WEATHER["temp"] < 25.0: CURRENT_WEATHER["temp"] += 0.5
        if CURRENT_WEATHER["wind_speed"] > 22.0: CURRENT_WEATHER["wind_speed"] -= 0.5
        if CURRENT_WEATHER["wind_speed"] < 12.0: CURRENT_WEATHER["wind_speed"] += 0.5

        # 2. Спонтанные возгорания
        if not active_fires and random.random() < 0.02:
            criticals = [s["id"] for s in FOREST_SECTORS if s["is_critical"]]
            target = random.choice(criticals)
            active_fires.add(target)
            nodes_state[target]["temp"] = 82.5
            nodes_state[target]["co2"] = 2450
            nodes_state[target]["status"] = "ТРЕВОГА"
            msg = f"КРИТИЧЕСКИЙ РОСТ ТЕМПЕРАТУРЫ: {nodes_state[target]['name']} (T: 82°C)"
            events_list.insert(0, {"level": "ALARM", "message": msg, "timestamp": get_msk_time()})

        # 3. Обновление датчиков
        for node_id, node in nodes_state.items():
            if node_id not in active_fires:
                # Датчики дышат вместе с погодой
                node["temp"] = round(CURRENT_WEATHER["temp"] + random.uniform(-1.5, 1.5), 1)
                node["battery"] = max(5, node["battery"] - random.choice([0, 0, 0, 1]))

threading.Thread(target=background_simulation_loop, daemon=True).start()

def get_dynamic_weather():
    # Если пожар, резко ухудшаем локальную погоду (растет температура и разгоняется ветер)
    is_alarm = any(n["status"] == "ТРЕВОГА" for n in nodes_state.values())
    if is_alarm:
        return {
            "temp": round(CURRENT_WEATHER["temp"] + 5.5, 1),
            "humidity": max(15.0, round(CURRENT_WEATHER["humidity"] - 15.0, 1)),
            "wind_speed": round(CURRENT_WEATHER["wind_speed"] + 6.0, 1),
            "wind_direction": 45.0,
        }
    return CURRENT_WEATHER

class FullAPIHandler(http.server.SimpleHTTPRequestHandler):
    def translate_path(self, path):
        if path.startswith("/api/"):
            return path
        if path == "/" or path == "":
            path = "/index.html"
        base_dir = os.path.join(os.getcwd(), "static")
        return os.path.join(base_dir, path.lstrip("/"))

    def do_GET(self):
        parsed_path = urllib.parse.urlparse(self.path)
        path = parsed_path.path

        if path == "/api/state":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            data = {
                "nodes": list(nodes_state.values()),
                "events": events_list[:40],
                "incidents": incidents_list,
                "weather": get_dynamic_weather()
            }
            self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))
            return

        elif path == "/api/ai-forecast":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            
            weather = get_dynamic_weather()
            temp = weather["temp"]
            hum = weather["humidity"]
            wind = weather["wind_speed"]
            
            # Динамический расчет риска от реальных текущих показателей
            risk = min(99.9, max(15.0, (temp * 1.6) + (wind * 2.5) - (hum * 0.4)))
            hours = ["Сейчас", "+1 ч", "+2 ч", "+3 ч", "+4 ч", "+5 ч", "+6 ч"]
            trends = [round(min(99.0, max(10.0, risk + random.uniform(-4, 4))), 1) for _ in hours]
            category = "КРИТИЧЕСКИЙ (IV класс)" if risk > 75 else ("ПОВЫШЕННЫЙ (III класс)" if risk > 45 else "СТАБИЛЬНЫЙ")
            
            response_data = {
                "risk_level": round(risk, 1),
                "risk_category": category,
                "mchs_text": f"⚠️ МЧС: Действует предупреждение. ИИ фиксирует динамический риск {round(risk,1)}% (ветер: {wind} м/с, t: {temp}°C).",
                "hours": hours,
                "trends": trends,
                "model_info": "FWI-ML Python Native Engine v2.4"
            }
            self.wfile.write(json.dumps(response_data, ensure_ascii=False).encode("utf-8"))
            return

        elif path == "/api/likes":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            forwarded = self.headers.get("X-Forwarded-For")
            client_ip = forwarded.split(",")[0].strip() if forwarded else self.client_address[0]
            voted = client_ip in voted_ips
            self.wfile.write(json.dumps({"count": likes_count, "voted": voted}).encode("utf-8"))
            return

        return super().do_GET()

    def do_POST(self):
        global likes_count, voted_ips
        parsed_path = urllib.parse.urlparse(self.path)
        path = parsed_path.path

        if path == "/api/like":
            forwarded = self.headers.get("X-Forwarded-For")
            client_ip = forwarded.split(",")[0].strip() if forwarded else self.client_address[0]
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            if client_ip in voted_ips:
                res = {"ok": False, "message": "Вы уже поддержали проект с этого IP-адреса!", "count": likes_count}
            else:
                voted_ips.add(client_ip)
                likes_count += 1
                save_likes(likes_count, voted_ips)
                res = {"ok": True, "count": likes_count}
            self.wfile.write(json.dumps(res, ensure_ascii=False).encode("utf-8"))
            return

        elif path == "/api/simulate-fire":
            criticals = [s["id"] for s in FOREST_SECTORS if s["is_critical"]]
            target = random.choice(criticals)
            active_fires.add(target)
            nodes_state[target]["temp"] = 85.0
            nodes_state[target]["co2"] = 2950
            nodes_state[target]["status"] = "ТРЕВОГА"
            msg = f"ЭКСТРЕННАЯ СИМУЛЯЦИЯ: Зафиксировано возгорание в секторе '{nodes_state[target]['name']}'"
            events_list.insert(0, {"level": "ALARM", "message": msg, "timestamp": get_msk_time()})
            inc_id = f"ОБР-{len(incidents_list) + 101}"
            incidents_list.insert(0, {
                "id": inc_id,
                "timestamp": get_msk_time(),
                "location_name": nodes_state[target]["name"],
                "nearest_node": nodes_state[target]["name"],
                "sensor_telemetry": "T: 85°C | CO2: 2950 ppm",
                "io_name": nodes_state[target]["io_name"],
                "io_phone": nodes_state[target]["io_phone"],
                "status": "ОЖИДАЕТ"
            })
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": True}).encode("utf-8"))
            return

        elif path == "/api/reset":
            reset_simulation_state()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": True}).encode("utf-8"))
            return

        elif path == "/api/citizen-report":
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length).decode('utf-8')
            try:
                data = json.loads(body)
            except:
                data = {"location_name": "Неизвестно", "description": "Сигнал"}
            inc_id = f"ОБР-{len(incidents_list) + 101}"
            matched = nodes_state.get("УЗЕЛ-01")
            incidents_list.insert(0, {
                "id": inc_id,
                "timestamp": get_msk_time(),
                "location_name": data.get("location_name", "Склон горы"),
                "nearest_node": matched["name"],
                "sensor_telemetry": f"T: {matched['temp']}°C | CO2: {matched['co2']} ppm",
                "io_name": matched["io_name"],
                "io_phone": matched["io_phone"],
                "status": "ОЖИДАЕТ"
            })
            events_list.insert(0, {
                "level": "CITIZEN",
                "message": f"Сигнал от жителя: {data.get('location_name')} ({data.get('description')}).",
                "timestamp": get_msk_time()
            })
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": True}).encode("utf-8"))
            return

        elif path == "/api/operator/dispatch" or path == "/api/operator/reject":
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length).decode('utf-8')
            try:
                data = json.loads(body)
                inc_id = data.get("incident_id")
                for inc in incidents_list:
                    if inc["id"] == inc_id:
                        inc["status"] = "ВЫПОЛНЯЕТСЯ" if "dispatch" in path else "ОТКЛОНЕН (ЛОЖНЫЙ)"
            except:
                pass
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": True}).encode("utf-8"))
            return

        self.send_response(404)
        self.end_headers()

if __name__ == "__main__":
    PORT = int(os.environ.get("PORT", 10000))
    with socketserver.TCPServer(("0.0.0.0", PORT), FullAPIHandler) as httpd:
        print(f"Сервер запущен на порту {PORT}")
        httpd.serve_forever()
