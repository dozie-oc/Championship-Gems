import time
import pandas as pd
import requests
from bs4 import BeautifulSoup
import os
import re

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
BASE_URL = "https://www.transfermarkt.us"

def fetch_with_retries(url, is_pandas=False):
    retries = 3
    for attempt in range(retries):
        try:
            if is_pandas:
                # Use a specific engine and handle potential read errors
                dfs = pd.read_html(url, storage_options={"User-Agent": HEADERS["User-Agent"]})
                return dfs
            else:
                resp = requests.get(url, headers=HEADERS, timeout=30)
                if resp.status_code == 200:
                    return resp.text
                elif resp.status_code == 403:
                    print(f"  Attempt {attempt+1}: 403 Forbidden. Site is blocking us.")
        except Exception as e:
            print(f"  Attempt {attempt+1} failed: {e}. Retrying in 5s...")
            time.sleep(5)
    return None

def get_championship_clubs():
    print("Fetching Championship club list...")
    url = f"{BASE_URL}/championship/startseite/wettbewerb/GB2"
    html = fetch_with_retries(url)
    if not html: return []
    
    soup = BeautifulSoup(html, 'html.parser')
    table = soup.find('table', class_='items')
    clubs = []
    if table:
        links = table.find_all('a', href=re.compile(r'startseite/verein'))
        # Filter unique club links
        seen_hrefs = set()
        for link in links:
            href = link.get('href')
            if href not in seen_hrefs and 'saison_id' not in href:
                # Convert startseite to kader (squad) for full list
                squad_href = href.replace('startseite', 'kader')
                clubs.append({"name": link.text.strip(), "url": BASE_URL + squad_href})
                seen_hrefs.add(href)
    print(f"Found {len(clubs)} clubs.")
    return clubs

def scrape_club_squad(club):
    print(f"  Scraping {club['name']}...")
    html = fetch_with_retries(club['url'])
    if not html: return []
    
    soup = BeautifulSoup(html, 'html.parser')
    # Find the main squad table
    table = soup.find('table', class_='items')
    players = []
    if table:
        rows = table.find('tbody').find_all('tr', recursive=False)
        for row in rows:
            cells = row.find_all('td', recursive=False)
            if len(cells) < 4: continue
            
            # Name and position are usually in the second cell
            name_td = cells[1].find('table')
            if name_td:
                name_rows = name_td.find_all('tr')
                player_name = name_rows[0].find('a').text.strip()
                pos = name_rows[1].text.strip()
            else:
                player_name = cells[1].text.strip()
                pos = "N/A"
            
            age = cells[2].text.strip()
            val_str = cells[5].text.strip() if len(cells) > 5 else "-"
            
            players.append({
                "Player": player_name,
                "Squad": club['name'],
                "Position": pos,
                "Age": age,
                "Market Value str": val_str
            })
    return players

def scrape_data():
    os.makedirs("data/raw", exist_ok=True)
    print("=== Super-Scraper 2.0: Club-Based Architecture ===")
    
    # 1. Transfermarkt: Scrape All Clubs
    clubs = get_championship_clubs()
    all_tm_players = []
    for club in clubs:
        squad = scrape_club_squad(club)
        all_tm_players.extend(squad)
        time.sleep(1) # Polite scraping
    
    tm_df = pd.DataFrame(all_tm_players)
    if not tm_df.empty:
        tm_df = tm_df.drop_duplicates(subset=['Player', 'Squad']).reset_index(drop=True)
        tm_df.to_csv("data/raw/transfermarkt_top200.csv", index=False)
        print(f"\n[DONE] Saved {len(tm_df)} unique players from all 24 clubs to TM CSV.")
    
    # 2. FBRef: Use a wider Wayback snapshot
    fbref_urls = {
        "Standard": "https://web.archive.org/web/20251215/https://fbref.com/en/comps/10/stats/Championship-Stats",
        "Shooting": "https://web.archive.org/web/20251215/https://fbref.com/en/comps/10/shooting/Championship-Stats"
    }

    print("\nScraping FBRef Data via Archive Proxy...")
    for name, url in fbref_urls.items():
        print(f"Fetching FBref {name} stats...")
        try:
            tables = fetch_with_retries(url, is_pandas=True)
            if tables:
                found = False
                for df in tables:
                    # Look for the main player table
                    cols = df.columns
                    if isinstance(cols, pd.MultiIndex):
                        cols = cols.get_level_values(1)
                    
                    if 'Player' in cols:
                        if isinstance(df.columns, pd.MultiIndex):
                            df.columns = df.columns.droplevel(0)
                        
                        # Cleanup FBRef repeated headers
                        df = df.loc[:,~df.columns.duplicated()].copy()
                        df = df[df['Player'] != 'Player'].copy()
                        
                        df.to_csv(f"data/raw/fbref_{name.lower()}.csv", index=False)
                        print(f"--> Saved {len(df)} {name} records.")
                        found = True
                        break
                if not found:
                    print(f"Warning: Could not find player table in {name} URL.")
        except Exception as e:
            print(f"Error on FBref {name}: {e}")

    print("\n=== Scraper Complete ===")

if __name__ == "__main__":
    scrape_data()
