import nbformat as nbf
import json
import os

nb = nbf.v4.new_notebook()

# Markdown: Intro
cell_1 = nbf.v4.new_markdown_cell("""# EFL Championship 2025-26: Unearthing Hidden Gems 💎

This notebook is the analytical heart of our pipeline. It takes the top ~200 most valuable players from Transfermarkt and merges them against FBref's advanced performance metrics (Standard & Shooting) to calculate a definitive **Value-for-Money** yardstick.

**Key Architecture & Improvements:**
- **Live Scraped Data**: We ingest data freshly acquired by our Playwright-driven `scraper.py` engine, bypassing cloud protections safely.
- **Dynamic Normalization Filters**: Players who haven't played at least 25% of the league's maximum minutes so far are filtered out to keep the analysis relevant and resilient to small sample sizes.
- **Advanced Fuzzy Matching**: We overlay robust fuzzy matching logic (`thefuzz` @ 75%) with a manual dictionary (`player_mapping.json`) to elegantly bridge Transfermarkt's and FBref's differing naming conventions.
""")

# Code: Working-directory guard (must be first)
cell_0 = nbf.v4.new_code_cell("""import os, pathlib

# Ensure we're running in the project root so paths align
_cwd = pathlib.Path(os.getcwd())
if _cwd.name == 'notebooks':
    os.chdir(_cwd.parent)
    print(f"Working directory shifted to: {os.getcwd()}")
else:
    print(f"Working directory ready at root: {os.getcwd()}")
""")

# Code: Setup
cell_2 = nbf.v4.new_code_cell("""import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import re
from thefuzz import process, fuzz
import json
import warnings
warnings.filterwarnings('ignore')

# --- CONFIGURATION LAB ---
# How much should we weigh attacking vs defending? 
OFF_WEIGHT = 0.6
DEF_WEIGHT = 0.4

def clean_value(v):
    if not isinstance(v, str) or v == '-': return 0
    mult = 1
    v_lower = v.lower()
    if 'm' in v_lower: mult = 1
    elif 'k' in v_lower: mult = 0.001
    num = re.sub(r'[^\\d.]', '', v)
    try: return float(num) * mult
    except: return 0
    
print("Environment completely initialized. Ready to crunch numbers.")
""")

# Markdown: Transfermarkt
cell_3 = nbf.v4.new_markdown_cell("""## 1. Extract Transfermarkt Valuations

Here we load our scraped Transfermarkt dataset (`data/raw/transfermarkt_top200.csv`). This gives us our baseline "Yardstick" — the average market value of the league's top players.""")

# Code: Transfermarkt
cell_4 = nbf.v4.new_code_cell("""# 1. Load Transfermarkt Data
try:
    tm_df = pd.read_csv("data/raw/transfermarkt_top200.csv")
    print(f"Successfully loaded {len(tm_df)} rows from Transfermarkt scrape.")
except FileNotFoundError:
    print("Transfermarkt data not found. Please run scraper.py first.")
    tm_df = pd.DataFrame()
    
if not tm_df.empty:
    # Defensive deduplication: drop any repeated players to enforce 1 player = 1 row
    before_dedup = len(tm_df)
    tm_df = tm_df.drop_duplicates(subset=['Player'], keep='first').reset_index(drop=True)
    if len(tm_df) < before_dedup:
        print(f"Removed {before_dedup - len(tm_df)} duplicate player rows from TM data.")
    print(f"{len(tm_df)} unique players loaded for analysis.")

    tm_df['Market Value (m)'] = tm_df['Market Value str'].apply(clean_value)
    
    # Drop rows without a clean value
    tm_df = tm_df[tm_df['Market Value (m)'] > 0].copy()
    
    avg_market_value = tm_df['Market Value (m)'].mean()
    print(f"\\n🎯 YARDSTICK: The average market value of these Championship players is €{avg_market_value:.2f}m")
    tm_df['vs_average'] = tm_df['Market Value (m)'] - avg_market_value
    
    # Categorize pricing
    tm_df['price_category'] = pd.cut(
        tm_df['Market Value (m)'],
        bins=[-np.inf, avg_market_value, avg_market_value * 1.5, np.inf],
        labels=['Below Avg', 'Above Avg', 'Premium'],
        duplicates='drop'
    )
tm_df.head()
""")

# Markdown: FBref Section
cell_5 = nbf.v4.new_markdown_cell("""## 2. Ingest FBref Performance Metrics

We pull in the tactical data (Standard & Shooting) from our scraped CSVs.""")

# Code: FBRef
cell_6 = nbf.v4.new_code_cell("""import os

dfs_fbref = {}
# Standard already contains critical progression metrics (PrgC, PrgP, xAG)
fbref_modules = ['standard', 'shooting']

for mod in fbref_modules:
    path = f"data/raw/fbref_{mod}.csv"
    if os.path.exists(path):
        df = pd.read_csv(path)
        dfs_fbref[mod.capitalize()] = df
    else:
        print(f"Warning: {path} not found. Did the scraper complete successfully?")

print(f"Loaded {len(dfs_fbref)} FBRef tables from disk.")
""")

# Markdown: Merge
cell_7 = nbf.v4.new_markdown_cell("""## 3. The Great Merge: Linking TM and FBref

This is where the magic happens. We merge the datasets, applying dynamic filters based on minutes played (`90s`), and use fuzzy matching to ensure "Carlos Vicente" connects with "C. Vicente".""")

# Code: Merge
cell_8 = nbf.v4.new_code_cell("""import json

if len(dfs_fbref) >= 1:
    # 1. Merge Standard + Shooting stats
    std_cols = ['Player', 'Squad', 'Pos', '90s', 'xG', 'xAG', 'PrgC', 'PrgP']
    sht_cols = ['Player', 'Squad', 'SoT']
    
    col_mappings = {'Standard': std_cols, 'Shooting': sht_cols}
    fb_df = None
    
    try:
        for name, df in dfs_fbref.items():
            avail_cols = [c for c in col_mappings.get(name, []) if c in df.columns]
            if 'Player' not in avail_cols: avail_cols.insert(0, 'Player')
            if 'Squad' not in avail_cols: avail_cols.insert(1, 'Squad')
            df_sub = df[avail_cols].drop_duplicates(subset=['Player', 'Squad'])
            
            if fb_df is None:
                fb_df = df_sub
            else:
                fb_df = fb_df.merge(df_sub, on=['Player', 'Squad'], how='outer')
        
        # Clean numeric columns
        cols_to_num = fb_df.columns.drop(['Player', 'Squad', 'Pos'], errors='ignore')
        fb_df[cols_to_num] = fb_df[cols_to_num].apply(pd.to_numeric, errors='coerce').fillna(0)
        
        # 🛡️ Dynamic Minutes Filter (25% of max 90s)
        if '90s' in fb_df.columns:
            max_90s = fb_df['90s'].max()
            min_90s = 0.25 * max_90s
            fb_df = fb_df[fb_df['90s'] >= min_90s].copy()
            print(f"🛡️ Dynamic Minutes Filter: Kept players with >= {min_90s:.2f} '90s' (25% of max {max_90s:.2f})")
        else:
            print("Warning: Standard stats (90s) missing, skipping filtering.")
            fb_df['90s'] = 1  
            
        # 🤝 Fuzzy Matching to Transfermarkt
        print("Fuzzy matching players across datasets...")
        mapping_dict = {}
        try:
            with open("data/player_mapping.json", "r") as f:
                mapping_dict = json.load(f)
        except Exception as e:
            print("Notice: No player_mapping.json loaded", e)
            
        fb_names = fb_df['Player'].dropna().unique()
        
        def match_name(tm_name):
            if not isinstance(tm_name, str): return None
            # 1. Check manual JSON mapping
            if tm_name in mapping_dict:
                mapped = mapping_dict[tm_name]
                # If mapped exists, return it, otherwise allow fallback
                if mapped in fb_names: return mapped
                
            if len(fb_names) == 0: return None
            
            # 2. ExtractOne threshold set to 75% for robust detection
            match = process.extractOne(tm_name, fb_names, scorer=fuzz.token_sort_ratio)
            return match[0] if match and match[1] >= 75 else None
            
        tm_df['fbref_name'] = tm_df['Player'].apply(match_name)
        
        # Final join
        final_df = tm_df.merge(fb_df, left_on='fbref_name', right_on='Player', suffixes=('_tm', '_fb'))
        final_df = final_df.drop(columns=['fbref_name', 'Player_fb']).rename(columns={'Player_tm': 'Player'})
        
        print(f"✅ Final merged dataset contains {len(final_df)} players who successfully bridged TM and FBref.")
        display(final_df.head())
    except Exception as e:
        print("Merge error:", e)
        final_df = pd.DataFrame()
else:
    print("Skipping merge because NO FBRef data was retrieved.")
    final_df = pd.DataFrame()
    display(final_df.head())
""")

# Markdown: Feature Eng
cell_9 = nbf.v4.new_markdown_cell("""## 4. Unearthing the Gems: Contribution & Value Scores

We combine attacking and defending metrics into a single `Total Contribution Score`, then divide by `Market Value` to find the most efficient players (the hidden gems).""")

# Code: FE
cell_10 = nbf.v4.new_code_cell("""if not final_df.empty:
    # Use .get() safely for synthetic scores
    xG   = pd.to_numeric(final_df.get('xG',   0), errors='coerce').fillna(0)
    xAG  = pd.to_numeric(final_df.get('xAG',  0), errors='coerce').fillna(0)
    PrgP = pd.to_numeric(final_df.get('PrgP', 0), errors='coerce').fillna(0)
    PrgC = pd.to_numeric(final_df.get('PrgC', 0), errors='coerce').fillna(0)
    SoT  = pd.to_numeric(final_df.get('SoT',  0), errors='coerce').fillna(0)
    
    off_tot = xG + xAG + PrgP + PrgC + SoT
    def_tot = pd.Series([0] * len(final_df), index=final_df.index)  # placeholder until more defensive data added
    
    # Natively normalize by '90s'
    final_df['Offensive Score'] = off_tot / final_df['90s']
    final_df['Defensive Score'] = def_tot / final_df['90s']
    
    final_df['Total Contribution Score'] = (OFF_WEIGHT * final_df['Offensive Score']) + (DEF_WEIGHT * final_df['Defensive Score'])
    
    # Calculate Value-for-Money (adding +1 smooth factor to avoid division by 0)
    final_df['Value-for-Money Score'] = final_df['Total Contribution Score'] / (final_df['Market Value (m)'] + 1)
    
    # Quadrant Classification
    avg_score = final_df['Total Contribution Score'].mean()
    
    def get_performer_type(row):
        score_high = row['Total Contribution Score'] >= avg_score
        price_high = row['Market Value (m)'] >= avg_market_value
        if score_high and not price_high: return "Hidden Gem (High Perf, Low Price)"
        if score_high and price_high: return "Star (High Perf, High Price)"
        if not score_high and not price_high: return "Depth (Low Perf, Low Price)"
        return "Overvalued (Low Perf, High Price)"
        
    final_df['performer_type'] = final_df.apply(get_performer_type, axis=1)
    
    final_df.to_csv("data/final_ranked_players.csv", index=False)
    print("💎 Scores generated and final rankings saved to 'data/final_ranked_players.csv'")
""")

# Code: Plotly Dashboard
cell_11 = nbf.v4.new_code_cell("""if not final_df.empty:
    # 1. The Value Quadrant Scatter Plot
    fig_scatter = px.scatter(
        final_df, 
        x='Total Contribution Score',
        y='Market Value (m)',
        color='performer_type',
        hover_data=['Offensive Score', 'Defensive Score', 'Pos', 'Age', 'Market Value (m)'],
        title="Championship Players: Performance vs Market Value",
        labels={'Market Value (m)': 'Market Value (€m)'},
        color_discrete_map={
            "Hidden Gem (High Perf, Low Price)": "green",
            "Star (High Perf, High Price)": "orange",
            "Depth (Low Perf, Low Price)": "gray",
            "Overvalued (Low Perf, High Price)": "red"
        }
    )
    
    # Add yardstick lines to create the 4 quadrants
    fig_scatter.add_hline(y=avg_market_value, line_dash="dash", line_color="red", annotation_text="Avg Market Value")
    fig_scatter.add_vline(x=avg_score, line_dash="dash", line_color="blue", annotation_text="Avg Contribution")
    
    # 2. Ranking Table of the top 10 Hidden Gems
    top_value = final_df.sort_values('Value-for-Money Score', ascending=False).head(10)
    fig_table = go.Figure(data=[go.Table(
        header=dict(values=['Player', 'Squad', 'Market Value (€m)', 'Total Score', 'Value Score'],
                    fill_color='paleturquoise',
                    align='left'),
        cells=dict(values=[top_value['Player'], top_value['Squad'], top_value['Market Value (m)'], 
                           round(top_value['Total Contribution Score'], 2), 
                           round(top_value['Value-for-Money Score'], 2)],
                   fill_color='lavender',
                   align='left'))
    ])
    fig_table.update_layout(title="Top 10 Value-for-Money Targets 💎")
    
    # Output to disk (reports/ keeps generated files off the root)
    import os as _os
    _os.makedirs('reports', exist_ok=True)
    with open('reports/championship_dashboard.html', 'w') as f:
        f.write("<h1>EFL Championship Analysis 25/26: Hidden Gems</h1>")
        f.write("<p>Weights Used: <strong>{}</strong> Offensive, <strong>{}</strong> Defensive.</p>".format(OFF_WEIGHT, DEF_WEIGHT))
        f.write(fig_scatter.to_html(full_html=False, include_plotlyjs='cdn'))
        f.write(fig_table.to_html(full_html=False, include_plotlyjs='cdn'))
        
    print("📊 Dashboard generated! Open 'reports/championship_dashboard.html' in your browser.")
    fig_scatter.show()
    fig_table.show()
""")

nb.cells = [cell_0, cell_1, cell_2, cell_3, cell_4, cell_5, cell_6, cell_7, cell_8, cell_9, cell_10, cell_11]

import os
os.makedirs('notebooks', exist_ok=True)
with open('notebooks/EFL_Championship_Analysis.ipynb', 'w', encoding='utf-8') as f:
    nbf.write(nb, f)
    
print("Notebook freshly written to notebooks/EFL_Championship_Analysis.ipynb")
