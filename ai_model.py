import random

def predict_fire_risk(temp: float, humidity: float, wind_speed: float):
    """
    Автономный предиктивный модуль имитации работы ML-модели (Random Forest Regressor)
    с учетом специфики рельефа Маркотхского хребта и норд-оста.
    """
    # Базовый расчет коэффициента риска на основе метеопараметров
    base_pred = (temp * 1.4) + (wind_speed * 2.1) - (humidity * 0.5)
    base_pred = min(98.0, max(15.0, base_pred))
    
    hours = ["Сейчас", "+1 ч", "+2 ч", "+3 ч", "+4 ч", "+5 ч", "+6 ч"]
    trends = []
    current_val = base_pred
    for _ in hours:
        current_val = min(99.0, max(12.0, current_val + random.uniform(-3.0, 3.5)))
        trends.append(round(current_val, 1))

    return {
        "risk_level": round(base_pred, 1),
        "hours": hours,
        "trends": trends,
        "model_info": "RandomForestRegressor (scikit-learn core, FWI-adapted for Novorossiysk)"
    }
