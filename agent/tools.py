"""
Herramientas del Agente Formula 101
- OpenF1 API  : datos de sesiones recientes / en vivo
- Jolpica API : datos históricos de campeonatos (compatible Ergast)
- RAG search  : búsqueda en base de conocimiento local
"""

import time
import requests
from datetime import datetime, timezone
from langchain_core.tools import tool

# ── Cache TTL ────────────────────────────────────────────────────────────────
class _TTLCache:
    """Cache en memoria con tiempo de vida por entrada."""
    def __init__(self):
        self._store: dict = {}

    def get(self, key: str):
        if key in self._store:
            data, ts, ttl = self._store[key]
            if time.time() - ts < ttl:
                return data
        return None

    def set(self, key: str, data, ttl: int):
        self._store[key] = (data, time.time(), ttl)


_cache = _TTLCache()
TTL_REALTIME   = 60       # 1 minuto para datos en vivo
TTL_HISTORICAL = 3600     # 1 hora para datos históricos


# ── Helpers HTTP ─────────────────────────────────────────────────────────────
OPENF1_BASE  = "https://api.openf1.org/v1"
JOLPICA_BASE = "https://api.jolpi.ca/ergast/f1"


def _get(url: str, params: dict = None):
    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        return {"error": str(e)}


def _cached_get(key: str, url: str, params: dict = None, ttl: int = 60):
    """GET con caché. Sólo cachea respuestas sin error."""
    cached = _cache.get(key)
    if cached is not None:
        return cached
    data = _get(url, params)
    if not (isinstance(data, dict) and "error" in data):
        _cache.set(key, data, ttl)
    return data


# ── Inicialización lazy del retriever RAG ────────────────────────────────────
_retriever = None

def _get_retriever():
    global _retriever
    if _retriever is None:
        from agent.rag import get_retriever
        _retriever = get_retriever(k=4)
    return _retriever


# ── TOOLS: OpenF1 (tiempo real) ──────────────────────────────────────────────

@tool
def get_latest_session() -> dict:
    """Obtiene la carrera de F1 más reciente ya disputada (no futuras)."""
    data = _cached_get("latest_session", f"{OPENF1_BASE}/sessions",
                        params={"session_type": "Race"}, ttl=TTL_REALTIME)
    if isinstance(data, list) and data:
        now = datetime.now(timezone.utc).isoformat()
        past = [s for s in data if s.get("date_start", "") <= now] or data
        latest = sorted(past, key=lambda x: x.get("date_start", ""), reverse=True)[0]
        return {
            "session_key":  latest.get("session_key"),
            "meeting_name": latest.get("meeting_name"),
            "session_name": latest.get("session_name"),
            "country":      latest.get("country_name"),
            "circuit":      latest.get("circuit_short_name"),
            "date_start":   latest.get("date_start"),
            "year":         latest.get("year"),
        }
    return data or {"error": "No se encontraron sesiones"}


@tool
def get_race_positions(session_key: int) -> list:
    """Retorna las posiciones finales de todos los pilotos para un session_key dado."""
    data = _cached_get(f"positions_{session_key}", f"{OPENF1_BASE}/position",
                        params={"session_key": session_key}, ttl=TTL_REALTIME)
    if not isinstance(data, list):
        return [data]
    latest_by_driver = {}
    for entry in data:
        dn = entry.get("driver_number")
        if dn not in latest_by_driver or entry.get("date", "") > latest_by_driver[dn].get("date", ""):
            latest_by_driver[dn] = entry
    return sorted(latest_by_driver.values(), key=lambda x: x.get("position", 99))[:20]


@tool
def get_pit_stops(session_key: int) -> list:
    """Retorna todos los pit stops (piloto, vuelta, duración) para un session_key dado."""
    data = _cached_get(f"pits_{session_key}", f"{OPENF1_BASE}/pit",
                        params={"session_key": session_key}, ttl=TTL_REALTIME)
    return sorted(data, key=lambda x: x.get("date", "")) if isinstance(data, list) else [data]


@tool
def get_lap_times(session_key: int, driver_number: int) -> list:
    """Retorna los tiempos de vuelta de un piloto específico en una sesión."""
    key = f"laps_{session_key}_{driver_number}"
    data = _cached_get(key, f"{OPENF1_BASE}/laps",
                        params={"session_key": session_key, "driver_number": driver_number},
                        ttl=TTL_REALTIME)
    return data if isinstance(data, list) else [data]


@tool
def get_weather(session_key: int) -> dict:
    """Retorna las condiciones climáticas más recientes de una sesión (temperatura, lluvia, viento)."""
    data = _cached_get(f"weather_{session_key}", f"{OPENF1_BASE}/weather",
                        params={"session_key": session_key}, ttl=TTL_REALTIME)
    if isinstance(data, list) and data:
        latest = sorted(data, key=lambda x: x.get("date", ""), reverse=True)[0]
        return {k: latest.get(k) for k in
                ("air_temperature", "track_temperature", "humidity", "wind_speed",
                 "wind_direction", "rainfall")}
    return data or {"error": "Sin datos de clima"}


@tool
def get_drivers_in_session(session_key: int) -> list:
    """Retorna la lista de pilotos (nombre, número, equipo) que participaron en una sesión."""
    data = _cached_get(f"drivers_{session_key}", f"{OPENF1_BASE}/drivers",
                        params={"session_key": session_key}, ttl=TTL_HISTORICAL)
    if isinstance(data, list):
        return [{"driver_number": d.get("driver_number"), "full_name": d.get("full_name"),
                 "abbreviation": d.get("name_acronym"), "team": d.get("team_name"),
                 "country": d.get("country_code")} for d in data]
    return [data]


# ── TOOL: Buscar sesión por GP ───────────────────────────────────────────────

@tool
def get_session_by_gp(year: int, country_name: str = None, session_type: str = "Race") -> list:
    """
    Busca sesiones de F1 en OpenF1 por año, país y tipo de sesión.
    Útil para obtener el session_key de un GP específico y luego consultar
    posiciones, pit stops, tiempos de vuelta, clima, etc.
    - year: año de la temporada (ej. 2024, 2025)
    - country_name: nombre del país en inglés (ej. 'Japan', 'Italy', 'Monaco'). Opcional.
    - session_type: 'Race', 'Qualifying', 'Practice 1', 'Practice 2', 'Practice 3', 'Sprint'
    """
    params: dict = {"session_type": session_type, "year": year}
    if country_name:
        params["country_name"] = country_name
    key = f"session_{year}_{country_name}_{session_type}"
    data = _cached_get(key, f"{OPENF1_BASE}/sessions", params=params, ttl=TTL_HISTORICAL)
    if isinstance(data, list) and data:
        return [
            {
                "session_key":  s.get("session_key"),
                "meeting_name": s.get("meeting_name"),
                "session_name": s.get("session_name"),
                "country":      s.get("country_name"),
                "circuit":      s.get("circuit_short_name"),
                "date_start":   s.get("date_start"),
                "year":         s.get("year"),
            }
            for s in data
        ]
    return [{"error": "No se encontraron sesiones con esos parámetros"}]


# ── TOOLS: Jolpica / Ergast (histórico) ─────────────────────────────────────

@tool
def get_driver_standings(year: int) -> list:
    """Retorna el campeonato de pilotos de un año dado (1950-2024) con puntos y victorias."""
    data = _cached_get(f"driver_standings_{year}",
                        f"{JOLPICA_BASE}/{year}/driverStandings.json", ttl=TTL_HISTORICAL)
    try:
        standings = data["MRData"]["StandingsTable"]["StandingsLists"][0]["DriverStandings"]
        return [{"position": int(s["position"]),
                 "driver":   f"{s['Driver']['givenName']} {s['Driver']['familyName']}",
                 "team":     s["Constructors"][0]["name"] if s["Constructors"] else "N/A",
                 "points":   float(s["points"]), "wins": int(s["wins"])} for s in standings]
    except (KeyError, IndexError, TypeError):
        return [{"error": "Sin datos para ese año"}]


@tool
def get_constructor_standings(year: int) -> list:
    """Retorna el campeonato de constructores de un año dado con puntos y victorias."""
    data = _cached_get(f"constructor_standings_{year}",
                        f"{JOLPICA_BASE}/{year}/constructorStandings.json", ttl=TTL_HISTORICAL)
    try:
        standings = data["MRData"]["StandingsTable"]["StandingsLists"][0]["ConstructorStandings"]
        return [{"position": int(s["position"]), "team": s["Constructor"]["name"],
                 "points": float(s["points"]), "wins": int(s["wins"])} for s in standings]
    except (KeyError, IndexError, TypeError):
        return [{"error": "Sin datos para ese año"}]


@tool
def get_race_results(year: int, round_number: int) -> dict:
    """Retorna resultados completos de una carrera dado el año y número de ronda."""
    data = _cached_get(f"race_{year}_{round_number}",
                        f"{JOLPICA_BASE}/{year}/{round_number}/results.json", ttl=TTL_HISTORICAL)
    try:
        race = data["MRData"]["RaceTable"]["Races"][0]
        return {
            "grand_prix": race.get("raceName"),
            "circuit":    race.get("Circuit", {}).get("circuitName"),
            "date":       race.get("date"),
            "results": [{"position": r.get("position"),
                         "driver":   f"{r['Driver']['givenName']} {r['Driver']['familyName']}",
                         "team":     r["Constructor"]["name"],
                         "laps":     r.get("laps"),
                         "time":     r.get("Time", {}).get("time", r.get("status", "N/A")),
                         "points":   r.get("points")} for r in race.get("Results", [])],
        }
    except (KeyError, IndexError, TypeError):
        return {"error": "Sin resultados"}


@tool
def get_season_schedule(year: int) -> list:
    """Retorna el calendario completo de una temporada con fechas, circuitos y países."""
    data = _cached_get(f"schedule_{year}", f"{JOLPICA_BASE}/{year}.json", ttl=TTL_HISTORICAL)
    try:
        return [{"round": int(r["round"]), "grand_prix": r["raceName"],
                 "circuit": r["Circuit"]["circuitName"],
                 "country": r["Circuit"]["Location"]["country"],
                 "date":    r["date"]} for r in data["MRData"]["RaceTable"]["Races"]]
    except (KeyError, TypeError):
        return [{"error": "Sin calendario"}]


@tool
def get_driver_career(driver_id: str) -> dict:
    """Retorna info de carrera de un piloto por su ID (ej: 'hamilton', 'verstappen', 'alonso')."""
    data = _cached_get(f"driver_{driver_id}",
                        f"{JOLPICA_BASE}/drivers/{driver_id}.json", ttl=TTL_HISTORICAL)
    try:
        d = data["MRData"]["DriverTable"]["Drivers"][0]
        return {"name": f"{d['givenName']} {d['familyName']}", "nationality": d.get("nationality"),
                "date_of_birth": d.get("dateOfBirth"), "permanent_number": d.get("permanentNumber")}
    except (KeyError, IndexError, TypeError):
        return {"error": f"Piloto '{driver_id}' no encontrado"}


@tool
def get_qualifying_results(year: int, round_number: int) -> dict:
    """Retorna resultados de clasificación (Q1/Q2/Q3) de un Gran Premio específico."""
    data = _cached_get(f"quali_{year}_{round_number}",
                        f"{JOLPICA_BASE}/{year}/{round_number}/qualifying.json", ttl=TTL_HISTORICAL)
    try:
        race = data["MRData"]["RaceTable"]["Races"][0]
        return {
            "grand_prix": race.get("raceName"),
            "date":       race.get("date"),
            "results": [{"position": int(r["position"]),
                         "driver":   f"{r['Driver']['givenName']} {r['Driver']['familyName']}",
                         "team":     r["Constructor"]["name"],
                         "Q1": r.get("Q1", "-"), "Q2": r.get("Q2", "-"), "Q3": r.get("Q3", "-")}
                        for r in race.get("QualifyingResults", [])],
        }
    except (KeyError, IndexError, TypeError):
        return {"error": "Sin resultados de clasificación"}


# ── TOOL: RAG ────────────────────────────────────────────────────────────────

@tool
def search_f1_knowledge(query: str) -> str:
    """Busca en la base de conocimiento local sobre reglamentos, equipos, historia y estrategia F1."""
    docs = _get_retriever().invoke(query)
    if not docs:
        return "Sin información relevante en la base de conocimiento."
    return "\n\n---\n\n".join(
        f"[{doc.metadata.get('source', '?')}]\n{doc.page_content}" for doc in docs
    )


# ── Lista exportada ──────────────────────────────────────────────────────────
ALL_TOOLS = [
    get_latest_session, get_session_by_gp, get_race_positions, get_pit_stops,
    get_lap_times, get_weather, get_drivers_in_session, get_driver_standings,
    get_constructor_standings, get_race_results, get_season_schedule,
    get_driver_career, get_qualifying_results, search_f1_knowledge,
]
