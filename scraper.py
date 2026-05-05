import time
import pandas as pd
import os
import requests
from bs4 import BeautifulSoup

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("Playwright not installed. Please run: pip install playwright && playwright install chromium")
    exit(1)

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

def fetch_html_playwright(url, wait_time=3):
    """Fetches HTML using Playwright with stealth settings to bypass basic protections."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=USER_AGENT,
            viewport={'width': 1920, 'height': 1080},
            java_script_enabled=True,
            bypass_csp=True
        )
        page = context.new_page()
        # Basic stealth to hide automated webdriver
        page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        
        try:
            print(f"Loading {url} ...")
            page.goto(url, timeout=45000, wait_until='domcontentloaded')
            time.sleep(wait_time)
            html = page.content()
            return html
        except Exception as e:
            print(f"Error loading {url}: {e}")
            return None
        finally:
            browser.close()

def parse_transfermarkt_row(row):
    """Helper to cleanly extract player data from a single Transfermarkt table row."""
    cells = row.find_all('td', recursive=False)
    if len(cells) < 6: return None
    
    # Name and Position are nested in a sub-table in cell 1
    name_td = cells[1].find('table')
    if name_td and len(name_td.find_all('tr')) >= 2:
        name_rows = name_td.find_all('tr')
        player_name = name_rows[0].find('a').text.strip()
        pos = name_rows[1].text.strip()
    else:
        player_name = cells[1].text.strip()
        pos = "N/A"
        
    age = cells[2].text.strip()
    squad_img = cells[3].find('img')
    squad = squad_img.get('alt') if squad_img else "Unknown"
    val_str = cells[5].text.strip()
    
    return {
        "Player": player_name,
        "Squad": squad,
        "Position": pos,
        "Age": age,
        "Market Value str": val_str
    }

def scrape_transfermarkt():
    """Scrapes top ~200 players, trying .us then .com to bypass regional blocks."""
    domains = ["transfermarkt.us", "transfermarkt.com"]
    
    for domain in domains:
        print(f"\n--- Scraping Transfermarkt via {domain} ---")
        players = []
        seen_players = set()
        
        for page_num in range(1, 9): # 8 pages * 25 = 200 players
            url = f"https://www.{domain}/championship/marktwerte/wettbewerb/GB2?ajax=yw1&page={page_num}"
            html = fetch_html_playwright(url, wait_time=3)
            
            if not html: break
                
            soup = BeautifulSoup(html, 'html.parser')
            table = soup.find('table', class_='items')
            
            if not table:
                print(f"Could not find players table on page {page_num}. Likely blocked (403).")
                break
            
            rows = table.find('tbody').find_all('tr', recursive=False)
            new_players_count = 0
            
            for row in rows:
                player_data = parse_transfermarkt_row(row)
                if not player_data: continue
                
                # Prevent silent pagination duplication from TM
                if player_data['Player'] in seen_players: continue
                    
                seen_players.add(player_data['Player'])
                players.append(player_data)
                new_players_count += 1
                
            if new_players_count == 0:
                print(f"No new players found on page {page_num}. Ending pagination.")
                break
                
            time.sleep(3) # Polite scraping
            
        if players:
            print(f"✅ Successfully scraped {len(players)} players from {domain}.")
            return players
            
    print("❌ Failed to scrape Transfermarkt on all domains.")
    return []

def extract_fbref_table(html):
    """Cleans FBRef HTML (removes comments) and extracts the primary player dataframe."""
    html = html.replace('<!--', '').replace('-->', '')
    try:
        dfs = pd.read_html(html)
        for df in dfs:
            cols = df.columns
            # Flatten multi-level headers if present
            if isinstance(cols, pd.MultiIndex):
                cols = cols.get_level_values(1)
                
            if 'Player' in cols:
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.droplevel(0)
                
                # Clean up repeated FBRef headers mid-table
                df = df.loc[:,~df.columns.duplicated()].copy()
                df = df[df['Player'] != 'Player'].copy()
                return df
    except Exception as e:
        print(f"Failed to parse table: {e}")
    return None

def scrape_fbref():
    """Scrapes FBref stats using Playwright, falling back to Wayback Machine requests if blocked."""
    endpoints = {
        "Standard": {
            "live": "https://fbref.com/en/comps/10/stats/Championship-Stats",
            "archive": "https://web.archive.org/web/20251215/https://fbref.com/en/comps/10/stats/Championship-Stats"
        },
        "Shooting": {
            "live": "https://fbref.com/en/comps/10/shooting/Championship-Stats",
            "archive": "https://web.archive.org/web/20251215/https://fbref.com/en/comps/10/shooting/Championship-Stats"
        }
    }
    
    for name, urls in endpoints.items():
        print(f"\n--- Scraping FBRef: {name} ---")
        
        # Attempt 1: Live Playwright
        html = fetch_html_playwright(urls["live"], wait_time=4)
        df = extract_fbref_table(html) if html else None
        
        # Attempt 2: Wayback Machine via basic requests (light fallback)
        if df is None or df.empty:
            print("Live scrape failed. Falling back to Wayback Machine archive...")
            try:
                resp = requests.get(urls["archive"], headers={"User-Agent": USER_AGENT}, timeout=15)
                if resp.status_code == 200:
                    df = extract_fbref_table(resp.text)
            except Exception as e:
                print(f"Archive fallback failed: {e}")

        # Save results
        if df is not None and not df.empty:
            df.to_csv(f"data/raw/fbref_{name.lower()}.csv", index=False)
            print(f"✅ Saved {len(df)} {name} records.")
        else:
            print(f"❌ Failed to acquire {name} stats.")

def scrape_data():
    print("=== Pipeline: Refactored Data Scraper ===")
    os.makedirs("data/raw", exist_ok=True)
    
    # 1. Transfermarkt
    tm_players = scrape_transfermarkt()
    if tm_players:
        tm_df = pd.DataFrame(tm_players)
        tm_df.to_csv("data/raw/transfermarkt_top200.csv", index=False)
        
    # 2. FBRef
    scrape_fbref()

    print("\n=== Scraper Complete ===")

if __name__ == "__main__":
    scrape_data()
