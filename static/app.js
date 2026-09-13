const BASE_LAT = 44.7238;
const BASE_LNG = 37.7688;

const map = L.map("map", {
  zoomControl: true,
}).setView([BASE_LAT, BASE_LNG], 13);

// Отключаем стандартный копирайт с флагом, ставим название проекта
map.attributionControl.setPrefix('EcoNet Mesh Project'); 

// Подключаем премиальную тёмную карту Esri (без водяных знаков)
L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}', {
    attribution: '&copy; Esri',
    maxZoom: 16
}).addTo(map);

const markers = {}; // node_id -> { marker, circle }

const nodeCountEl = document.getElementById("nodeCount");
const alarmCountEl = document.getElementById("alarmCount");
const eventLogEl = document.getElementById("eventLog");
const connDot = document.getElementById("connDot");
const connText = document.getElementById("connText");
const simulateBtn = document.getElementById("simulateBtn");

function statusColor(status) {
  if (status === "ALARM") return "#ff3b5c";
  if (status === "WARNING") return "#ffb020";
  return "#00ff9d";
}

function buildPopupContent(node) {
  return `
    <div class="node-popup__title">${node.node_id}</div>
    <div class="node-popup__row"><span>Температура</span><span>${node.temp}°C</span></div>
    <div class="node-popup__row"><span>CO2</span><span>${node.co2} ppm</span></div>
    <div class="node-popup__row"><span>Влажность</span><span>${node.humidity}%</span></div>
    <div class="node-popup__row"><span>Батарея</span><span>${node.battery}%</span></div>
    <div class="node-popup__row"><span>Статус</span><span>${node.status}</span></div>
  `;
}

function upsertNode(node) {
  const color = statusColor(node.status);
  const existing = markers[node.node_id];

  if (node.status === "ALARM") {
    const icon = L.divIcon({
      className: "",
      html: `<div class="fire-marker"><div class="fire-marker__pulse"></div><div class="fire-marker__core"></div></div>`,
      iconSize: [16, 16],
      iconAnchor: [8, 8],
    });

    if (existing) {
      existing.marker.setIcon(icon);
      existing.marker.setLatLng([node.lat, node.lng]);
      existing.marker.setPopupContent(buildPopupContent(node));
    } else {
      const marker = L.marker([node.lat, node.lng], { icon }).addTo(map);
      marker.bindPopup(buildPopupContent(node));
      markers[node.node_id] = { marker };
    }
  } else {
    if (existing) {
      existing.marker.setStyle
        ? existing.marker.setStyle({ color, fillColor: color })
        : null;
      if (existing.marker.setLatLng) existing.marker.setLatLng([node.lat, node.lng]);
      existing.marker.setPopupContent(buildPopupContent(node));

      // If it was previously an alarm divIcon marker, replace with circle marker
      if (!(existing.marker instanceof L.CircleMarker)) {
        map.removeLayer(existing.marker);
        const circle = L.circleMarker([node.lat, node.lng], {
          radius: 8,
          color,
          fillColor: color,
          fillOpacity: 0.8,
          weight: 2,
        }).addTo(map);
        circle.bindPopup(buildPopupContent(node));
        markers[node.node_id] = { marker: circle };
      }
    } else {
      const circle = L.circleMarker([node.lat, node.lng], {
        radius: 8,
        color,
        fillColor: color,
        fillOpacity: 0.8,
        weight: 2,
      }).addTo(map);
      circle.bindPopup(buildPopupContent(node));
      markers[node.node_id] = { marker: circle };
    }
  }

  refreshCounts();
}

function refreshCounts() {
  const nodeIds = Object.keys(markers);
  nodeCountEl.textContent = nodeIds.length;
  // alarm count is tracked separately via nodesState
  const alarmCount = Object.values(nodesState).filter((n) => n.status === "ALARM").length;
  alarmCountEl.textContent = alarmCount;
}

const nodesState = {}; // node_id -> latest node data

function addEvent(evt) {
  const emptyMsg = eventLogEl.querySelector(".event-log__empty");
  if (emptyMsg) emptyMsg.remove();

  const item = document.createElement("div");
  item.className = "event-item";
  item.innerHTML = `
    <span class="event-item__time">${evt.timestamp}</span>
    <span class="event-item__msg">${evt.message}</span>
  `;
  eventLogEl.appendChild(item);
  eventLogEl.scrollTop = eventLogEl.scrollHeight;
}

function connectWebSocket() {
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${protocol}://${window.location.host}/ws`);

  ws.onopen = () => {
    connDot.className = "conn-dot connected";
    connText.textContent = "Подключено";
  };

  ws.onclose = () => {
    connDot.className = "conn-dot disconnected";
    connText.textContent = "Отключено — переподключение...";
    setTimeout(connectWebSocket, 2000);
  };

  ws.onerror = () => {
    ws.close();
  };

  ws.onmessage = (event) => {
    const data = JSON.parse(event.data);

    if (data.type === "init") {
      data.nodes.forEach((node) => {
        nodesState[node.node_id] = node;
        upsertNode(node);
      });
      data.events.forEach((evt) => addEvent(evt));
    } else if (data.type === "telemetry") {
      nodesState[data.node.node_id] = data.node;
      upsertNode(data.node);
    } else if (data.type === "event") {
      addEvent(data);
    }
  };
}

simulateBtn.addEventListener("click", async () => {
  simulateBtn.disabled = true;
  simulateBtn.textContent = "ЗАПУСК...";
  try {
    await fetch("/api/simulate-fire", { method: "POST" });
  } catch (err) {
    console.error("Ошибка симуляции пожара:", err);
  } finally {
    setTimeout(() => {
      simulateBtn.disabled = false;
      simulateBtn.textContent = "🔥 ТЕСТ: СИМУЛЯЦИЯ ПОЖАРА";
    }, 3000);
  }
});

connectWebSocket();

const exportBtn = document.getElementById("exportBtn");
if (exportBtn) {
  exportBtn.addEventListener("click", () => {
    window.open("/api/export", "_blank");
  });
}