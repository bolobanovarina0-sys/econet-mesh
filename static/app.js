/* ==========================================================================
   EcoNet Mesh: Ситуационный Центр — Frontend Logic (Leaflet, Three.js, WS)
   ========================================================================== */

// --------------------------------------------------------------------------
// 1. Инициализация геоинформационной подсистемы (Leaflet)
// --------------------------------------------------------------------------
const BASE_CENTER = [44.736, 37.738];
const map = L.map("map", {
  zoomControl: false,
  attributionControl: false
}).setView(BASE_CENTER, 12);

L.control.zoom({ position: "bottomright" }).addTo(map);

// Подложка карты: Esri Dark Canvas
L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}", {
  maxZoom: 16
}).addTo(map);

// Слой для отрисовки динамических зон опасности и ветра
const fireConesLayer = L.layerGroup().addTo(map);
const markersMap = {};
const nodesCache = {};
let currentActiveIncident = null;
let selectedTagSectorId = null;

let weatherState = {
  wind_speed: 14.2,
  wind_direction: 45.0, // 45° = С-В (Норд-ост)
  temp: 24.5
};

// --------------------------------------------------------------------------
// 2. Расчет аэродинамического сектора сноса пламени (Конус опасности)
// --------------------------------------------------------------------------
function calculateWindCone(centerLat, centerLng, windFromDeg, windSpeed) {
  // Ветер дует "ОТКУДА" (windFromDeg). Пламя и дым сносит в противоположную сторону (+180°)
  const targetAzimuth = (windFromDeg + 180) % 360;
  const spreadHalfAngle = 28; // Угол раскрытия факела рассеивания (градусы)
  
  // Дистанция поражения зависит от скорости ветра (14 м/с ~ 3.2 км опасной зоны)
  const distanceKm = Math.min(4.5, Math.max(1.2, (windSpeed * 0.22)));
  const earthRadiusKm = 6371.0;

  function getOffsetPoint(lat, lng, azimuthDeg, distKm) {
    const rad = (azimuthDeg * Math.PI) / 180;
    const dLat = (distKm / earthRadiusKm) * (180 / Math.PI);
    const dLng = ((distKm / earthRadiusKm) * (180 / Math.PI)) / Math.cos((lat * Math.PI) / 180);
    return [lat + dLat * Math.cos(rad), lng + dLng * Math.sin(rad)];
  }

  const leftAzimuth = targetAzimuth - spreadHalfAngle;
  const rightAzimuth = targetAzimuth + spreadHalfAngle;

  const leftPoint = getOffsetPoint(centerLat, centerLng, leftAzimuth, distanceKm);
  const midPoint = getOffsetPoint(centerLat, centerLng, targetAzimuth, distanceKm * 1.15);
  const rightPoint = getOffsetPoint(centerLat, centerLng, rightAzimuth, distanceKm);

  return [[centerLat, centerLng], leftPoint, midPoint, rightPoint];
}

function renderFireZones() {
  fireConesLayer.clearLayers();
  
  Object.values(nodesCache).forEach((node) => {
    if (node.status === "ALARM") {
      const coneCoords = calculateWindCone(
        node.lat,
        node.lng,
        weatherState.wind_direction,
        weatherState.wind_speed
      );

      // Отрисовка сектора ветра
      L.polygon(coneCoords, {
        color: "#dc2626",
        fillColor: "#ef4444",
        fillOpacity: 0.28,
        weight: 1.5,
        dashArray: "5, 5"
      }).addTo(fireConesLayer).bindTooltip(`Зона ветрового сноса: ${node.name} (Норд-ост ${weatherState.wind_speed} м/с)`, {
        sticky: true,
        className: "leaflet-tooltip-dark"
      });

      // Ореол непосредственного очага
      L.circle([node.lat, node.lng], {
        radius: 350,
        color: "#f87171",
        fillColor: "#dc2626",
        fillOpacity: 0.6,
        weight: 2
      }).addTo(fireConesLayer);
    }
  });
}

// --------------------------------------------------------------------------
// 3. Управление маркерами датчиков
// --------------------------------------------------------------------------
function createMarkerIcon(status, isCritical) {
  let statusClass = "ok";
  if (status === "ALARM") statusClass = "alarm";
  else if (status === "WARNING") statusClass = "warning";

  const hubClass = isCritical ? "critical-hub" : "";
  return L.divIcon({
    className: "custom-node-icon",
    html: `<div class="node-pin ${statusClass} ${hubClass}"></div>`,
    iconSize: [16, 16],
    iconAnchor: [8, 8]
  });
}

function buildPopupHTML(node) {
  const catLabel = node.is_critical ? "⚠️ Объект критического риска" : "Лесной массив";
  return `
    <div style="font-family: var(--font-sans); font-size: 12px; color: #fff; line-height: 1.45;">
      <div style="font-weight: 700; color: #38bdf8; font-size: 13px;">${node.name}</div>
      <div style="font-size: 10px; color: #94a3b8; margin-bottom: 6px;">${catLabel} • ID: ${node.node_id}</div>
      <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 4px 10px; background: #0b111b; padding: 6px 8px; border-radius: 4px; border: 1px solid #1e293b;">
        <span>Температура:</span><b style="color: #fff;">${node.temp}°C</b>
        <span>CO2 (пиролиз):</span><b style="color: #fff;">${node.co2} ppm</b>
        <span>Влажность:</span><b>${node.humidity}%</b>
        <span>Питание:</span><b>${node.battery}%</b>
      </div>
      <div style="margin-top: 6px; font-size: 11px; text-align: right;">
        Статус: <b style="color: ${node.status === 'ALARM' ? '#f87171' : '#34d399'}">${node.status}</b>
      </div>
    </div>
  `;
}

function upsertNode(node) {
  nodesCache[node.node_id] = node;
  const existing = markersMap[node.node_id];

  if (existing) {
    existing.setIcon(createMarkerIcon(node.status, node.is_critical));
    existing.setLatLng([node.lat, node.lng]);
    existing.setPopupContent(buildPopupHTML(node));
  } else {
    const marker = L.marker([node.lat, node.lng], {
      icon: createMarkerIcon(node.status, node.is_critical)
    }).addTo(map);
    marker.bindPopup(buildPopupHTML(node));
    markersMap[node.node_id] = marker;
  }

  updateDashboardSummary();
  renderFireZones();
}

function updateDashboardSummary() {
  const list = Object.values(nodesCache);
  const alarms = list.filter((n) => n.status === "ALARM");
  
  const statusBadge = document.getElementById("networkStatusBadge");
  const countBadge = document.getElementById("activeNodesCount");
  
  if (countBadge) countBadge.textContent = `${list.length} / 15`;

  if (alarms.length > 0) {
    statusBadge.textContent = `ТРЕВОГА (${alarms.length} ОЧАГОВ)`;
    statusBadge.style.color = "var(--danger)";
  } else {
    statusBadge.textContent = "ДЕЖУРНЫЙ РЕЖИМ";
    statusBadge.style.color = "var(--ok)";
  }

  // Обновление таблицы секторов
  const tableEl = document.getElementById("sectorsListTable");
  if (tableEl) {
    tableEl.innerHTML = list.map((n) => `
      <div class="sector-row ${n.is_critical ? 'critical' : ''} ${n.status === 'ALARM' ? 'alarm' : ''}">
        <span class="sector-row__name">${n.name}</span>
        <span class="sector-row__vals">${n.temp}°C • ${n.co2} ppm • ${n.battery}%</span>
      </div>
    `).join("");
  }
}

// --------------------------------------------------------------------------
// 4. Сквозной сценарий диспетчера ЕДДС и карточка реагирования
// --------------------------------------------------------------------------
function displayIncidentOnConsole(inc) {
  currentActiveIncident = inc;
  const dispatchCard = document.getElementById("dispatchCard");
  const dispatchTarget = document.getElementById("dispatchTarget");
  const dispatchConfidence = document.getElementById("dispatchConfidence");
  const badge = document.getElementById("operatorIncidentBadge");

  badge.textContent = "ТРЕВОГА";
  badge.className = "gov-pill alert";

  dispatchTarget.textContent = `Локация: ${inc.location_name} (Опорный узел: ${inc.nearest_node})`;
  dispatchConfidence.innerHTML = `
    Достоверность: <strong>${inc.confidence}%</strong> (${inc.verification_badge})<br>
    Телеметрия датчика: ${inc.sensor_telemetry}
  `;
  dispatchCard.style.display = "block";
}

document.getElementById("assignUnitBtn").addEventListener("click", async () => {
  if (!currentActiveIncident) return;

  const unit = document.getElementById("rescueUnitSelect").value;
  const btn = document.getElementById("assignUnitBtn");
  btn.disabled = true;
  btn.textContent = "Передача координат...";

  try {
    const res = await fetch("/api/operator/dispatch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ incident_id: currentActiveIncident.id, assigned_unit: unit })
    });

    if (res.ok) {
      document.getElementById("dispatchCard").style.display = "none";
      document.getElementById("operatorIncidentBadge").textContent = "НАРЯД НАПРАВЛЕН";
      document.getElementById("operatorIncidentBadge").className = "gov-pill ok-pill";
      currentActiveIncident = null;
    }
  } catch (e) {
    alert("Сбой передачи наряда оперативным службам.");
  } finally {
    btn.disabled = false;
    btn.textContent = "Подтвердить и направить наряд";
  }
});

// --------------------------------------------------------------------------
// 5. Гражданский контур (Модальное окно и ст. 19.13 КоАП РФ)
// --------------------------------------------------------------------------
const citizenForm = document.getElementById("citizenSmokeForm");
const legalModal = document.getElementById("confirmLegalModal");
const modalCancelBtn = document.getElementById("modalCancelBtn");
const modalConfirmBtn = document.getElementById("modalConfirmBtn");
let pendingCitizenReport = null;

// Быстрые теги секторов повышенного риска
document.querySelectorAll(".tag-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tag-btn").forEach((b) => (b.style.borderColor = "var(--border-dim)"));
    btn.style.borderColor = "#38bdf8";
    selectedTagSectorId = btn.dataset.sec;
    document.getElementById("citizenLocInput").value = btn.textContent.trim();
  });
});

citizenForm.addEventListener("submit", (e) => {
  e.preventDefault();
  pendingCitizenReport = {
    location_name: document.getElementById("citizenLocInput").value.trim(),
    target_sector_id: selectedTagSectorId,
    description: document.getElementById("citizenDescInput").value.trim()
  };
  legalModal.style.display = "flex";
});

modalCancelBtn.addEventListener("click", () => {
  legalModal.style.display = "none";
  pendingCitizenReport = null;
});

modalConfirmBtn.addEventListener("click", async () => {
  if (!pendingCitizenReport) return;
  modalConfirmBtn.disabled = true;
  modalConfirmBtn.textContent = "Отправка...";

  try {
    const res = await fetch("/api/citizen-report", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(pendingCitizenReport)
    });
    
    if (res.ok) {
      legalModal.style.display = "none";
      citizenForm.reset();
      selectedTagSectorId = null;
      document.querySelectorAll(".tag-btn").forEach((b) => (b.style.borderColor = "var(--border-dim)"));
      alert("Сигнал передан дежурному диспетчеру ЕДДС Новороссийска. Данные верифицируются по радиосети.");
    }
  } catch (err) {
    alert("Ошибка сети. Попробуйте снова.");
  } finally {
    modalConfirmBtn.disabled = false;
    modalConfirmBtn.textContent = "Подтверждаю отправку";
    pendingCitizenReport = null;
  }
});

// --------------------------------------------------------------------------
// 6. Журнал событий реального времени
// --------------------------------------------------------------------------
function addEventStreamItem(evt) {
  const streamEl = document.getElementById("operatorEventStream");
  const placeholder = streamEl.querySelector(".empty-placeholder");
  if (placeholder) placeholder.remove();

  const item = document.createElement("div");
  let entryClass = "event-item";
  if (evt.level === "ALARM") entryClass += " alarm";
  if (evt.level === "DISPATCH") entryClass += " dispatch";
  if (evt.level === "CITIZEN") entryClass += " citizen";

  item.className = entryClass;
  item.innerHTML = `
    <span class="event-item__time">${evt.timestamp}</span>
    <div class="event-item__msg">${evt.message}</div>
  `;
  streamEl.prepend(item);
}

// WEBSOCKET
function initWS() {
  const ws = new WebSocket(`${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.host}/ws`);
  ws.onmessage = (msg) => {
    const data = JSON.parse(msg.data);
    if (data.type === "init") {
      if (data.weather) {
        weatherWindSpeed = data.weather.wind_speed;
        weatherWindDir = data.weather.wind_direction;
        
        // Заполняем виджет погоды
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
      if(!isOperator) alert("ВНИМАНИЕ: Поступил новый сигнал по Новороссийску. Требуется авторизация оператора!");
    }
  };
  ws.onclose = () => setTimeout(initWS, 3000);
}
initWS();
// Служебные кнопки
document.getElementById("simulateBtn").addEventListener("click", () => fetch("/api/simulate-fire", { method: "POST" }));
document.getElementById("resetBtn").addEventListener("click", () => fetch("/api/reset", { method: "POST" }));
document.getElementById("exportExcelBtn").addEventListener("click", () => window.open("/api/export", "_blank"));

// --------------------------------------------------------------------------
// 8. Переключение табов ролей
// --------------------------------------------------------------------------
document.querySelectorAll(".role-tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".role-tab").forEach((t) => t.classList.remove("active"));
    document.querySelectorAll(".tab-view").forEach((v) => v.classList.remove("active"));
    
    tab.classList.add("active");
    const activeView = document.getElementById(tab.dataset.tab);
    activeView.classList.add("active");

    // При открытии вкладки с 3D обновляем размеры рендера Three.js
    if (tab.dataset.tab === "hardwareTab" && window.onResizeThree) {
      window.onResizeThree();
    }
  });
});

// --------------------------------------------------------------------------
// 9. Процедурная 3D-визуализация узла EcoNet-Node v1.2 (Three.js)
// --------------------------------------------------------------------------
function initHardware3D() {
  const container = document.getElementById("node3dCanvas");
  if (!container || typeof THREE === "undefined") return;

  const width = container.clientWidth || 400;
  const height = container.clientHeight || 270;

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(40, width / height, 0.1, 100);
  camera.position.set(3.2, 2.4, 4.0);

  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setSize(width, height);
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  container.appendChild(renderer.domElement);

  const controls = new THREE.OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.05;
  controls.autoRotate = true;
  controls.autoRotateSpeed = 1.2;
  controls.maxDistance = 8;
  controls.minDistance = 2;

  // Освещение (промышленный студийный свет)
  const ambLight = new THREE.AmbientLight(0xffffff, 0.9);
  scene.add(ambLight);

  const keyLight = new THREE.DirectionalLight(0x38bdf8, 1.8);
  keyLight.position.set(4, 5, 3);
  scene.add(keyLight);

  const rimLight = new THREE.DirectionalLight(0xffffff, 1.2);
  rimLight.position.set(-4, -2, -3);
  scene.add(rimLight);

  const nodeGroup = new THREE.Group();

  // Материалы
  const casingMaterial = new THREE.MeshStandardMaterial({
    color: 0x1a2332,
    roughness: 0.35,
    metalness: 0.2
  });

  const panelMaterial = new THREE.MeshStandardMaterial({
    color: 0x091322,
    roughness: 0.15,
    metalness: 0.85
  });

  const antennaMaterial = new THREE.MeshStandardMaterial({
    color: 0x0f172a,
    roughness: 0.6,
    metalness: 0.4
  });

  const goldMaterial = new THREE.MeshStandardMaterial({
    color: 0xd97706,
    roughness: 0.3,
    metalness: 0.9
  });

  // 1. Основной корпус (ASA пластик, гермобокс IP67)
  const bodyGeo = new THREE.BoxGeometry(1.6, 2.0, 0.9);
  const bodyMesh = new THREE.Mesh(bodyGeo, casingMaterial);
  nodeGroup.add(bodyMesh);

  // 2. Солнечная монокристаллическая панель на верхней грани
  const panelGeo = new THREE.BoxGeometry(1.4, 0.05, 0.75);
  const panelMesh = new THREE.Mesh(panelGeo, panelMaterial);
  panelMesh.position.set(0, 1.02, 0);
  nodeGroup.add(panelMesh);

  // 3. Латунный разъем SMA антенны
  const smaGeo = new THREE.CylinderGeometry(0.08, 0.08, 0.16, 16);
  const smaMesh = new THREE.Mesh(smaGeo, goldMaterial);
  smaMesh.position.set(0.55, 1.08, -0.25);
  nodeGroup.add(smaMesh);

  // 4. Гибкая антенна LoRa 868 МГц
  const antGeo = new THREE.CylinderGeometry(0.04, 0.05, 1.6, 16);
  const antMesh = new THREE.Mesh(antGeo, antennaMaterial);
  antMesh.position.set(0.55, 1.9, -0.25);
  nodeGroup.add(antMesh);

  // 5. Вентиляционный лабиринт забора проб воздуха (BME280 / CCS811)
  const ventGeo = new THREE.CylinderGeometry(0.35, 0.35, 0.22, 24);
  const ventMesh = new THREE.Mesh(ventGeo, casingMaterial);
  ventMesh.position.set(0, -1.08, 0);
  nodeGroup.add(ventMesh);

  // 6. Индикатор состояния сети (LED)
  const ledGeo = new THREE.SphereGeometry(0.06, 16, 16);
  const ledMat = new THREE.MeshBasicMaterial({ color: 0x10b981 });
  const ledMesh = new THREE.Mesh(ledGeo, ledMat);
  ledMesh.position.set(0.6, 0.7, 0.46);
  nodeGroup.add(ledMesh);

  scene.add(nodeGroup);

  function animate() {
    requestAnimationFrame(animate);
    controls.update();
    renderer.render(scene, camera);
  }
  animate();

  window.onResizeThree = () => {
    const w = container.clientWidth;
    const h = container.clientHeight;
    if (w && h) {
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.setSize(w, h);
    }
  };

  window.addEventListener("resize", window.onResizeThree);
}

// Запуск Three.js после загрузки DOM
window.addEventListener("DOMContentLoaded", () => {
  setTimeout(initHardware3D, 200);
});
