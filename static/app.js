const map = L.map("map", { zoomControl: false, attributionControl: false }).setView([44.736, 37.738], 12);
L.control.zoom({ position: "bottomright" }).addTo(map);

L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', { maxZoom: 16 }).addTo(map);

const markersMap = {};
const nodesCache = {};
const fireConesLayer = L.layerGroup().addTo(map);

let weatherWindSpeed = 12;
let weatherWindDir = 45;
let selectedTag = null;
let currentIncidentId = null;
let isOperator = false;

// Авторизация
document.getElementById("loginBtn").addEventListener("click", () => {
  if (isOperator) {
    alert("Вы уже авторизованы.");
    return;
  }
  const pwd = prompt("Введите пароль доступа (пароль: admin):");
  if (pwd === "admin") {
    isOperator = true;
    document.getElementById("loginBtn").style.display = "none";
    document.getElementById("adminControls").classList.remove("hidden");
    document.getElementById("operatorTabBtn").classList.remove("hidden");
    document.getElementById("operatorTabBtn").click();
    alert("Доступ разрешен. Пульт дежурного активирован.");
  } else if (pwd !== null) {
    alert("Неверный пароль!");
  }
});

// Отрисовка конуса ветра
function drawCones() {
  fireConesLayer.clearLayers();
  Object.values(nodesCache).forEach(node => {
    if (node.status === "ТРЕВОГА") {
      const az = (weatherWindDir + 180) % 360;
      const rad = az * Math.PI / 180;
      const dist = 0.02; 
      const p1 = [node.lat, node.lng];
      const p2 = [node.lat + dist * Math.cos(rad - 0.3), node.lng + dist * Math.sin(rad - 0.3)];
      const p3 = [node.lat + dist * Math.cos(rad + 0.3), node.lng + dist * Math.sin(rad + 0.3)];
      
      L.polygon([p1, p2, p3], { color: "#dc2626", fillOpacity: 0.2, weight: 1 }).addTo(fireConesLayer);
      L.circle([node.lat, node.lng], { radius: 300, color: "#dc2626", fillOpacity: 0.5 }).addTo(fireConesLayer);
    }
  });
}

function updateNode(node) {
  nodesCache[node.node_id] = node;
  const isAlarm = node.status === "ТРЕВОГА";
  
  const icon = L.divIcon({
    className: "",
    html: `<div class="node-pin ${isAlarm ? 'alarm' : ''}"></div>`,
    iconSize: [16,16], iconAnchor: [8,8]
  });

  const popup = `<b>${node.name}</b><br>T: ${node.temp}°C | CO2: ${node.co2}<br>Ответственный: ${node.io_name}<br>Тел: ${node.io_phone}`;

  if (markersMap[node.node_id]) {
    markersMap[node.node_id].setIcon(icon);
    markersMap[node.node_id].setPopupContent(popup);
  } else {
    markersMap[node.node_id] = L.marker([node.lat, node.lng], {icon}).bindPopup(popup).addTo(map);
  }
  
  drawCones();
  updateTable();
}

function updateTable() {
  const list = Object.values(nodesCache);
  const alarms = list.filter(n => n.status === "ТРЕВОГА");
  
  document.getElementById("activeNodesCount").textContent = `${list.length}/10`;
  const stBadge = document.getElementById("networkStatusBadge");
  if (alarms.length > 0) {
    stBadge.textContent = `ТРЕВОГА (${alarms.length})`;
    stBadge.style.color = "var(--danger)";
  } else {
    stBadge.textContent = "НОРМА";
    stBadge.style.color = "var(--ok)";
  }

  document.getElementById("sectorsTable").innerHTML = list.map(n => `
    <div class="sec-row ${n.status === 'ТРЕВОГА' ? 'alarm' : ''}">
      <span><b>${n.name}</b><br><small style="color:#64748b">Отв: ${n.io_name} (${n.io_phone})</small></span>
      <span>${n.temp}°C | ${n.co2} ppm</span>
    </div>
  `).join("");
}

function addFeedItem(evt) {
  const feed = document.getElementById("publicEventFeed");
  const div = document.createElement("div");
  div.className = `feed-item ${evt.level === 'ALARM' ? 'alarm' : ''}`;
  div.innerHTML = `<span class="time">[${evt.timestamp} МСК]</span>${evt.message}`;
  feed.prepend(div);
}

// Теги выбора участка
document.querySelectorAll(".tag").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tag").forEach(b => b.classList.remove("selected"));
    btn.classList.add("selected");
    selectedTag = btn.dataset.sec;
    document.getElementById("citLoc").value = btn.textContent;
  });
});

// Отправка формы жителя
document.getElementById("citizenForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const data = {
    location_name: document.getElementById("citLoc").value,
    target_sector_id: selectedTag,
    description: "Сигнал от жителя"
  };
  await fetch("/api/citizen-report", { method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(data) });
  alert("Сигнал отправлен! Он опубликован в ленте и передан диспетчеру ЕДДС Новороссийска.");
  e.target.reset();
  document.querySelectorAll(".tag").forEach(b => b.classList.remove("selected"));
});

// Пульт оператора
function showIncident(inc) {
  currentIncidentId = inc.id;
  document.getElementById("dispatchCard").style.display = "block";
  document.getElementById("dispatchTarget").innerHTML = `<b>Локация:</b> ${inc.location_name}<br><b>Узел:</b> ${inc.nearest_node}`;
  document.getElementById("dispatchTele").innerHTML = `<b>Телеметрия:</b> ${inc.sensor_telemetry}`;
  document.getElementById("dispatchIOName").textContent = `Ответственный ИО: ${inc.io_name}`;
  document.getElementById("dispatchIOPhone").textContent = `Телефон: ${inc.io_phone}`;
}

document.getElementById("assignBtn").addEventListener("click", async () => {
  const unit = document.getElementById("rescueUnit").value;
  await fetch("/api/operator/dispatch", {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({ incident_id: currentIncidentId, assigned_unit: unit })
  });
  document.getElementById("dispatchCard").style.display = "none";
  alert("Наряд успешно направлен на участок.");
});

// Кнопки управления
document.getElementById("syncBtn").addEventListener("click", () => { window.location.reload(); });
document.getElementById("simulateBtn").addEventListener("click", () => fetch("/api/simulate-fire", { method: "POST" }));
document.getElementById("resetBtn").addEventListener("click", () => fetch("/api/reset", { method: "POST" }));

// Табы
document.querySelectorAll(".tab-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
    document.querySelectorAll(".tab-content").forEach(c => c.classList.remove("active"));
    btn.classList.add("active");
    document.getElementById(btn.dataset.tab).classList.add("active");
  });
});

// WebSocket с МСК погодой
function initWS() {
  const ws = new WebSocket(`${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.host}/ws`);
  ws.onmessage = (msg) => {
    const data = JSON.parse(msg.data);
    if (data.type === "init") {
      if (data.weather) {
        weatherWindSpeed = data.weather.wind_speed;
        weatherWindDir = data.weather.wind_direction;
        document.getElementById("weatherTemp").textContent = `${data.weather.temp}°C`;
        document.getElementById("weatherHum").textContent = `${data.weather.humidity}%`;
        document.getElementById("weatherWind").textContent = `${weatherWindSpeed} м/с (С-В)`;
      }
      data.nodes.forEach(updateNode);
      data.events.forEach(addFeedItem);
    } else if (data.type === "telemetry") {
      updateNode(data.node);
    } else if (data.type === "event") {
      addFeedItem(data);
    } else if (data.type === "new_incident") {
      showIncident(data.incident);
      if(!isOperator) alert("ВНИМАНИЕ: Зафиксирован инцидент в Новороссийске. Требуется проверка оператора!");
    }
  };
  ws.onclose = () => setTimeout(initWS, 3000);
}
initWS();

// 3D Модель
setTimeout(() => {
  const container = document.getElementById("node3dCanvas");
  if(!container) return;
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(40, container.clientWidth/container.clientHeight, 0.1, 100);
  camera.position.set(3, 2, 4);
  const renderer = new THREE.WebGLRenderer({alpha:true, antialias:true});
  renderer.setSize(container.clientWidth, container.clientHeight);
  container.appendChild(renderer.domElement);
  const controls = new THREE.OrbitControls(camera, renderer.domElement);
  controls.autoRotate = true;
  
  scene.add(new THREE.AmbientLight(0xffffff, 0.8));
  const light = new THREE.DirectionalLight(0xffffff, 0.5);
  light.position.set(2,5,3);
  scene.add(light);

  const body = new THREE.Mesh(new THREE.BoxGeometry(1.2, 1.8, 0.8), new THREE.MeshStandardMaterial({color: 0x334155}));
  const panel = new THREE.Mesh(new THREE.BoxGeometry(1.0, 0.1, 0.6), new THREE.MeshStandardMaterial({color: 0x0f172a}));
  panel.position.set(0, 0.95, 0);
  const antenna = new THREE.Mesh(new THREE.CylinderGeometry(0.03, 0.03, 1.2), new THREE.MeshStandardMaterial({color: 0x1e293b}));
  antenna.position.set(0.4, 1.5, -0.2);
  
  const group = new THREE.Group();
  group.add(body, panel, antenna);
  scene.add(group);

  function animate() { requestAnimationFrame(animate); controls.update(); renderer.render(scene, camera); }
  animate();
}, 500);
