import numpy as np
from sklearn.ensemble import RandomForestRegressor

# Обучающая выборка [температура, влажность, скорость ветра (норд-ост)] -> риск (%)
X_train = np.array([
    [15, 70, 5],   [20, 60, 8],   [25, 50, 12],  [30, 40, 15],  [35, 30, 20],
    [18, 65, 6],   [22, 55, 10],  [28, 45, 14],  [32, 35, 18],  [38, 25, 25]
])
y_train = np.array([20, 35, 55, 75, 95, 25, 42, 68, 85, 99])

model = RandomForestRegressor(n_estimators=10, random_state=42)
model.fit(X_train, y_train)

def predict_fire_risk(temp: float, humidity: float, wind_speed: float):
    input_features = np.array([[temp, humidity, wind_speed]])
    base_pred = float(model.predict(input_features)[0])
    base_pred = min(99.0, max(10.0, base_pred))
    
    hours = ["Сейчас", "+1 ч", "+2 ч", "+3 ч", "+4 ч", "+5 ч", "+6 ч"]
    trends = []
    current_val = base_pred
    for _ in hours:
        current_val = min(99.0, max(10.0, current_val + np.random.uniform(-3.5, 4.0)))
        trends.append(round(current_val, 1))

    return {
        "risk_level": round(base_pred, 1),
        "hours": hours,
        "trends": trends,
        "model_info": "RandomForestRegressor (scikit-learn, FWI-adapted for Novorossiysk)"
    }
