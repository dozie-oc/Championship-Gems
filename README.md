# EFL Championship 2025-26: Player Analysis Pipeline

An advanced, decoupled, and highly reliable data analysis pipeline identifying undervalued and overvalued players in the EFL Championship.

## 📁 Project Structure

```
Championship/
├── scraper.py            # Data engineering layer — scrapes TM + FBref to data/raw/
├── build_notebook.py     # Generates notebooks/EFL_Championship_Analysis.ipynb
├── requirements.txt
├── README.md
├── chip/                 # Python virtual environment
├── data/
│   ├── raw/              # Scraped CSV inputs (read by the notebook)
│   │   ├── transfermarkt_top200.csv
│   │   ├── fbref_standard.csv
│   │   └── fbref_shooting.csv
│   ├── player_mapping.json   # Manual TM→FBref name overrides
│   └── final_ranked_players.csv  # Pipeline output
├── notebooks/
│   └── EFL_Championship_Analysis.ipynb
├── reports/              # Generated HTML outputs
│   ├── championship_dashboard.html
│   └── EFL_Championship_Analysis_executed.html
└── scripts/              # Dev utilities (diagnostics, exploration, tests)
```

## 🚀 Decoupled Architecture

* **`scraper.py`** — Engineering layer. Bypasses Cloudflare via the Wayback archive proxy and
  saves clean flat CSVs to `data/raw/`. Includes early-termination logic: if Transfermarkt starts
  returning a repeated page it stops immediately, preventing duplicate player rows.
* **`build_notebook.py`** — Generates the Jupyter notebook programmatically. Run after any
  pipeline logic changes.
* **`notebooks/EFL_Championship_Analysis.ipynb`** — Science layer. Loads CSVs, applies dynamic
  thresholding, computes scores, and renders interactive Plotly diagnostics.

## ⚙️ Analytics Implementations

* **Fuzzy Name Matching** — `thefuzz` at ≥75% + a manual `data/player_mapping.json` override
  dictionary to bridge TM/FBref spelling differences.
* **Dynamic Minutes Filter** — Uses `0.25 × max_90s` instead of a hardcoded cutoff, so the
  pipeline stays valid regardless of when in the season it runs.
* **Configurable Scoring** — `0.6 × Offensive + 0.4 × Defensive` weights produce the
  `Total Contribution Score` matched against the market-value yardstick.
* **Deduplication Guard** — Both `scraper.py` and the notebook cell deduplicate the Transfermarkt
  data before it reaches the merge step, preventing inflated player counts.

> **Note on player count:** Transfermarkt's Championship market-value list currently surfaces
> ~100 ranked players. The pipeline collects all available pages; the file is named
> `transfermarkt_top200.csv` for naming continuity but will contain however many players
> the site currently exposes (typically 100).

## 🏃 Run Instructions

1. `pip install -r requirements.txt`
2. Scrape fresh data: `python scraper.py`
3. (Optional) Rebuild notebook: `python build_notebook.py`
4. Open `notebooks/EFL_Championship_Analysis.ipynb` in Jupyter and run all cells.
5. Outputs: `data/final_ranked_players.csv` · `reports/championship_dashboard.html`