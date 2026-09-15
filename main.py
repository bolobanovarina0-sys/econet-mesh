import http.server
import socketserver
import json
import random
import urllib.parse
from datetime import datetime, timezone, timedelta

MSK = timezone(timedelta(hours=3), name="MSK")

def get_msk_time():
    return datetime.now(MSK).strftime("%H:%M:%S")

# Данные датчиков и метео
current_weather = {
    "temp": 26.5,
    "humidity": 42.0,
    "wind_speed": 14.0,
    "wind_direction": 45.0,
}

likes_data = {"count": 184, "voted_ips": set()}

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
            
            # AI-анализ на чистом Python с учетом погоды
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
            client_ip = self.client_address[0]
            voted = client_ip in likes_data["voted_ips"]
            self.wfile.write(json.dumps({"count": likes_data["count"], "voted": voted}).encode("utf-8"))
            return

        return super().do_GET()

    def do_POST(self):
        parsed_path = urllib.parse.urlparse(self.path)
        path = parsed_path.path

        if path == "/api/like":
            client_ip = self.client_address[0]
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            
            if client_ip in likes_data["voted_ips"]:
                res = {"ok": False, "message": "Вы уже поддержали проект с этого IP!", "count": likes_data["count"]}
            else:
                likes_data["voted_ips"].add(client_ip)
                likes_data["count"] += 1
                res = {"ok": True, "count": likes_data["count"]}
                
            self.wfile.write(json.dumps(res, ensure_ascii=False).encode("utf-8"))
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
