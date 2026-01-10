# -*- coding: utf-8 -*-
import requests
from bs4 import BeautifulSoup
import json
import os
import time
from datetime import datetime
import pytz

TZ_MADRID = pytz.timezone('Europe/Madrid')
CALENDAR_FILE = "calendar.json"
STANDINGS_FILE = "standings.json"
RESULTS_FILE = "results.json"

URLS_STANDINGS = {
    "LALIGA": "https://www.lavanguardia.com/deportes/resultados/laliga-primera-division/clasificacion",
    "CHAMPIONS": "https://www.lavanguardia.com/deportes/resultados/champions-league/clasificacion",
    "EUROPA": "https://www.lavanguardia.com/deportes/resultados/europa-league/clasificacion"
}

def scrape_standings():
    print("📊 Extrayendo Clasificaciones...")
    standings = {}
    headers = {'User-Agent': 'Mozilla/5.0'}
    for name, url in URLS_STANDINGS.items():
        try:
            r = requests.get(url, headers=headers, timeout=15)
            soup = BeautifulSoup(r.content, 'html.parser')
            table = max(soup.find_all('table'), key=lambda t: len(t.find_all('tr')))
            rows = table.find_all('tr')
            league_data = []
            for row in rows:
                cells = row.find_all(['td', 'th'])
                texts = [c.get_text(strip=True) for c in cells]
                if len(texts) > 5 and texts[0].isdigit():
                    league_data.append({
                        "rank": texts[0],
                        "team": texts[1],
                        "points": texts[2]
                    })
            if league_data:
                standings[name] = league_data
        except: continue
    return standings

# ... (El resto de funciones scrape_agenda y scrape_results se mantienen igual) ...

if __name__ == "__main__":
    # Forzar actualización inicial si faltan archivos
    force = not (os.path.exists(CALENDAR_FILE) and os.path.exists(STANDINGS_FILE))
    
    # ... Lógica de check_if_update_needed ...
    
    # Ejecución
    with open(STANDINGS_FILE, 'w') as f:
        json.dump(scrape_standings(), f, indent=2)
    # (Añadir aquí las llamadas a scrape_agenda y scrape_results y guardar en sus respectivos archivos)
