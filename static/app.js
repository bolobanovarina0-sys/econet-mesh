const map = L.map("map", { zoomControl: false, attributionControl: false }).setView([44.736, 37.738], 12);
L.control.zoom({ position: "bottomright" }).addTo(map);

L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 16 }).addTo(map);

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
  if (isOperator) { alert("Вы уже авторизованы."); return; }
  const pwd = prompt("Введите пароль доступа сотрудника ЕДДС:");
  if (pwd === "admin") {
    isOperator = true;
    document.getElementById("loginBtn").style.display = "none";
    document.getElementById("adminControls").classList.remove("hidden");
    document.getElementById("operatorTabBtn").classList.remove("hidden");
    document.getElementById("operatorTabBtn").click();
    alert("Доступ разрешен. Пульт дежурного синхронизирован.");
    updateTable();
  } else if (pwd !== null) {
    alert("Неверный пароль!");
  }
});

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
      
      L.polygon([p1, p2, p3], { color: "#ef4444", fillOpacity: 0.25, weight: 1 }).addTo(fireConesLayer);
      L.circle([node.lat, node.lng], { radius: 300, color: "#ef4444", fillOpacity: 0.5 }).addTo(fireConesLayer);
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

  let popup = `<b>${node.name}</b><br>T: ${node.temp}°C | CO2: ${node.co2}`;
  if (isOperator) {
    popup += `<br><span style="color:#b45309">Отв: ${node.io_name} (${node.io_phone})</span>`;
  }

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
  
  document.getElementById("activeNodesCount").textContent = `${list.length} / 10`;
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
      <span><b>${n.name}</b><br><small style="color:var(--text-muted)">${isOperator ? 'Отв: ' + n.io_name + ' (' + n.io_phone + ')' : 'Сектор мониторинга ЕДДС'}</small></span>
      <span style="font-family:monospace">${n.temp}°C | ${n.co2}ppm</span>
    </div>
  `).join("");
}

function addFeedItem(evt) {
  const html = `<span class="time">[${evt.timestamp} МСК]</span>${evt.message}`;
  
  const feed = document.getElementById("publicEventFeed");
  if(feed) {
    const div = document.createElement("div");
    div.className = `event-item ${evt.level === 'ALARM' ? 'alarm' : ''}`;
    div.innerHTML = html;
    feed.prepend(div);
  }

  const opStream = document.getElementById("operatorEventStream");
  if(opStream) {
    const div = document.createElement("div");
    div.className = `event-item ${evt.level === 'ALARM' ? 'alarm' : ''}`;
    div.innerHTML = html;
    opStream.prepend(div);
  }
}

// Теги выбора
document.querySelectorAll(".tag-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tag-btn").forEach(b => b.style.borderColor = "var(--border-color)");
    btn.style.borderColor = "var(--primary)";
    selectedTag = btn.dataset.sec;
    document.getElementById("citLoc").value = btn.textContent;
  });
});

// Отправка формы
document.getElementById("citizenForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const data = {
    location_name: document.getElementById("citLoc").value,
    target_sector_id: selectedTag,
    description: "Сигнал от жителя"
  };
  await fetch("/api/citizen-report", { method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(data) });
  alert("Сигнал передан в ЕДДС Новороссийск. Проверено по регламенту ст. 19.13 КоАП РФ.");
  e.target.reset();
  document.querySelectorAll(".tag-btn").forEach(b => b.style.borderColor = "var(--border-color)");
});

// Синхронизация инцидента на пульте
function showIncident(inc) {
  currentIncidentId = inc.id;
  const card = document.getElementById("dispatchCard");
  const noText = document.getElementById("noIncidentText");
  if(card) card.style.display = "block";
  if(noText) noText.style.display = "none";
  
  document.getElementById("dispatchTarget").innerHTML = `<b>Локация:</b> ${inc.location_name} (Узел: ${inc.nearest_node})`;
  document.getElementById("dispatchTele").innerHTML = `<b>Телеметрия:</b> ${inc.sensor_telemetry}`;
  document.getElementById("dispatchIO").innerHTML = `Ответственный ИО: <b>${inc.io_name}</b> (${inc.io_phone})`;
}

document.getElementById("assignBtn").addEventListener("click", async () => {
  if (!currentIncidentId) return;
  const unit = document.getElementById("rescueUnit").value;
  await fetch("/api/operator/dispatch", {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({ incident_id: currentIncidentId, assigned_unit: unit })
  });
  document.getElementById("dispatchCard").style.display = "none";
  document.getElementById("noIncidentText").style.display = "block";
  alert("Оперативный наряд успешно направлен.");
  currentIncidentId = null;
});

// Кнопки управления
document.getElementById("syncBtn").addEventListener("click", () => { window.location.reload(); });
document.getElementById("simulateBtn").addEventListener("click", () => fetch("/api/simulate-fire", { method: "POST" }));
document.getElementById("resetBtn").addEventListener("click", () => fetch("/api/reset", { method: "POST" }));
document.getElementById("exportExcelBtn").addEventListener("click", () => window.open("/api/export", "_blank"));

// Табы
document.querySelectorAll(".role-tab").forEach(tab => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".role-tab").forEach(t => t.classList.remove("active"));
    document.querySelectorAll(".tab-view").forEach(v => v.classList.remove("active"));
    tab.classList.add("active");
    document.getElementById(tab.dataset.tab).classList.add("active");
    if (tab.dataset.tab === "hardwareTab" && window.onResizeThree) window.onResizeThree();
  });
});

// WebSocket с полной синхронизацией
function initWS() {
  const ws = new WebSocket(`${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.host}/ws`);
  ws.onmessage = (msg) => {
    const data = JSON.parse(msg.data);
    if (data.type === "init") {
      if (data.weather) {
        weatherWindSpeed = data.weather.wind_speed;
        weatherWindDir = data.weather.wind_direction;
        document.getElementById("weatherDisplay").textContent = `${data.weather.temp}°C | ${data.weather.humidity}% | С-В (Норд-ост), ${weatherWindSpeed} м/с`;
      }
      data.nodes.forEach(updateNode);
      data.events.forEach(addFeedItem);
      if (data.incidents && data.incidents.length > 0) {
        const activeInc = data.incidents.find(i => i.status === "ОЖИДАЕТ" || i.status === "WAITING_OPERATOR");
        if (activeInc) showIncident(activeInc);
      }
    } else if (data.type === "telemetry") {
      updateNode(data.node);
    } else if (data.type === "event") {
      addFeedItem(data);
    } else if (data.type === "new_incident") {
      showIncident(data.incident);
      if(!isOperator) alert("ВНИМАНИЕ: Поступил экстренный вызов в Новороссийске! Требуется вход сотрудника.");
    }
  };
  ws.onclose = () => setTimeout(initWS, 3000);
}
initWS();

// 3D Модель
setTimeout(() => {
  const container = document.getElementById("node3dCanvas");
  if(!container || typeof THREE === "undefined") return;

  const w = container.clientWidth || 350;
  const h = container.clientHeight || 220;

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(40, w / h, 0.1, 100);
  camera.position.set(3, 2, 4);

  const renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true });
  renderer.setSize(w, h);
  container.appendChild(renderer.domElement);

  const controls = new THREE.OrbitControls(camera, renderer.domElement);
  controls.autoRotate = true;

  scene.add(new THREE.AmbientLight(0xffffff, 0.9));
  const light = new THREE.DirectionalLight(0xffffff, 1.2);
  light.position.set(3, 5, 4);
  scene.add(light);

  const group = new THREE.Group();
  const body = new THREE.Mesh(new THREE.BoxGeometry(1.2, 1.8, 0.8), new THREE.MeshStandardMaterial({color: 0x334155, roughness:0.4}));
  const panel = new THREE.Mesh(new THREE.BoxGeometry(1.0, 0.08, 0.6), new THREE.MeshStandardMaterial({color: 0x0f172a, metalness:0.8}));
  panel.position.set(0, 0.95, 0);
  const antenna = new THREE.Mesh(new THREE.CylinderGeometry(0.03, 0.03, 1.2), new THREE.MeshStandardMaterial({color: 0x1e293b}));
  antenna.position.set(0.4, 1.5, -0.2);

  group.add(body, panel, antenna);
  scene.add(group);

  function animate() { requestAnimationFrame(animate); controls.update(); renderer.render(scene, camera); }
  animate();

  window.onResizeThree = () => {
    const nw = container.clientWidth;
    const nh = container.clientHeight;
    if(nw && nh) {
      camera.aspect = nw / nh;
      camera.updateProjectionMatrix();
      renderer.setSize(nw, nh);
    }
  };
}, 600);
