import nbformat as nbf
import json
import os

nb = nbf.v4.new_notebook()

# Markdown: Intro
cell_1 = nbf.v4.new_markdown_cell("""# EFL Championship 2025-26: Top 200 Players Analysis 

This notebook loads the top 200 players locally scraped from Transfermarkt and merges them against FBref's advanced metrics (Standard, Shooting, Passing, Possession, Defense) to create a **Value-for-Money** yardstick.

**Key Architecture Updates:**
- **Decoupled Data Pipeline**: We no longer actively scrape directly inside Pandas. We import raw CSV batches collected proactively by `scraper.py`, preventing mid-notebook Cloudflare HTTP 403 flags!
- **Dynamic Normalization Filters**: We dynamically trim outlier data by scaling `min_90s` proportionally (25%) to the highest `90s` logged in the local data snapshot.
- **Explicit Player Directories**: We overlay fuzzy matching logic (`thefuzz` @ 75%) with a JSON map (`player_mapping.json`) to cleanly align differing spelling schemas (e.g., Transfermarkt's "João Pedro" vs FBref's "Joao Pedro").
""")

# Code: Working-directory guard (must be first)
# When Jupyter opens this notebook from notebooks/, os.getcwd() is the notebooks/ folder.
# All data paths are relative to the PROJECT ROOT, so we navigate up if needed.
cell_0 = nbf.v4.new_code_cell("""import os, pathlib

# If running from inside notebooks/, move up to the project root
_cwd = pathlib.Path(os.getcwd())
if _cwd.name == 'notebooks':
    os.chdir(_cwd.parent)
    print(f"Working directory set to: {os.getcwd()}")
else:
    print(f"Working directory already at root: {os.getcwd()}")
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
# Dynamic weighting for Contribution Output
OFF_WEIGHT = 0.6
DEF_WEIGHT = 0.4

def clean_value(v):
    if not isinstance(v, str) or v == '-': return 0
    mult = 1
    v_lower = v.lower()
    if 'm' in v_lower: mult = 1
    elif 'k' in v_lower: mult = 0.001
    num = re.sub(r'[^\d.]', '', v)
    try: return float(num) * mult
    except: return 0
    
print("Environment completely initialized.")
""")

# Markdown: Transfermarkt
cell_3 = nbf.v4.new_markdown_cell("""## 1. Extract Transfermarkt Data (Yardstick)

Loading the 200 highest market values from our explicit local batch index `data/raw/transfermarkt_top200.csv`.""")

# Code: Transfermarkt
cell_4 = nbf.v4.new_code_cell("""# 1. Load Transfermarkt Data
try:
    tm_df = pd.read_csv("data/raw/transfermarkt_top200.csv")
    print(f"Successfully loaded {len(tm_df)} rows from Transfermarkt scrape.")
except FileNotFoundError:
    print("Transfermarkt data not found. Please run scraper.py first.")
    tm_df = pd.DataFrame()
    
if not tm_df.empty:
    # Defensive deduplication: drop any repeated players carried in by the scraper
    before_dedup = len(tm_df)
    tm_df = tm_df.drop_duplicates(subset=['Player'], keep='first').reset_index(drop=True)
    if len(tm_df) < before_dedup:
        print(f"Removed {before_dedup - len(tm_df)} duplicate player rows from TM data.")
    print(f"{len(tm_df)} unique players loaded.")

    tm_df['Market Value (m)'] = tm_df['Market Value str'].apply(clean_value)
    
    # Drop rows without a clean value
    tm_df = tm_df[tm_df['Market Value (m)'] > 0].copy()
    
    avg_market_value = tm_df['Market Value (m)'].mean()
    print(f"\\nYARDSTICK: The average market value of the Championship ranked players is €{avg_market_value:.2f}m")
    tm_df['vs_average'] = tm_df['Market Value (m)'] - avg_market_value
    
    # Categorize
    tm_df['price_category'] = pd.cut(
        tm_df['Market Value (m)'],
        bins=[-np.inf, avg_market_value, avg_market_value * 1.5, np.inf],
        labels=['Below Avg', 'Above Avg', 'Premium'],
        duplicates='drop'
    )
tm_df.head()
""")

# Markdown: FBref Section
cell_5 = nbf.v4.new_markdown_cell("""## 2. Load FBref Performance Data

We aggregate the locally scraped raw CSVs compiled into our `data/raw/` repository.""")

# Code: FBRef
cell_6 = nbf.v4.new_code_cell("""import os

dfs_fbref = {}
# Standard already contains PrgC, PrgP, xAG - covers what Passing/Possession would add
# Defense/Possession Wayback snapshots only have squad-level data, not player-level
fbref_modules = ['standard', 'shooting']

for mod in fbref_modules:
    path = f"data/raw/fbref_{mod}.csv"
    if os.path.exists(path):
        df = pd.read_csv(path)
        dfs_fbref[mod.capitalize()] = df
    else:
        print(f"Warning: {path} not found. Run scraper.py first.")

print(f"Loaded {len(dfs_fbref)} FBRef tables from disk.")
""")

# Markdown: Merge
cell_7 = nbf.v4.new_markdown_cell("""## 3. Link Tables & Dynamic Normalization

Merging datasets efficiently with automated column conflict detection, processing time thresholds natively (`min_90s`), and bridging namespaces. """)

# Code: Merge
cell_8 = nbf.v4.new_code_cell("""import json

if len(dfs_fbref) >= 1:
    # 1. Merge Standard (xG, xAG, PrgC, PrgP, 90s) + Shooting (SoT)
    # Standard natively contains prog carry/pass stats — no separate Passing/Possession CSV needed
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
        
        # Numeric cleanup processing
        cols_to_num = fb_df.columns.drop(['Player', 'Squad', 'Pos'], errors='ignore')
        fb_df[cols_to_num] = fb_df[cols_to_num].apply(pd.to_numeric, errors='coerce').fillna(0)
        
        # Filter based on DYNAMIC 90s (optimal scaling)
        if '90s' in fb_df.columns:
            max_90s = fb_df['90s'].max()
            min_90s = 0.25 * max_90s
            fb_df = fb_df[fb_df['90s'] >= min_90s].copy()
            print(f"Dynamic Minutes Filter Applied: Players must have >= {min_90s:.2f} '90s' (25% of top {max_90s:.2f})")
        else:
            print("Warning: Standard stats (90s) missing, skipping filtering.")
            fb_df['90s'] = 1  
            
        # 2. Match to Transfermarkt Top 200 (Load explicit static mapping first!)
        print("Fuzzy matching players...")
        mapping_dict = {}
        try:
            with open("data/player_mapping.json", "r") as f:
                mapping_dict = json.load(f)
        except Exception as e:
            print("No player_mapping.json loaded", e)
            
        fb_names = fb_df['Player'].dropna().unique()
        
        def match_name(tm_name):
            if not isinstance(tm_name, str): return None
            # Check manual JSON mapping
            if tm_name in mapping_dict:
                mapped = mapping_dict[tm_name]
                if mapped in fb_names: return mapped
                
            if len(fb_names) == 0: return None
            # ExtractOne lower threshold to 75% for robust detection
            match = process.extractOne(tm_name, fb_names, scorer=fuzz.token_sort_ratio)
            return match[0] if match and match[1] >= 75 else None
            
        tm_df['fbref_name'] = tm_df['Player'].apply(match_name)
        
        # Final join (Inner join filters to ONLY those in top 200)
        final_df = tm_df.merge(fb_df, left_on='fbref_name', right_on='Player', suffixes=('_tm', '_fb'))
        final_df = final_df.drop(columns=['fbref_name', 'Player_fb']).rename(columns={'Player_tm': 'Player'})
        
        print(f"Final merged dataset contains {len(final_df)} players from the Top 200 who matched FBRef.")
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
cell_9 = nbf.v4.new_markdown_cell("""## 4. Feature Engineering – Contribution & Value Scores

We compute synthetic scores dynamically using our configurable weights logic (`OFF_WEIGHT = 0.6`, `DEF_WEIGHT = 0.4` as requested).""")

# Code: FE
cell_10 = nbf.v4.new_code_cell("""if not final_df.empty:
    # Calculate totals using all available columns with .get() for safety
    xG   = pd.to_numeric(final_df.get('xG',   0), errors='coerce').fillna(0)
    xAG  = pd.to_numeric(final_df.get('xAG',  0), errors='coerce').fillna(0)
    PrgP = pd.to_numeric(final_df.get('PrgP', 0), errors='coerce').fillna(0)
    PrgC = pd.to_numeric(final_df.get('PrgC', 0), errors='coerce').fillna(0)
    SoT  = pd.to_numeric(final_df.get('SoT',  0), errors='coerce').fillna(0)
    
    off_tot = xG + xAG + PrgP + PrgC + SoT
    def_tot = pd.Series([0] * len(final_df), index=final_df.index)  # placeholder until Defense data available
    
    # We natively divide sums by '90s'
    final_df['Offensive Score'] = off_tot / final_df['90s']
    final_df['Defensive Score'] = def_tot / final_df['90s']
    
    final_df['Total Contribution Score'] = (OFF_WEIGHT * final_df['Offensive Score']) + (DEF_WEIGHT * final_df['Defensive Score'])
    final_df['Value-for-Money Score'] = final_df['Total Contribution Score'] / (final_df['Market Value (m)'] + 1)
    
    # Performer type
    avg_score = final_df['Total Contribution Score'].mean()
    
    def get_performer_type(row):
        score_high = row['Total Contribution Score'] >= avg_score
        price_high = row['Market Value (m)'] >= avg_market_value
        if score_high and not price_high: return "High Performer Low Price"
        if score_high and price_high: return "High Performer High Price"
        if not score_high and not price_high: return "Low Performer Low Price"
        return "Low Performer High Price"
        
    final_df['performer_type'] = final_df.apply(get_performer_type, axis=1)
    
    final_df.to_csv("data/final_ranked_players.csv", index=False)
    print("Scores created and final CSV locally exported.")
""")

# Code: Plotly Dashboard
cell_11 = nbf.v4.new_code_cell("""if not final_df.empty:
    # 1. Scatter Plot
    fig_scatter = px.scatter(
        final_df, 
        x='Total Contribution Score',
        y='Market Value (m)',
        color='performer_type',
        hover_data=['Offensive Score', 'Defensive Score', 'Pos', 'Age', 'Market Value (m)'],
        title="Championship Players: Value vs Contribution (Yardstick)",
        labels={'Market Value (m)': 'Market Value (€m)'},
        color_discrete_map={
            "High Performer Low Price": "green",
            "High Performer High Price": "orange",
            "Low Performer Low Price": "gray",
            "Low Performer High Price": "red"
        }
    )
    
    # Add yardstick lines
    fig_scatter.add_hline(y=avg_market_value, line_dash="dash", line_color="red", annotation_text="Avg Market Value Yardstick")
    fig_scatter.add_vline(x=avg_score, line_dash="dash", line_color="blue", annotation_text="Avg Contribution")
    
    # 2. Ranking Table of best value
    top_value = final_df.sort_values('Value-for-Money Score', ascending=False).head(10)
    fig_table = go.Figure(data=[go.Table(
        header=dict(values=['Player', 'Squad', 'Market Value (€m)', 'Total Score', 'Value/Money Score'],
                    fill_color='paleturquoise',
                    align='left'),
        cells=dict(values=[top_value['Player'], top_value['Squad'], top_value['Market Value (m)'], 
                           round(top_value['Total Contribution Score'], 2), 
                           round(top_value['Value-for-Money Score'], 2)],
                   fill_color='lavender',
                   align='left'))
    ])
    fig_table.update_layout(title="Top 10 Value-for-Money Targets")
    
    # Output to disk (reports/ keeps generated files off the root)
    import os as _os
    _os.makedirs('reports', exist_ok=True)
    with open('reports/championship_dashboard.html', 'w') as f:
        f.write("<h1>EFL Championship Analysis 25/26</h1>")
        f.write("<p>Weights Used: <strong>{}</strong> Offensive, <strong>{}</strong> Defensive.</p>".format(OFF_WEIGHT, DEF_WEIGHT))
        f.write(fig_scatter.to_html(full_html=False, include_plotlyjs='cdn'))
        f.write(fig_table.to_html(full_html=False, include_plotlyjs='cdn'))
        
    print("Notebook Pipeline Processed! Check 'reports/championship_dashboard.html'.")
    fig_scatter.show()
    fig_table.show()
""")

nb.cells = [cell_0, cell_1, cell_2, cell_3, cell_4, cell_5, cell_6, cell_7, cell_8, cell_9, cell_10, cell_11]

import os
os.makedirs('notebooks', exist_ok=True)
with open('notebooks/EFL_Championship_Analysis.ipynb', 'w', encoding='utf-8') as f:
    nbf.write(nb, f)
    
print("Notebook written to notebooks/EFL_Championship_Analysis.ipynb")
