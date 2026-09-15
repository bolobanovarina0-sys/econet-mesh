import http.server
import socketserver
import json
import random
import urllib.parse
import os
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

current_weather = {
    "temp": 26.5,
    "humidity": 42.0,
    "wind_speed": 14.0,
    "wind_direction": 45.0,
}

class SimpleAPIHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        parsed_path = urllib.parse.urlparse(self.path)
        path = parsed_path.path

        if path == "/" or path == "":
            self.path = "/static/index.html"
            return super().do_GET()
        
        elif path == "/api/ai-forecast":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            
            temp = current_weather["temp"]
            hum = current_weather["humidity"]
            wind = current_weather["wind_speed"]
            
            risk = min(98.5, max(15.0, (temp * 1.5) + (wind * 2.3) - (hum * 0.55)))
            hours = ["Сейчас", "+1 ч", "+2 ч", "+3 ч", "+4 ч", "+5 ч", "+6 ч"]
            trends = [round(min(99.0, max(10.0, risk + random.uniform(-3, 3))), 1) for _ in hours]
            category = "КРИТИЧЕСКИЙ (IV класс)" if risk > 75 else ("ПОВЫШЕННЫЙ (III класс)" if risk > 45 else "СТАБИЛЬНЫЙ")
            
            response_data = {
                "risk_level": round(risk, 1),
                "risk_category": category,
                "mchs_text": f"⚠️ ГУ МЧС по Краснодарскому краю: Действует экстренное предупреждение. ИИ фиксирует риск {round(risk,1)}% из-за норд-оста ({wind} м/с).",
                "hours": hours,
                "trends": trends,
                "model_info": "FWI-ML Python Native Engine v2.4",
                "factors": {
                    "wind_impact": min(100, int(wind * 6)),
                    "dryness_impact": min(100, int((100 - hum) * 1.1)),
                    "temp_impact": min(100, int(temp * 2.5))
                }
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

        elif path == "/api/reset-likes":
            likes_count = 0
            voted_ips = set()
            save_likes(likes_count, voted_ips)
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": True, "count": 0}).encode("utf-8"))
            return

        elif path == "/api/citizen-report" or path == "/api/simulate-fire" or path == "/api/reset":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": True}).encode("utf-8"))
            return

        self.send_response(404)
        self.end_headers()

if __name__ == "__main__":
    PORT = 10000
    with socketserver.TCPServer(("0.0.0.0", PORT), SimpleAPIHandler) as httpd:
        print(f"Сервер АПК ЭкоСеть запущен на порту {PORT}")
        httpd.serve_forever()
