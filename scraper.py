import time
import pandas as pd
import requests
from bs4 import BeautifulSoup
import os

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}

def fetch_with_retries(url, is_pandas=False):
    retries = 5
    for attempt in range(retries):
        try:
            if is_pandas:
                dfs = pd.read_html(url, storage_options={"User-Agent": HEADERS["User-Agent"]})
                return dfs
            else:
                resp = requests.get(url, headers=HEADERS, timeout=20)
                if resp.status_code == 200:
                    return resp.text
        except Exception as e:
            print(f"  Attempt {attempt+1}/{retries} failed: {e}. Retrying in 10s...")
            time.sleep(10)
    raise Exception(f"Failed to fetch {url} after {retries} retries.")

def scrape_data():
    os.makedirs("data/raw", exist_ok=True)
    print("=== Super-Scraper Initiated (Resilient Networking) ===")
    
    # 1. Transfermarkt Scrape
    print("Scraping Transfermarkt top 200 players...")
    players_data = []
    seen_players = set()  # Guard: detect when site loops and returns the same page again
    
    for p_idx in range(1, 9):
        url = f"https://www.transfermarkt.us/championship/marktwerte/wettbewerb/GB2?ajax=yw1&page={p_idx}"
        try:
            html = fetch_with_retries(url)
            soup = BeautifulSoup(html, 'html.parser')
            table = soup.find('table', class_='items')
            
            if table:
                rows = table.find('tbody').find_all('tr', recursive=False)
                page_players = []
                for row in rows:
                    cells = row.find_all('td', recursive=False)
                    if len(cells) < 6: continue
                    name_td = cells[1]
                    name = name_td.find('img')['title'] if name_td.find('img') else name_td.text.strip()
                    pos = name_td.find_all('td')[-1].text.strip() if name_td.find_all('td') else ""
                    age = cells[3].text.strip()
                    val_str = cells[5].text.strip()
                    page_players.append({"Rank": cells[0].text.strip(), "Player": name, "Position": pos, "Age": age, "Market Value str": val_str})
                
                if not page_players:
                    print(f"  Page {p_idx}: no players found, stopping.")
                    break
                
                # Early-termination: if >=50% of this page's players were already scraped,
                # the site is repeating a previous page — stop immediately.
                page_names = {r["Player"] for r in page_players}
                overlap = len(page_names & seen_players)
                if seen_players and overlap / len(page_names) >= 0.5:
                    print(f"  Page {p_idx}: {overlap}/{len(page_names)} players already seen — site is looping. Stopping early.")
                    break
                
                players_data.extend(page_players)
                seen_players.update(page_names)
                print(f"  Page {p_idx}: scraped {len(page_players)} players ({len(seen_players)} unique so far).")
        except Exception as e:
            print(f"Fatal error on TM page {p_idx}: {e}")
            
    tm_df = pd.DataFrame(players_data)
    # Final deduplication guard — keep first occurrence of each player name
    before = len(tm_df)
    tm_df = tm_df.drop_duplicates(subset=['Player'], keep='first').reset_index(drop=True)
    if len(tm_df) < before:
        print(f"  Deduplication removed {before - len(tm_df)} duplicate rows.")
    tm_df.to_csv("data/raw/transfermarkt_top200.csv", index=False)
    print(f"Saved {len(tm_df)} unique Transfermarkt players.")

    # 2. FBRef Scrape (via Wayback Archive to bypass Cloudflare)
    # NOTE: Standard table already contains PrgC, PrgP, xAG (covers Passing + Possession needs)
    # Passing/Possession/Defense Wayback snapshots only return squad-level (24 teams) - not player-level
    fbref_urls = {
        "Standard": "https://web.archive.org/web/2026/https://fbref.com/en/comps/10/stats/Championship-Stats",
        "Shooting": "https://web.archive.org/web/2026/https://fbref.com/en/comps/10/shooting/Championship-Stats"
    }

    print("\nScraping FBRef Data via Archive Proxy...")
    for name, url in fbref_urls.items():
        print(f"Fetching FBref {name} stats...")
        try:
            tables = fetch_with_retries(url, is_pandas=True)
            for df in tables:
                if 'Player' in df.columns or (isinstance(df.columns, pd.MultiIndex) and 'Player' in df.columns.get_level_values(1)):
                    if isinstance(df.columns, pd.MultiIndex):
                        df.columns = df.columns.droplevel(0)
                    df = df.loc[:,~df.columns.duplicated()].copy()
                    df = df[df['Player'] != 'Player']
                    df.to_csv(f"data/raw/fbref_{name.lower()}.csv", index=False)
                    print(f"--> Saved {name} with {len(df)} records.")
                    break
        except Exception as e:
            print(f"Fatal Error on FBref {name}: {e}")

    print("=== Scraper Complete ===")

if __name__ == "__main__":
    scrape_data()
