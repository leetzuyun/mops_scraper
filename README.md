# Description
This is a scraper designed specifically for the financial reports on MOPS, for the internal use ONLY of scraping reports with filters. If an official csv is available, the scraper downloads it; or it would parse the <table> elements and turn it into a csv file.
Each **query job** outputs a folder ("financial_reports") that contains the .xlsx files added from the input window. All of the tables from the request would be saved into the same file as multiple sheets.

# Requirements
## OS
- Windows 10/11, macOS 12+ or Linux(x86_64)
## Network
- Outbound HTTPS to TWSE/MOPS
- If your company performs TLS inspection/SSL prxy, configure a corporate root CA (see **TLS notes**)
## Python
- Python 3.11+ (recommended)
> We pinned numpy==2.4.3, which requires Python >= 3.11

## Python packages
```
beautifulsoup4     4.14.3
certifi            2026.2.25
charset-normalizer 3.4.6
colorama           0.4.6
et-xmlfile         2.0.0
greenlet           3.3.2
idna               3.11
lxml               6.0.2
numpy              2.4.3
openpyxl           3.1.5
pandas             3.0.1
python-dateutil    2.9.0.post0
requests           2.32.5
six                1.17.0
soupsieve          2.8.3
tqdm               4.67.3
typing-extensions  4.15.0
tzdata             2025.3
urllib3            2.6.3
```

## TLS notes
If your organization intercepts HTTPS traffic, configure `requests` to trust your corporate root CA.

**Windows (PowerShell)**
```
$env:REQUESTS_CA_BUNDLE="C:\path\to\corp-root.pem"
```

**Windows(CMD)**
```
set REQUESTS_CA_BUNDLE=C:\path\to\corp-root.pem
```

**macOS/Linux (bash/zsh)**
```
export REQUESTS_CA_BUNDLE=/path/to/corp-root.pem
```
For quick testing, the GUI has a “Skip TLS verification (test only)” toggle. Use it only to validate connectivity—prefer the CA method for real runs.

# How to run it on your device
## Run with uv (recomended)
**install uv**
```
# via pipx
pipx install uv
# or via pip
pip install --user uv
```
**run**
```
uv run input_window.py
```
uv run resolves/isolate dependencies using pyproject.toml/uv.lock and launches GUI.

## Run without uv (python + pip)
```
# 1) Create & activate a venv
python -m venv .venv

# Windows
.\.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

# 2) Install dependencies
pip install --upgrade pip
pip install -r requirements.txt

# 3) Run
python input_window.py
```

## Workflow
- Calls MOPS **AJAX endpoints** via requests
- If the page exposes a download button that specifies "另存 CSV", the app attempts this download first.
- When no CSV/XLS exists, all tables on the page are parsed and written to one Excel per job (multiple sheets).

**Output**
- financial_reports/: one Excel per query job, named by the query tag (e.g., 資產負債表-sii-2025-Q4-ALL.xlsx)
- downloads/: official CSV/XLS if present
- debug_out/: raw *-result.html per job (diagnostics)