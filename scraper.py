import time
import pandas as pd
import os
import re
from bs4 import BeautifulSoup

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("Playwright not installed. Please run: pip install playwright && playwright install chromium")
    exit(1)

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

def get_html_playwright(url, wait_time=3):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        # Apply stealth-like settings
        context = browser.new_context(
            user_agent=USER_AGENT,
            viewport={'width': 1920, 'height': 1080},
            java_script_enabled=True,
            bypass_csp=True
        )
        page = context.new_page()
        # Mask webdriver to avoid simple detection
        page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        
        try:
            print(f"Loading {url} ...")
            page.goto(url, timeout=45000, wait_until='domcontentloaded')
            time.sleep(wait_time)
            html = page.content()
            browser.close()
            return html
        except Exception as e:
            print(f"Error loading {url}: {e}")
            browser.close()
            return None

def fetch_transfermarkt_pages():
    # Try .us first, then .com
    domains = ["transfermarkt.us", "transfermarkt.com"]
    players = []
    
    for domain in domains:
        print(f"\n--- Trying Transfermarkt on {domain} ---")
        players = []
        seen_players = set()
        success = True
        
        for page_num in range(1, 9): # 8 pages * 25 = 200 players
            url = f"https://www.{domain}/championship/marktwerte/wettbewerb/GB2?ajax=yw1&page={page_num}"
            print(f"Scraping Page {page_num}...")
            
            html = get_html_playwright(url, wait_time=3)
            if not html:
                success = False
                break
                
            soup = BeautifulSoup(html, 'html.parser')
            table = soup.find('table', class_='items')
            
            if not table:
                print(f"Could not find players table on page {page_num}.")
                if "403" in html or "Forbidden" in html or "Cloudflare" in html:
                    print("Blocked by Cloudflare/403.")
                    success = False
                break
            
            rows = table.find('tbody').find_all('tr', recursive=False)
            new_players_count = 0
            for row in rows:
                cells = row.find_all('td', recursive=False)
                if len(cells) < 6: continue
                
                name_td = cells[1].find('table')
                if name_td:
                    name_rows = name_td.find_all('tr')
                    if len(name_rows) >= 2:
                        player_name = name_rows[0].find('a').text.strip()
                        pos = name_rows[1].text.strip()
                    else:
                        player_name = cells[1].text.strip()
                        pos = "N/A"
                else:
                    player_name = cells[1].text.strip()
                    pos = "N/A"
                
                # Check for duplicates to handle TM's silent pagination repetition
                if player_name in seen_players:
                    continue
                    
                seen_players.add(player_name)
                new_players_count += 1
                
                age = cells[2].text.strip()
                squad = cells[3].find('img').get('alt') if cells[3].find('img') else "Unknown"
                val_str = cells[5].text.strip()
                
                players.append({
                    "Player": player_name,
                    "Squad": squad,
                    "Position": pos,
                    "Age": age,
                    "Market Value str": val_str
                })
                
            if new_players_count == 0:
                print(f"No new players found on page {page_num}. Ending pagination.")
                break
                
            time.sleep(3) # Polite scraping
            
        if success and len(players) > 0:
            print(f"Successfully scraped {len(players)} players from {domain}.")
            return players
            
    return players

def fetch_fbref_live(name, url):
    print(f"\n--- Trying Live FBRef for {name} ---")
    html = get_html_playwright(url, wait_time=4)
    if not html: return None
    
    # FBRef hides data in comments
    html = html.replace('<!--', '').replace('-->', '')
    
    try:
        dfs = pd.read_html(html)
        for df in dfs:
            cols = df.columns
            if isinstance(cols, pd.MultiIndex):
                cols = cols.get_level_values(1)
                
            if 'Player' in cols:
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.droplevel(0)
                
                # Clean up repeated headers
                df = df.loc[:,~df.columns.duplicated()].copy()
                df = df[df['Player'] != 'Player'].copy()
                return df
    except Exception as e:
        print(f"Live parsing failed: {e}")
        
    return None

def fetch_fbref_wayback(name, url):
    print(f"--- Falling back to Wayback Machine for {name} ---")
    import requests
    retries = 3
    for attempt in range(retries):
        try:
            headers = {"User-Agent": USER_AGENT}
            resp = requests.get(url, headers=headers, timeout=30)
            if resp.status_code == 200:
                html = resp.text.replace('<!--', '').replace('-->', '')
                dfs = pd.read_html(html)
                for df in dfs:
                    cols = df.columns
                    if isinstance(cols, pd.MultiIndex):
                        cols = cols.get_level_values(1)
                    if 'Player' in cols:
                        if isinstance(df.columns, pd.MultiIndex):
                            df.columns = df.columns.droplevel(0)
                        df = df.loc[:,~df.columns.duplicated()].copy()
                        df = df[df['Player'] != 'Player'].copy()
                        return df
        except Exception as e:
            print(f"Wayback attempt {attempt+1} failed: {e}")
            time.sleep(5)
    return None

def scrape_data():
    os.makedirs("data/raw", exist_ok=True)
    print("=== Advanced Scraper: Playwright Live Edition ===")
    
    # 1. Transfermarkt
    tm_players = fetch_transfermarkt_pages()
    if tm_players:
        tm_df = pd.DataFrame(tm_players)
        tm_df.to_csv("data/raw/transfermarkt_top200.csv", index=False)
        print(f"[DONE] Saved {len(tm_df)} unique players to TM CSV.")
    else:
        print("[ERROR] Failed to scrape Transfermarkt.")
        
    # 2. FBRef
    fbref_endpoints = {
        "Standard": {
            "live": "https://fbref.com/en/comps/10/stats/Championship-Stats",
            "wayback": "https://web.archive.org/web/20251215/https://fbref.com/en/comps/10/stats/Championship-Stats"
        },
        "Shooting": {
            "live": "https://fbref.com/en/comps/10/shooting/Championship-Stats",
            "wayback": "https://web.archive.org/web/20251215/https://fbref.com/en/comps/10/shooting/Championship-Stats"
        }
    }
    
    for name, urls in fbref_endpoints.items():
        df = fetch_fbref_live(name, urls["live"])
        if df is None or df.empty:
            print("Live scrape failed or returned empty.")
            df = fetch_fbref_wayback(name, urls["wayback"])
            
        if df is not None and not df.empty:
            df.to_csv(f"data/raw/fbref_{name.lower()}.csv", index=False)
            print(f"--> Saved {len(df)} {name} records.")
        else:
            print(f"[ERROR] Completely failed to acquire {name} stats.")

    print("\n=== Scraper Complete ===")

if __name__ == "__main__":
    scrape_data()
