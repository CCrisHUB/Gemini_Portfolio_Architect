#01_ingestion_engine.py
#"""
#Avenue C Ingestion Engine
#Date: 2026-09-10
#Version: 2.0.6 (3-CSV Architecture & Dynamic Savings Calculation)
#Role: Ingests E*TRADE CSVs, parses Core Files, queries Gemini API, and archives state.
#"""
__version__ = "2.0.6"
__date__ = "2026-09-10"

import pandas as pd
import os
import io
import json
import re
import glob
import shutil
from datetime import datetime, timedelta
from google import genai
from google.genai import types
from dotenv import load_dotenv

# Define decoupled directory paths
DIR_CORE_ACTIVE = "00_CORE_Files"
DIR_CORE_ARCHIVE = "05_OLD_Core_Files"
DIR_CSV_ACTIVE = "20_CSV_Downloads_Current"
DIR_CSV_ARCHIVE = "50_OLD_CSV_Files"

def get_latest_file(directory, pattern):
    files = glob.glob(os.path.join(directory, pattern))
    if not files:
        raise FileNotFoundError(f"FATAL: No files found matching pattern: {pattern} in {directory}")
    return sorted(files)[-1]

def parse_previous_ledger(core_dir):
    print("System: Parsing previous ledger for persistent state...")
    files = glob.glob(os.path.join(core_dir, "GEM_Retirement_Portfolio_Ledger_*.txt"))
    if not files:
        raise FileNotFoundError("FATAL: No previous ledger found to extract state.")
    
    latest_file = sorted(files)[-1]
    
    # Dynamically extract the ledger version from the filename
    version_match = re.search(r'_v(\d+)\.txt', latest_file)
    ledger_version = int(version_match.group(1)) if version_match else 0
    
    with open(latest_file, 'r', encoding='utf-8') as f:
        content = f.read()
        
    tax_match = re.search(r'(PERSISTENT YTD TAX LEDGER.*?)(?=\n-{50,}\n+DATE-AWARE SPENDING PACING ENGINE)', content, re.DOTALL)
    tax_text = tax_match.group(1).strip() if tax_match else "PERSISTENT YTD TAX LEDGER\n[DATA NOT FOUND]"
    
    b1_match = re.search(r'(\[BUCKET 1\] LIQUIDITY & PRESERVATION.*?)(?=\n-{50,}\n+\[BUCKET 2\])', content, re.DOTALL)
    b1_text = b1_match.group(1).strip() if b1_match else "[BUCKET 1] LIQUIDITY & PRESERVATION\n[DATA NOT FOUND]"
    
    uninvested = float(re.search(r'Uninvested Brokerage Cash.*?\$\s*([\d,]+\.\d{2})', content).group(1).replace(',', '')) if re.search(r'Uninvested Brokerage Cash.*?\$\s*([\d,]+\.\d{2})', content) else 0.0
    op_cash = float(re.search(r'Operational Cash Buffer.*?\$\s*([\d,]+\.\d{2})', content).group(1).replace(',', '')) if re.search(r'Operational Cash Buffer.*?\$\s*([\d,]+\.\d{2})', content) else 0.0
    etrade_cds = float(re.search(r'E\*TRADE CD Ladder.*?\$\s*([\d,]+\.\d{2})', content).group(1).replace(',', '')) if re.search(r'E\*TRADE CD Ladder.*?\$\s*([\d,]+\.\d{2})', content) else 0.0
    ext_cds = float(re.search(r'External Bank Capital.*?\$\s*([\d,]+\.\d{2})', content).group(1).replace(',', '')) if re.search(r'External Bank Capital.*?\$\s*([\d,]+\.\d{2})', content) else 0.0
    
    dynamic_ticker_map = {}
    bucket_blocks = re.findall(r'\[BUCKET (\d)\](.*?)(?=\n\[BUCKET|\n={80})', content, re.DOTALL)
    for b_num, b_content in bucket_blocks:
        b_idx = int(b_num)
        if b_idx >= 2:
            tickers = re.findall(r'\*\s+([A-Z]+)\s+:', b_content)
            for t in tickers:
                dynamic_ticker_map[t] = b_idx
                
    milestone_match = re.search(r'ROLLING HISTORICAL MILESTONE LEDGER.*?\n\[Date.*?\]\n(.*?)(?=\n={80})', content, re.DOTALL)
    milestones = milestone_match.group(1).strip().split('\n') if milestone_match and milestone_match.group(1).strip() else []
                
    return {
        'tax_ledger': tax_text, 
        'bucket_1': b1_text, 
        'uninvested_cash': uninvested, 
        'op_cash': op_cash, 
        'etrade_cds': etrade_cds, 
        'ext_cds': ext_cds,
        'ticker_map': dynamic_ticker_map,
        'milestones': milestones,
        'ledger_version': ledger_version,
        'file_path': latest_file
    }

def process_tax_and_wash_sales(tax_ledger_text, gains_files, sold_tickers):
    today = datetime.now()
    today_str = today.strftime("%Y-%m-%d")
    
    # --- 1. WASH SALE TRACKER ---
    wash_sale_match = re.search(r'(30-DAY WASH-SALE LOCKOUT TRACKER:\n)(.*?)(?=\n-{50,})', tax_ledger_text, re.DOTALL)
    if wash_sale_match:
        tracker_header = wash_sale_match.group(1)
        tracker_body = wash_sale_match.group(2).strip()
        
        active_lockouts = []
        if tracker_body and "[NO ACTIVE LOCKOUTS]" not in tracker_body.upper():
            for line in tracker_body.split('\n'):
                match = re.search(r'-\s+([A-Z]+)\s+\|\s+Date Sold:\s+([\d-]+)\s+\|\s+Lockout Expiry:\s+([\d-]+)', line)
                if match:
                    ticker, date_sold, expiry = match.groups()
                    if datetime.strptime(expiry, "%Y-%m-%d") >= today:
                        active_lockouts.append(line.strip())
                        
        expiry_new = (today + timedelta(days=30)).strftime("%Y-%m-%d")
        for st in sold_tickers:
            active_lockouts.append(f"  - {st} | Date Sold: {today_str} | Lockout Expiry: {expiry_new}")
            
        new_tracker_body = "\n".join(active_lockouts) if active_lockouts else "  - [NO ACTIVE LOCKOUTS]"
        new_tracker_block = tracker_header + new_tracker_body + "\n"
        tax_ledger_text = tax_ledger_text[:wash_sale_match.start()] + new_tracker_block + tax_ledger_text[wash_sale_match.end():]

    # --- 2. REALIZED GAINS MATH ---
    if not gains_files:
        return tax_ledger_text
        
    stcg_match = re.search(r'Realized Short-Term Capital Gains YTD:\s+([+-]?)\$?([\d,]+\.\d{2})', tax_ledger_text)
    ltcg_match = re.search(r'Realized Long-Term Capital Gains \(LTCG\) YTD:\s+([+-]?)\$?([\d,]+\.\d{2})', tax_ledger_text)
    headroom_match = re.search(r'Starting 0% LTCG Headroom:\s+\$?([\d,]+\.\d{2})', tax_ledger_text)
    
    current_stcg = float(stcg_match.group(1) + stcg_match.group(2).replace(',', '')) if stcg_match else 0.0
    current_ltcg = float(ltcg_match.group(1) + ltcg_match.group(2).replace(',', '')) if ltcg_match else 0.0
    starting_headroom = float(headroom_match.group(1).replace(',', '')) if headroom_match else 49200.0
    
    new_stcg, new_ltcg = 0.0, 0.0
    event_logs = []
    
    for gf in gains_files:
        try:
            with open(gf, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                
            summary_idx = next((i for i, line in enumerate(lines) if 'TAXABLE G&L SUMMARY' in line), -1)
            if summary_idx == -1:
                print(f"Warning: Could not find TAXABLE G&L SUMMARY in {gf}")
                continue
                
            summary_csv = "\n".join(lines[summary_idx+1:summary_idx+3])
            df = pd.read_csv(io.StringIO(summary_csv))
            df.columns = df.columns.str.strip().str.lower()
            
            file_stcg, file_ltcg = 0.0, 0.0
            st_cols = [c for c in df.columns if 'short' in c and 'gain' in c]
            lt_cols = [c for c in df.columns if 'long' in c and 'gain' in c]
            
            if st_cols:
                file_stcg = pd.to_numeric(df[st_cols[0]].astype(str).str.replace(r'[$,]', '', regex=True), errors='coerce').fillna(0).sum()
            if lt_cols:
                file_ltcg = pd.to_numeric(df[lt_cols[0]].astype(str).str.replace(r'[$,]', '', regex=True), errors='coerce').fillna(0).sum()
                
            new_stcg += file_stcg
            new_ltcg += file_ltcg
            
            ticker_name = os.path.basename(gf).replace('RealizedGains_', '').replace('.csv', '')
            log_entry = f"  - {today_str} | Realized Gains Ingestion ({ticker_name})\n"
            if file_stcg != 0:
                log_entry += f"    * Net Realized STCG: {'+' if file_stcg >= 0 else ''}${file_stcg:,.2f}\n"
            if file_ltcg != 0:
                log_entry += f"    * Net Realized LTCG: {'+' if file_ltcg >= 0 else ''}${file_ltcg:,.2f}\n"
                
            if file_stcg != 0 or file_ltcg != 0:
                event_logs.append(log_entry.rstrip())
                
        except Exception as e:
            print(f"Warning: Could not parse gains from {gf}: {e}")
            
    if new_stcg == 0 and new_ltcg == 0:
        return tax_ledger_text
        
    updated_stcg = current_stcg + new_stcg
    updated_ltcg = current_ltcg + new_ltcg
    remaining_headroom = starting_headroom - updated_ltcg
    
    if event_logs:
        log_insertion = "\n".join(event_logs) + "\n\nYTD Cumulative Tax Summary:"
        tax_ledger_text = tax_ledger_text.replace("YTD Cumulative Tax Summary:", log_insertion)
        
    def format_currency(val):
        return f"-${abs(val):,.2f}" if val < 0 else f"+${val:,.2f}" if val > 0 else f"${val:,.2f}"
        
    tax_ledger_text = re.sub(r'(Realized Short-Term Capital Gains YTD:\s+)[+-]?\$[\d,]+\.\d{2}', r'\g<1>' + format_currency(updated_stcg).replace('\\', '\\\\'), tax_ledger_text)
    tax_ledger_text = re.sub(r'(Realized Long-Term Capital Gains \(LTCG\) YTD:\s+)[+-]?\$[\d,]+\.\d{2}', r'\g<1>' + format_currency(updated_ltcg).replace('\\', '\\\\'), tax_ledger_text)
    tax_ledger_text = re.sub(r'(Remaining 0% LTCG Headroom:\s+)[+-]?\$[\d,]+\.\d{2}', r'\g<1>' + f"${remaining_headroom:,.2f}".replace('\\', '\\\\'), tax_ledger_text)
    
    return tax_ledger_text

def load_and_clean_csv(filepath):
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"FATAL: Missing required file: {filepath}")
    print(f"System: Parsing {os.path.basename(filepath)}...")
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    header_index = -1
    for i, line in enumerate(lines):
        if line.strip().startswith("Symbol,Last Price $"):
            header_index = i
            break
    if header_index == -1:
        raise ValueError(f"FATAL: Could not find the main data table header in {filepath}.")
    clean_csv_string = "".join(lines[header_index:])
    df = pd.read_csv(io.StringIO(clean_csv_string), on_bad_lines='skip')
    df.columns = df.columns.str.strip()
    return df

def disaggregate_holdings(df_all, df_ira):
    print("System: Executing deterministic disaggregation...")
    required_cols = ['Symbol', 'Quantity', 'Last Price $', 'Value $', 'Price Paid $', 'Total Gain $']
    for col in required_cols:
        if col not in df_all.columns or col not in df_ira.columns:
            raise ValueError(f"FATAL: Missing required column '{col}' in CSVs.")

    df_all['Symbol'] = df_all['Symbol'].astype(str).str.strip()
    df_ira['Symbol'] = df_ira['Symbol'].astype(str).str.strip()

    for col in ['Quantity', 'Last Price $', 'Value $', 'Price Paid $', 'Total Gain $']:
        df_all[col] = pd.to_numeric(df_all[col].astype(str).str.replace(r'[$,]', '', regex=True), errors='coerce').fillna(0)
        df_ira[col] = pd.to_numeric(df_ira[col].astype(str).str.replace(r'[$,]', '', regex=True), errors='coerce').fillna(0)

    ira_holdings = df_ira.set_index('Symbol').to_dict('index')
    all_holdings = df_all.set_index('Symbol').to_dict('index')
    taxable_holdings = {}

    for symbol, all_data in all_holdings.items():
        # ANTI-GIGO FIX: Drop cash, totals, and E*TRADE timestamp garbage
        if symbol.lower() in ['cash', 'total', 'nan', ''] or 'generated' in symbol.lower() or len(symbol) > 10:
            continue
            
        if symbol in ira_holdings:
            ira_data = ira_holdings[symbol]
            taxable_qty = all_data['Quantity'] - ira_data['Quantity']
            taxable_val = all_data['Value $'] - ira_data['Value $']
            taxable_gain = all_data['Total Gain $'] - ira_data['Total Gain $']
            
            if taxable_qty > 0.001:
                taxable_holdings[symbol] = {
                    'Quantity': round(taxable_qty, 4),
                    'Last Price $': all_data['Last Price $'],
                    'Value $': round(taxable_val, 2),
                    'Price Paid $': all_data['Price Paid $'],
                    'Total Gain $': round(taxable_gain, 2),
                    'Basis $': round(taxable_val - taxable_gain, 2)
                }
        else:
            taxable_holdings[symbol] = {
                'Quantity': all_data['Quantity'],
                'Last Price $': all_data['Last Price $'],
                'Value $': all_data['Value $'],
                'Price Paid $': all_data['Price Paid $'],
                'Total Gain $': all_data['Total Gain $'],
                'Basis $': round(all_data['Value $'] - all_data['Total Gain $'], 2)
            }
            
    clean_ira_holdings = {}
    for sym, data in ira_holdings.items():
        if sym.lower() in ['cash', 'total', 'nan', ''] or 'generated' in sym.lower() or len(sym) > 10:
            continue
        data['Basis $'] = round(data['Value $'] - data['Total Gain $'], 2)
        clean_ira_holdings[sym] = data

    return taxable_holdings, clean_ira_holdings

def query_strategic_routing(telemetry_payload):
    print("System: Querying Neuro-Symbolic API for Strategic Routing (Live Web Search Enabled)...")
    load_dotenv()
    client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
    prompt = f"""
    You are a deterministic financial routing API. Evaluate the following telemetry payload and return ONLY a valid JSON object. 
    CRITICAL: Do not include markdown formatting, backticks, or search citations in your output. Output ONLY the JSON object starting with {{ and ending with }}.
    
    TELEMETRY PAYLOAD: {json.dumps(telemetry_payload)}
    
    REQUIRED JSON RESPONSE:
    1. "cpi_rate": Search the web for the current U.S. CPI-U annual inflation rate (float).
    2. "std_deduction": Current IRS Standard Deduction for Single filer (float).
    3. "ltcg_limit": Current IRS max taxable income for 0% LTCG bracket Single filer (float).
    4. "market_state": Search the web for the S&P 500 performance over the last 30 days. Return exactly: "DIP / CORRECTION", "NEUTRAL / SIDEWAYS", or "RALLY / EXPANSION".
    5. "sourcing_decision": Based on the Tank Capacity Ratio in the payload and the market state, return the routing decision.
    """
    try:
        chat = client.chats.create(
            model='gemini-3.6-flash',
            config=types.GenerateContentConfig(
                temperature=0.0,
                tools=[{"google_search": {}}]
            )
        )
        response = chat.send_message(prompt)
        
        if not response.text:
            raise ValueError("API returned an empty text response.")
            
        # Bulletproof JSON extraction (ignores citations/markdown)
        raw_text = response.text.strip()
        start_idx = raw_text.find('{')
        end_idx = raw_text.rfind('}') + 1
        
        if start_idx != -1 and end_idx != 0:
            json_str = raw_text[start_idx:end_idx]
            return json.loads(json_str)
        else:
            raise ValueError(f"Failed to extract JSON from API response: {raw_text}")
            
    except Exception as e:
        raise RuntimeError(f"API Boundary Failure: {e}")

def generate_master_constants(routing_data, current_version=87):
    print("System: Generating Core File 1 (Master Constants)...")
    new_version = current_version + 1
    today = datetime.now().strftime("%Y-%m-%d")
    
    cpi = routing_data.get('cpi_rate', 3.36)
    std_ded = routing_data.get('std_deduction', 16100.0)
    ltcg = routing_data.get('ltcg_limit', 49200.0)
    max_gross = std_ded + ltcg
    
    content = f"""================================================================================
MASTER PROFILE CONSTANTS & FINANCIAL PARAMETERS
Date: {today} (Version {new_version})
Role: Core File 1 - Master Constants and Version Manifest
File Name: GEM_Retirement_Master_Profile_Constants_{today}_v{new_version}.txt
================================================================================

0. ACTIVE CORE FILE VERSION MANIFEST
--------------------------------------------------------------------------------
The following filenames specify the authoritative active version for each of
the Core Files and Active Mega-Prompts governing this Gem. 

  - Core File 1 (Master Constants):
    GEM_Retirement_Master_Profile_Constants_{today}_v{new_version}.txt
  - Core File 2 (Portfolio Ledger):
    GEM_Retirement_Portfolio_Ledger_{today}_v39.txt
  - Core File 3 (Custom Instructions):
    GEM_Retirement_and_Portfolio_Architect_Custom_Instructions_2026-09-01_v30.txt

  - Active Mega-Prompts:
    * 01_ETrade_CSV_Ingestion_and_Portfolio_Ledger_Update_Prompt_2026-08-31_v45.txt
    * 02_Fund_Performance_and_Structural_Audit_Prompt_2026-08-30_v33.txt
    * 03_Trend_Tracking_and_Financial_Pacing_Prompt_2026-08-25_v4.txt
    * 04_Spending_Request_and_Affordability_Evaluation_Prompt_2026-08-25_v3.txt
    * 05_Dynamic_Custom_Sourcing_and_Multi_Bucket_Exemption_Prompt_2026-08-31_v22.txt
    * 06_Dynamic_Standard_Cash_Withdrawal_Request_Prompt_2026-08-31_v23.txt
    * 07_Expense_Payload_Patching_Prompt_2026-09-01_v1.txt

--------------------------------------------------------------------------------

1. DEMOGRAPHIC, TAX & RMD STATUS
   - Investor Status: Single widower, no dependents / no heirs.
   - Date of Birth: September 21, 1955 (RMD Initial Year: 2028 / Age 73).
   - Tax Filing Status: Single.
   - CONST_ACTIVE_STD_DEDUCTION: ${std_ded:,.2f} (Tax Year 2026)
   - CONST_ACTIVE_0PCT_LTCG_LIMIT: ${ltcg:,.2f} taxable income (Tax Year 2026).
   - CONST_ACTIVE_MAX_GROSS_0PCT_LTCG: ${max_gross:,.2f} (${ltcg:,.0f} + ${std_ded:,.0f}).
   - Target Horizon Age: Age 95 (Zero-Legacy Mandate).
   - Primary Strategy: Zero-legacy drawdown. Maximize lifestyle capital usage
     while staying within the 0% LTCG bracket headroom.

--------------------------------------------------------------------------------

2. FIXED INCOME, CASH FLOW & MACRO TREND ACCUMULATORS
   - VA Disability Benefit : $180.42 / month ($2,165.04 / year)
     * Tax Status          : 100% TAX-EXEMPT (Excluded from Tax Ledger)
   - Social Security       : $978.00 / month ($11,736.00 / year)
     * Tax Status          : TAXABLE ORDINARY INCOME
   - U.S. Navy Pension     : $404.58 / month ($4,854.96 / year)
     * Tax Status          : TAXABLE ORDINARY INCOME

   - CONST_GUARANTEED_ANNUAL_FLOOR: $18,756.00/year ($1,563.00/month).
   - CONST_TAXABLE_FIXED_BASELINE : $16,590.96/year ($1,382.58/month).
   - CONST_TARGET_LIFESTYLE_SPEND : $93,996.66/year ($7,833.06/month).
   - CONST_TARGET_NET_DRAWDOWN_GAP: $77,405.70/year ($6,450.48/month).
   - CONST_CRASH_FIXED_FLOOR      : $50,000.00/year (bare-bones baseline).
   - CONST_CRASH_DRAWDOWN_GAP     : $31,244.00/year ($50k floor - $18,756 floor).
   - CONST_OPERATIONAL_CASH_BUFFER: $85,000.00 (E*TRADE Savings ...1600).
   - CONST_SAVINGS_TARGET         : $85,000.00 (Premium Savings ...1600 Target).
   - CONST_SAVINGS_FLOOR          : $20,000.00 (Minimum Cash Tank Floor).
   - Dynamic CPI Factor           : {cpi}% (Retrieved U.S. CPI Baseline)
     
   - CONST_PEAK_PORTFOLIO_NAV     : $1,733,426.88 (High-water mark tracker)
   - CONST_BASELINE_DEPLETION_AGE : Age 95 (Baseline horizon anchor)
   - CONST_3YR_CUMULATIVE_DRAWDOWN: $0.00 (Multi-year cumulative burn tracker)
   - CONST_MIN_STATISTICAL_DAYS   : 90 (Cold-Start Proxy Threshold)

--------------------------------------------------------------------------------

3. BUCKET 1 CASH & CD STRUCTURE (EXPLICIT LOCATION MAP)
   - Operational Cash Buffer: $85,000.00 (Held in E*TRADE Savings ...1600)
   - CD Bucket #1: $100,000.00 (Matures 10/17/2026) [EXTERNAL BANK - NOT IN CSV]
   - CD Bucket #2: $100,000.00 (Matures 04/14/2027) [HELD IN E*TRADE - IN CSV]
   - CD Bucket #3: $100,000.00 (Matures 05/05/2027) [HELD IN E*TRADE - IN CSV]
   - CD Bucket #4: $100,000.00 (Matures 05/05/2027) [HELD IN E*TRADE - IN CSV]
   - CD Bucket #5: $100,000.00 (Matures 05/05/2027) [HELD IN E*TRADE - IN CSV]

--------------------------------------------------------------------------------

4. INGESTED EXPENSE PAYLOAD
# [START COPY HERE]
- CONST_STATIC_MONTHLY_BILLS:
  * Pool_Service: [Amount: $150.00]
  * Lawn_Service: [Amount: $230.00]
  * Internet_Service: [Amount: $85.00]
  * T-Mobile_Cellular: [Amount: $85.00]
  * Spotify: [Amount: $15.00]
  * OUC_Water: [Amount: $40.00]

- CONST_VARIABLE_SPEND:
  * Food: [Historical_Monthly_Average: $500.00]
  * Garden_Purchases: [Historical_Monthly_Average: $120.50]
  * Electronic_Equipment: [Historical_Monthly_Average: $850.00]
  * Tolls: [Historical_Monthly_Average: $55.00]

- CONST_NON_LINEAR_EXPENSES:
  * Massey_Lawn_Two_Months: [Due_Month: 1] [Last_Paid_Amount: $85.00]

- CONST_SEASONAL_MONTHLY_BILLS:
  * Electric_Bill: [Jan: $338.41]
# [END COPY HERE]
================================================================================"""
    filename = os.path.join(DIR_CORE_ACTIVE, f"GEM_Retirement_Master_Profile_Constants_{today}_v{new_version}.txt")
    with open(filename, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"System: Saved {filename}")

def generate_portfolio_ledger(taxable, ira, routing_data, prev_state, current_version=38):
    print("System: Generating Core File 2 (Portfolio Ledger)...")
    new_version = current_version + 1
    today = datetime.now().strftime("%Y-%m-%d")
    market_status = routing_data.get('market_state', 'NORMAL')
    
    # Initialize Buckets
    buckets = {
        2: {'name': 'U.S. LARGE-CAP CORE & GROWTH', 'account': '...0331', 'holdings': [], 'total': 0.0},
        3: {'name': 'HIGH-YIELD INCOME', 'account': '...2008', 'holdings': [], 'total': 0.0},
        4: {'name': 'U.S. MID / SMALL-CAP EQUITY', 'account': '...7851', 'holdings': [], 'total': 0.0},
        5: {'name': 'INTERNATIONAL EQUITIES', 'account': '...2641', 'holdings': [], 'total': 0.0},
        6: {'name': 'TRADITIONAL IRA (TAX-SHELTERED CORE)', 'account': '...5669', 'holdings': [], 'total': 0.0},
        7: {'name': 'U.S. DIVIDEND GROWTH & APPRECIATION', 'account': '...2654', 'holdings': [], 'total': 0.0},
        8: {'name': 'TAX-FREE / ULTRA-SHORT TREASURY STABILIZER', 'account': '...2670', 'holdings': [], 'total': 0.0}
    }

    # Process IRA (Always Bucket 6)
    for sym, data in sorted(ira.items()):
        if sym.lower() in ['cash', 'total', 'nan', ''] or 'generated' in sym.lower() or len(sym) > 10: continue
        gain_str = f"+${data['Total Gain $']:,.2f}" if data['Total Gain $'] >= 0 else f"-${abs(data['Total Gain $']):,.2f}"
        line = f"      * {sym:<4} : {data['Quantity']:.4f} shares\n        [Price: ${data['Last Price $']:.3f} | Basis: ${data['Basis $']:,.2f} | Value: ${data['Value $']:,.2f} | {gain_str}]"
        buckets[6]['holdings'].append(line)
        buckets[6]['total'] += data['Value $']

    dynamic_ticker_map = prev_state.get('ticker_map', {})

    # Process Taxable (Routed via Dynamic Map)
    for sym, data in sorted(taxable.items()):
        if sym.lower() in ['cash', 'total', 'nan', ''] or 'generated' in sym.lower() or len(sym) > 10: continue
        b_idx = dynamic_ticker_map.get(sym, 2) # Default to 2 if unknown (New Ticker)
        gain_str = f"+${data['Total Gain $']:,.2f}" if data['Total Gain $'] >= 0 else f"-${abs(data['Total Gain $']):,.2f}"
        line = f"      * {sym:<4} : {data['Quantity']:.4f} shares\n        [Price: ${data['Last Price $']:.3f} | Basis: ${data['Basis $']:,.2f} | Value: ${data['Value $']:,.2f} | {gain_str}]"
        buckets[b_idx]['holdings'].append(line)
        buckets[b_idx]['total'] += data['Value $']

    total_executed_equities = sum(b['total'] for b in buckets.values())
    
    # Dynamic Cash from 3-CSV Architecture
    etrade_cds = prev_state['etrade_cds']
    ext_cds = prev_state['ext_cds']
    
    uninvested_cash = prev_state.get('brokerage_cash', prev_state['uninvested_cash'])
    total_platform_cash = prev_state.get('total_platform_cash', 0.0)
    
    if total_platform_cash > 0:
        op_cash = total_platform_cash - uninvested_cash - etrade_cds
    else:
        op_cash = prev_state['op_cash']
        
    etrade_platform_assets = total_executed_equities + uninvested_cash + op_cash + etrade_cds
    combined_capital = etrade_platform_assets + ext_cds

    # Update Bucket 1 text dynamically
    b1_text = prev_state['bucket_1']
    b1_text = re.sub(r'(Operational Cash Buffer.*?)\$[\d,]+\.\d{2}', r'\g<1>' + f"${op_cash:,.2f}", b1_text)
    b1_text = re.sub(r'(Subtotal E\*TRADE Bucket 1 Capital.*?)\$[\d,]+\.\d{2}', r'\g<1>' + f"${(op_cash + etrade_cds):,.2f}", b1_text)
    b1_text = re.sub(r'(Total Bucket 1 Liquidity.*?)\$[\d,]+\.\d{2}', r'\g<1>' + f"${(op_cash + etrade_cds + ext_cds):,.2f}", b1_text)

    today_dt = datetime.strptime(today, "%Y-%m-%d")
    active_milestones = []
    for m in prev_state.get('milestones', []):
        date_match = re.search(r'\[(\d{4}-\d{2}-\d{2})', m)
        if date_match:
            m_date = datetime.strptime(date_match.group(1), "%Y-%m-%d")
            if (today_dt - m_date).days <= 730:
                active_milestones.append(m)

    new_milestone = f"[{today} | ${combined_capital:,.2f} | ${total_executed_equities:,.2f} | ${(uninvested_cash + op_cash + etrade_cds + ext_cds):,.2f} | $0.00 | {market_status}]"
    active_milestones.append(new_milestone)
    milestone_block = "\n".join(active_milestones)

    content = f"""================================================================================
PORTFOLIO ALLOCATION LEDGER & BUCKET STRUCTURE
Date: {today} (Version {new_version})
Framework Structure: 8 Macro Asset Buckets (Single Account Architecture)
Active Market Status Designation: [{market_status}]
Reconciliation Source: Dual-CSV Ingestion (All Accounts + Account ...5669)
================================================================================

{prev_state['tax_ledger']}

--------------------------------------------------------------------------------

DATE-AWARE SPENDING PACING ENGINE & LIABILITY FORECAST
--------------------------------------------------------------------------------
Current Date: {today}
Annual Target Net Drawdown Gap: $53,249.01

  - Total A (Paced YTD Target):                   $35,596.60
  - Total B (Actual YTD Drawdown):                     $0.00
  - Pacing Variance (Gross):                     -$35,596.60 (Under paced target)
  
  - Pending Fixed Liabilities (YTD Remaining):    $8,522.00
  - Net Adjusted Pacing Variance:                +$27,074.60

--------------------------------------------------------------------------------

{b1_text}

--------------------------------------------------------------------------------
"""
    for b_idx in range(2, 9):
        b = buckets[b_idx]
        content += f"\n[BUCKET {b_idx}] {b['name']}\n"
        content += f"  - Account: {b['account']}\n"
        content += f"  - Holdings (CSV Reconciled):\n"
        if b['holdings']:
            content += "\n".join(b['holdings']) + "\n"
        else:
            content += "      * [NO ACTIVE HOLDINGS]\n"
        content += f"  - Account Value (Executed Equities): ${b['total']:,.2f}\n"
        content += f"  - Status: ACTIVE / RECONCILED\n"
        content += "\n--------------------------------------------------------------------------------\n"

    content += f"""
================================================================================
RECONCILED TOTAL SYSTEM CAPITAL (ZERO DOUBLE-COUNTING AUDIT)
================================================================================
  - Total Executed Holdings Market Value (Buckets 2–8):         ${total_executed_equities:,.2f}
  - E*TRADE Reported Total Platform Cash Line:                    ${(uninvested_cash + op_cash + etrade_cds):,.2f}
      * Consisting of:
        - Uninvested Brokerage Cash (Buckets 2–8):      ${uninvested_cash:,.2f}
        - Operational Cash Buffer (Savings ...1600): ${op_cash:,.2f}
        - E*TRADE CD Ladder (4 x $100k Tranches):   ${etrade_cds:,.2f}
  - Subtotal E*TRADE Platform Assets:                           ${etrade_platform_assets:,.2f}
  - External Bank Capital (CD Bucket #1):                         ${ext_cds:,.2f}
--------------------------------------------------------------------------------
  - COMBINED TOTAL SYSTEM CAPITAL:                              ${combined_capital:,.2f}
================================================================================

ROLLING HISTORICAL MILESTONE LEDGER (TRAILING 8 QUARTERS)
--------------------------------------------------------------------------------
[Date | Total Capital | Executed Equities | Cash/CD Bridge | YTD Drawdown | Market Status]
{milestone_block}
================================================================================
"""
    filename = os.path.join(DIR_CORE_ACTIVE, f"GEM_Retirement_Portfolio_Ledger_{today}_v{new_version}.txt")
    with open(filename, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"System: Saved {filename}")

def main():
    print("System: Initializing Avenue C Ingestion Engine...")
    try:
        print("\n" + "=" * 80)
        print("STEP 1: DATA INGESTION")
        print("=" * 80)
        while True:
            print("Please download fresh CSV files for:")
            print("1. 'All brokerage and bank accounts' CSV")
            print("2. 'All brokerage accounts' CSV (Name it: PortfolioDownload_2-8_*.csv)")
            print("3. 'Traditional IRA -5669' CSV")
            input(f"Place them in the '{DIR_CSV_ACTIVE}' folder and press ENTER to continue...")
            try:
                all_accounts_csv = get_latest_file(DIR_CSV_ACTIVE, "PortfolioDownload_AllAccounts*.csv")
                brokerage_csv = get_latest_file(DIR_CSV_ACTIVE, "PortfolioDownload_2-8*.csv")
                ira_csv = get_latest_file(DIR_CSV_ACTIVE, "PortfolioDownload_5669*.csv")
                print(f"\n✅ Detected: {os.path.basename(all_accounts_csv)}")
                print(f"✅ Detected: {os.path.basename(brokerage_csv)}")
                print(f"✅ Detected: {os.path.basename(ira_csv)}")
                break
            except FileNotFoundError:
                print(f"\n❌ ERROR: I did not detect the required CSV files in the '{DIR_CSV_ACTIVE}' folder.")
                print("Please make sure the files are in the folder and try again.\n")
                
        print("\n" + "-" * 80)
        print("STEP 2: METADATA OVERRIDES")
        print("-" * 80)
        print("If you need to reassign a ticker to a new bucket, please type:")
        print("Move TICKER to Bucket X")
        user_input = input("Otherwise, just press ENTER to continue: ").strip()
        
        metadata_overrides = {}
        if user_input:
            matches = re.findall(r'Move\s+([A-Z]+)\s+to\s+Bucket\s+(\d)', user_input, re.IGNORECASE)
            for ticker, bucket in matches:
                metadata_overrides[ticker.upper()] = int(bucket)
                print(f"Queued override: {ticker.upper()} -> Bucket {bucket}")
                
        print("\n" + "-" * 80)
        print("STEP 3: DELTA CHECK (SOLD / BOUGHT TICKERS)")
        print("-" * 80)
        
        # Extract previous state FIRST to get old tickers
        prev_state = parse_previous_ledger(DIR_CORE_ACTIVE)
        old_ledger_path = prev_state['file_path']
        prev_state['ticker_map'].update(metadata_overrides)
        
        df_brokerage = load_and_clean_csv(brokerage_csv)
        df_ira = load_and_clean_csv(ira_csv)
        
        # Extract live CASH rows via regex to bypass pandas trailing comma drops
        with open(all_accounts_csv, 'r', encoding='utf-8') as f:
            all_cash_match = re.search(r'\nCASH,.*?,([\d\.]+),*\n', f.read())
        prev_state['total_platform_cash'] = float(all_cash_match.group(1)) if all_cash_match else 0.0
        
        with open(brokerage_csv, 'r', encoding='utf-8') as f:
            brok_cash_match = re.search(r'\nCASH,.*?,([\d\.]+),*\n', f.read())
        prev_state['brokerage_cash'] = float(brok_cash_match.group(1)) if brok_cash_match else 0.0
        
        taxable, ira = disaggregate_holdings(df_brokerage, df_ira)
        
        old_tickers = set(prev_state['ticker_map'].keys())
        new_tickers = set(taxable.keys()).union(set(ira.keys()))
        
        sold_tickers = old_tickers - new_tickers
        bought_tickers = new_tickers - old_tickers
        
        for bt in bought_tickers:
            if bt not in prev_state['ticker_map']:
                bucket_input = input(f"\nNew ticker [{bt}] detected. Please reply with its target Bucket (1-8): ").strip()
                try:
                    prev_state['ticker_map'][bt] = int(re.search(r'\d', bucket_input).group())
                except:
                    print(f"Invalid input. Defaulting {bt} to Bucket 2.")
                    prev_state['ticker_map'][bt] = 2
                    
        gains_files = []
        if sold_tickers:
            print(f"\nSale of [{', '.join(sold_tickers)}] detected.")
            while True:
                gains_files = glob.glob(os.path.join(DIR_CSV_ACTIVE, "RealizedGains*.csv"))
                if gains_files:
                    print("\n✅ Realized Gains CSV(s) detected:")
                    for gf in gains_files:
                        print(f"  - {os.path.basename(gf)}")
                    break
                else:
                    print("\n❌ WARNING: Realized Gains CSV(s) NOT FOUND.")
                    print("Please download your Realized Gains & Losses CSV(s).")
                    print("Naming convention: Must start with 'RealizedGains' (e.g., RealizedGains_XXXX.csv).")
                    input(f"Place them in the '{DIR_CSV_ACTIVE}' folder and press ENTER to continue...")
                    
        print("\n[DELTA CHECK COMPLETE: No Missing Info.] Proceeding to Data Processing...\n")
        
        # Execute Tax Engine
        prev_state['tax_ledger'] = process_tax_and_wash_sales(prev_state['tax_ledger'], gains_files, sold_tickers)
        
        total_taxable_value = sum(data['Value $'] for data in taxable.values())
        total_ira_value = sum(data['Value $'] for data in ira.values())
        total_executed_equities = total_taxable_value + total_ira_value
        
        telemetry_payload = {
            "total_executed_equities": round(total_executed_equities, 2),
            "current_savings_balance": prev_state.get('total_platform_cash', 0.0) - prev_state.get('brokerage_cash', 0.0) - prev_state['etrade_cds'],
            "target_savings_balance": 85000.00,
            "tank_capacity_ratio": (prev_state.get('total_platform_cash', 0.0) - prev_state.get('brokerage_cash', 0.0) - prev_state['etrade_cds']) / 85000.00
        }
        
        routing_data = query_strategic_routing(telemetry_payload)
        
        # Dynamically find latest Constants version
        old_const_path = None
        const_files = glob.glob(os.path.join(DIR_CORE_ACTIVE, "GEM_Retirement_Master_Profile_Constants_*.txt"))
        if const_files:
            latest_const = sorted(const_files)[-1]
            old_const_path = latest_const
            const_match = re.search(r'_v(\d+)\.txt', latest_const)
            const_version = int(const_match.group(1)) if const_match else 0
        else:
            const_version = 0
        
        # Execute Phase 4: File Generation
        generate_master_constants(routing_data, current_version=const_version)
        generate_portfolio_ledger(taxable, ira, routing_data, prev_state, current_version=prev_state['ledger_version'])
        
        print("\n=== PHASE 4 COMPLETE ===")
        print(f"Core Files generated successfully in {DIR_CORE_ACTIVE}.")
        
        print("\n=== PHASE 5: CLEAN ROOM ARCHIVING ===")
        if os.path.exists(old_ledger_path):
            shutil.move(old_ledger_path, os.path.join(DIR_CORE_ARCHIVE, os.path.basename(old_ledger_path)))
        if old_const_path and os.path.exists(old_const_path):
            shutil.move(old_const_path, os.path.join(DIR_CORE_ARCHIVE, os.path.basename(old_const_path)))
            
        shutil.move(all_accounts_csv, os.path.join(DIR_CSV_ARCHIVE, os.path.basename(all_accounts_csv)))
        shutil.move(brokerage_csv, os.path.join(DIR_CSV_ARCHIVE, os.path.basename(brokerage_csv)))
        shutil.move(ira_csv, os.path.join(DIR_CSV_ARCHIVE, os.path.basename(ira_csv)))
        for gf in gains_files:
            shutil.move(gf, os.path.join(DIR_CSV_ARCHIVE, os.path.basename(gf)))
            
        print("System: Old Core Files and processed CSVs successfully archived.")
            
    except Exception as e:
        print(f"\n[FATAL EXECUTION HALT] {e}")

if __name__ == "__main__":
    main()