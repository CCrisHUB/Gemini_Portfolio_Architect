#01_ingestion_engine.py
#"""
#Avenue C Ingestion Engine
#Date: 2026-09-12
#Version: 2.2.6 (Hardened Regex & Centralized NAV Math)
#Role: Ingests E*TRADE CSVs, parses Core Files, queries Gemini API, and archives state.
#"""
__version__ = "2.2.6"
__date__ = "2026-09-12"

import os
import json
import re
import glob
import shutil
from datetime import datetime, timedelta
from google import genai
from google.genai import types
from dotenv import load_dotenv
import alu_utils

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

def extract_currency(pattern, text):
    """Robustly extracts currency, handling both -$500 and $-500 formatting anomalies."""
    match = re.search(pattern + r'.*?([+-]?\$[+-]?[\d,]+\.\d{2})', text)
    return float(match.group(1).replace('$', '').replace(',', '')) if match else 0.0

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
    
    pacing_match = re.search(r'(DATE-AWARE SPENDING PACING ENGINE.*?)(?=\n-{50,}\n+\[BUCKET 1\])', content, re.DOTALL)
    pacing_text = pacing_match.group(1).strip() if pacing_match else "DATE-AWARE SPENDING PACING ENGINE\n[DATA NOT FOUND]"
    
    b1_match = re.search(r'(\[BUCKET 1\] LIQUIDITY & PRESERVATION.*?)(?=\n-{50,}\n+\[BUCKET 2\])', content, re.DOTALL)
    b1_text = b1_match.group(1).strip() if b1_match else "[BUCKET 1] LIQUIDITY & PRESERVATION\n[DATA NOT FOUND]"
    
    uninvested = extract_currency(r'Uninvested Brokerage Cash', content)
    op_cash = extract_currency(r'Operational Cash Buffer', content)
    etrade_cds = extract_currency(r'E\*TRADE CD Ladder', content)
    ext_cds = extract_currency(r'External Bank Capital', content)
    
    dynamic_ticker_map = {}
    bucket_blocks = re.findall(r'\[BUCKET (\d)\](.*?)(?=\n\[BUCKET|\n={80})', content, re.DOTALL)
    for b_num, b_content in bucket_blocks:
        b_idx = int(b_num)
        # ANTI-CONTAMINATION: Quarantine Bucket 6 (IRA)
        if b_idx >= 2 and b_idx != 6:
            tickers = re.findall(r'\*\s+([A-Z]+)\s+:', b_content)
            for t in tickers:
                dynamic_ticker_map[t] = b_idx
                
    milestone_match = re.search(r'ROLLING HISTORICAL MILESTONE LEDGER.*?\n\[Date.*?\]\n(.*?)(?=\n={80})', content, re.DOTALL)
    milestones = milestone_match.group(1).strip().split('\n') if milestone_match and milestone_match.group(1).strip() else []
                
    return {
        'tax_ledger': tax_text, 
        'pacing_engine': pacing_text,
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

def process_tax_and_wash_sales(tax_ledger_text, gains_files, sold_tickers, routing_data):
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

    # --- 2. EXTRACT CURRENT STATE ---
    stcg_match = re.search(r'Realized Short-Term Capital Gains YTD:\s+([+-]?)\$?([\d,]+\.\d{2})', tax_ledger_text)
    ltcg_match = re.search(r'Realized Long-Term Capital Gains \(LTCG\) YTD:\s+([+-]?)\$?([\d,]+\.\d{2})', tax_ledger_text)
    
    current_stcg = float(stcg_match.group(1) + stcg_match.group(2).replace(',', '')) if stcg_match else 0.0
    current_ltcg = float(ltcg_match.group(1) + ltcg_match.group(2).replace(',', '')) if ltcg_match else 0.0
    
    # --- 3. PROCESS NEW GAINS ---
    new_stcg, new_ltcg = 0.0, 0.0
    event_logs = []
    
    if gains_files:
        for gf in gains_files:
            try:
                with open(gf, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                    
                summary_idx = next((i for i, line in enumerate(lines) if 'TAXABLE G&L SUMMARY' in line), -1)
                if summary_idx == -1:
                    print(f"Warning: Could not find TAXABLE G&L SUMMARY in {gf}")
                    continue
                    
                # ANTI-GIGO: Strip trailing commas to prevent pandas ParserError
                clean_lines = [line.strip().rstrip(',') for line in lines[summary_idx+1:summary_idx+3]]
                summary_csv = "\n".join(clean_lines)
                import pandas as pd
                import io
                df = pd.read_csv(io.StringIO(summary_csv), on_bad_lines='skip')
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
            
    updated_stcg = current_stcg + new_stcg
    updated_ltcg = current_ltcg + new_ltcg
    
    # --- 4. DYNAMIC API MATH ---
    std_ded = routing_data.get('std_deduction', 16100.0)
    ltcg_limit = routing_data.get('ltcg_limit', 49200.0)
    max_gross = std_ded + ltcg_limit
    remaining_headroom = ltcg_limit - updated_ltcg
    
    if event_logs:
        log_insertion = "\n".join(event_logs) + "\n\nYTD Cumulative Tax Summary:"
        tax_ledger_text = tax_ledger_text.replace("YTD Cumulative Tax Summary:", log_insertion)
        
    def format_currency(val):
        return f"-${abs(val):,.2f}" if val < 0 else f"+${val:,.2f}" if val > 0 else f"${val:,.2f}"
        
    # Update Headers
    tax_ledger_text = re.sub(r'(0% LTCG Tax Headroom Baseline.*?)\$[\d,]+\.\d{2}', r'\g<1>' + f"${ltcg_limit:,.2f}", tax_ledger_text)
    tax_ledger_text = re.sub(r'(Federal Standard Deduction.*?)\$[\d,]+\.\d{2}', r'\g<1>' + f"${std_ded:,.2f}", tax_ledger_text)
    tax_ledger_text = re.sub(r'(Maximum Gross Taxable Income.*?)\$[\d,]+\.\d{2}', r'\g<1>' + f"${max_gross:,.2f}", tax_ledger_text)

    # Update Summary
    tax_ledger_text = re.sub(r'(Realized Short-Term Capital Gains YTD:\s+)[+-]?\$[\d,]+\.\d{2}', r'\g<1>' + format_currency(updated_stcg).replace('\\', '\\\\'), tax_ledger_text)
    tax_ledger_text = re.sub(r'(Realized Long-Term Capital Gains \(LTCG\) YTD:\s+)[+-]?\$[\d,]+\.\d{2}', r'\g<1>' + format_currency(updated_ltcg).replace('\\', '\\\\'), tax_ledger_text)
    tax_ledger_text = re.sub(r'(Starting 0% LTCG Headroom:\s+)\$[\d,]+\.\d{2}', r'\g<1>' + f"${ltcg_limit:,.2f}", tax_ledger_text)
    tax_ledger_text = re.sub(r'(Remaining 0% LTCG Headroom:\s+)[+-]?\$[\d,]+\.\d{2}', r'\g<1>' + f"${remaining_headroom:,.2f}".replace('\\', '\\\\'), tax_ledger_text)
    
    return tax_ledger_text

def calculate_pending_liabilities(const_text):
    today = datetime.now()
    current_month = today.month
    months_remaining = 12 - current_month + 1
    liabilities = 0.0
    payload_match = re.search(r'4\. INGESTED EXPENSE PAYLOAD\n# \[START COPY HERE\](.*?)# \[END COPY HERE\]', const_text, re.DOTALL)
    if not payload_match: return 0.0
    payload = payload_match.group(1)
    monthly_items = re.findall(r'\[(?:Amount|Historical_Monthly_Average):\s*\$([\d,]+\.\d{2})\]', payload)
    for val in monthly_items:
        liabilities += float(val.replace(',', '')) * months_remaining
    non_linear_items = re.findall(r'\[Due_Month:\s*(\d+)\]\s*\[Last_Paid_Amount:\s*\$([\d,]+\.\d{2})\]', payload)
    for month_str, val_str in non_linear_items:
        if int(month_str) >= current_month:
            liabilities += float(val_str.replace(',', ''))
    month_map = {'Jan':1, 'Feb':2, 'Mar':3, 'Apr':4, 'May':5, 'Jun':6, 'Jul':7, 'Aug':8, 'Sep':9, 'Oct':10, 'Nov':11, 'Dec':12}
    seasonal_items = re.findall(r'\[([A-Z][a-z]{2}):\s*\$([\d,]+\.\d{2})\]', payload)
    for m_str, val_str in seasonal_items:
        if month_map.get(m_str, 0) >= current_month:
            liabilities += float(val_str.replace(',', ''))
    return liabilities

def update_pacing_engine(pacing_text, const_text, new_target_gap=None):
    today = datetime.now()
    today_str = today.strftime("%Y-%m-%d")
    pacing_text = re.sub(r'Current Date:\s+\d{4}-\d{2}-\d{2}', f'Current Date: {today_str}', pacing_text)
    
    if new_target_gap:
        annual_gap = new_target_gap
        pacing_text = re.sub(r'(Annual Target Net Drawdown Gap:\s+)[+-]?\$[+-]?[\d,]+\.\d{2}', r'\g<1>' + f"${annual_gap:,.2f}", pacing_text)
    else:
        gap_match = re.search(r'Annual Target Net Drawdown Gap:\s+\$?([\d,]+\.\d{2})', pacing_text)
        annual_gap = float(gap_match.group(1).replace(',', '')) if gap_match else 0.0
        
    day_of_year = today.timetuple().tm_yday
    days_in_year = 366 if today.year % 4 == 0 and (today.year % 100 != 0 or today.year % 400 == 0) else 365
    paced_target = annual_gap * (day_of_year / days_in_year)
    actual_match = re.search(r'Total B \(Actual YTD Drawdown\):\s+\$?([\d,]+\.\d{2})', pacing_text)
    actual_drawdown = float(actual_match.group(1).replace(',', '')) if actual_match else 0.0
    gross_variance = actual_drawdown - paced_target
    variance_str = f"-${abs(gross_variance):,.2f} (Under paced target)" if gross_variance < 0 else f"+${gross_variance:,.2f} (Over paced target)"
    pending_liabilities = calculate_pending_liabilities(const_text)
    net_variance = gross_variance + pending_liabilities
    net_var_str = f"-${abs(net_variance):,.2f}" if net_variance < 0 else f"+${net_variance:,.2f}"
    pacing_text = re.sub(r'(Total A \(Paced YTD Target\):\s+)\$[\d,]+\.\d{2}', r'\g<1>' + f"${paced_target:,.2f}", pacing_text)
    pacing_text = re.sub(r'(Pacing Variance \(Gross\):\s+)[+-]?\$[\d,]+\.\d{2}.*?(?=\n)', r'\g<1>' + variance_str, pacing_text)
    if re.search(r'Pending Fixed Liabilities', pacing_text):
        pacing_text = re.sub(r'(Pending Fixed Liabilities \(YTD Remaining\):\s+)\$[\d,]+\.\d{2}', r'\g<1>' + f"${pending_liabilities:,.2f}", pacing_text)
        pacing_text = re.sub(r'(Net Adjusted Pacing Variance:\s+)[+-]?\$[\d,]+\.\d{2}', r'\g<1>' + net_var_str, pacing_text)
    return pacing_text

def calculate_zero_legacy_drawdown(combined_capital, const_text):
    today = datetime.now()
    dob_match = re.search(r'Date of Birth:\s+[A-Za-z]+\s+\d{1,2},\s+(\d{4})', const_text)
    horizon_match = re.search(r'Target Horizon Age:\s+Age\s+(\d+)', const_text)
    fixed_floor_match = re.search(r'CONST_GUARANTEED_ANNUAL_FLOOR:\s+\$?([\d,]+\.\d{2})', const_text)
    if not (dob_match and horizon_match and fixed_floor_match): return None, None
    birth_year = int(dob_match.group(1))
    horizon_age = int(horizon_match.group(1))
    fixed_floor = float(fixed_floor_match.group(1).replace(',', ''))
    current_age = today.year - birth_year
    years_remaining = horizon_age - current_age
    if years_remaining <= 0: years_remaining = 1
    target_net_drawdown = combined_capital / years_remaining
    target_lifestyle_spend = target_net_drawdown + fixed_floor
    return target_lifestyle_spend, target_net_drawdown

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

def generate_master_constants(old_const_text, routing_data, current_version, new_ledger_version, combined_capital):
    print("System: Generating Core File 1 (Master Constants)...")
    new_version = current_version + 1
    today = datetime.now().strftime("%Y-%m-%d")
    
    cpi = routing_data.get('cpi_rate', 3.36)
    std_ded = routing_data.get('std_deduction', 16100.0)
    ltcg = routing_data.get('ltcg_limit', 49200.0)
    max_gross = std_ded + ltcg
    
    content = old_const_text
    
    # Update Header Date and Version
    content = re.sub(r'Date: \d{4}-\d{2}-\d{2} \(Version \d+\)', f'Date: {today} (Version {new_version})', content)
    content = re.sub(r'File Name: GEM_Retirement_Master_Profile_Constants_\d{4}-\d{2}-\d{2}_v\d+\.txt', f'File Name: GEM_Retirement_Master_Profile_Constants_{today}_v{new_version}.txt', content)
    
    # Update Manifest
    content = re.sub(r'GEM_Retirement_Master_Profile_Constants_\d{4}-\d{2}-\d{2}_v\d+\.txt', f'GEM_Retirement_Master_Profile_Constants_{today}_v{new_version}.txt', content)
    content = re.sub(r'GEM_Retirement_Portfolio_Ledger_\d{4}-\d{2}-\d{2}_v\d+\.txt', f'GEM_Retirement_Portfolio_Ledger_{today}_v{new_ledger_version}.txt', content)
    
    # Update Tax Parameters
    content = re.sub(r'(CONST_ACTIVE_STD_DEDUCTION:\s+)\$[\d,]+\.\d{2}', r'\g<1>' + f"${std_ded:,.2f}", content)
    content = re.sub(r'(CONST_ACTIVE_0PCT_LTCG_LIMIT:\s+)\$[\d,]+\.\d{2}', r'\g<1>' + f"${ltcg:,.2f}", content)
    content = re.sub(r'(CONST_ACTIVE_MAX_GROSS_0PCT_LTCG:\s+)\$[\d,]+\.\d{2}', r'\g<1>' + f"${max_gross:,.2f}", content)
    
    # Update CPI
    content = re.sub(r'(Dynamic CPI Factor\s+:\s+)[\d\.]+%', r'\g<1>' + f"{cpi}%", content)
    
    # Update Zero-Legacy Drawdown
    target_spend, target_drawdown = calculate_zero_legacy_drawdown(combined_capital, content)
    if target_spend and target_drawdown:
        content = re.sub(r'(CONST_TARGET_LIFESTYLE_SPEND\s+:\s+)\$[\d,]+\.\d{2}/year \(\$[\d,]+\.\d{2}/month\)', r'\g<1>' + f"${target_spend:,.2f}/year (${(target_spend/12):,.2f}/month)", content)
        content = re.sub(r'(CONST_TARGET_NET_DRAWDOWN_GAP:\s+)\$[\d,]+\.\d{2}/year \(\$[\d,]+\.\d{2}/month\)', r'\g<1>' + f"${target_drawdown:,.2f}/year (${(target_drawdown/12):,.2f}/month)", content)
    
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
        op_cash = total_platform_cash - uninvested_cash
    else:
        op_cash = prev_state['op_cash']
        
    etrade_platform_assets = total_executed_equities + uninvested_cash + op_cash + etrade_cds
    combined_capital = etrade_platform_assets + ext_cds

    # Update Bucket 1 text dynamically (Hardened Regex)
    b1_text = prev_state['bucket_1']
    b1_text = re.sub(r'(Operational Cash \(E\*TRADE Savings \.\.\.1600\):.*?)[+-]?\$[+-]?[\d,]+\.\d{2}', r'\g<1>' + f"${op_cash:,.2f}", b1_text)
    b1_text = re.sub(r'(Subtotal E\*TRADE Bucket 1 Capital.*?)[+-]?\$[+-]?[\d,]+\.\d{2}', r'\g<1>' + f"${(op_cash + etrade_cds):,.2f}", b1_text)
    b1_text = re.sub(r'(Total Bucket 1 Liquidity.*?)[+-]?\$[+-]?[\d,]+\.\d{2}', r'\g<1>' + f"${(op_cash + etrade_cds + ext_cds):,.2f}", b1_text)

    today_dt = datetime.strptime(today, "%Y-%m-%d")
    active_milestones = []
    for m in prev_state.get('milestones', []):
        date_match = re.search(r'\[(\d{4}-\d{2}-\d{2})', m)
        if date_match:
            m_date = datetime.strptime(date_match.group(1), "%Y-%m-%d")
            if (today_dt - m_date).days <= 730:
                active_milestones.append(m)

    # Extract live YTD Drawdown from Pacing Engine
    ytd_match = re.search(r'Total B \(Actual YTD Drawdown\):\s+\$?([\d,]+\.\d{2})', prev_state.get('pacing_engine', ''))
    ytd_drawdown = float(ytd_match.group(1).replace(',', '')) if ytd_match else 0.0

    new_milestone = f"[{today} | ${combined_capital:,.2f} | ${total_executed_equities:,.2f} | ${(uninvested_cash + op_cash + etrade_cds + ext_cds):,.2f} | ${ytd_drawdown:,.2f} | {market_status}]"
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

{prev_state.get('pacing_engine', 'DATE-AWARE SPENDING PACING ENGINE\\n[DATA NOT FOUND]')}

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

def extract_all_cash(filepath):
    """Robustly extracts and sums all CASH rows, bypassing pandas trailing comma drops."""
    total = 0.0
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        matches = re.findall(r'\nCASH,.*?,([-\d\.,]+)', content)
        for m in matches:
            try:
                total += float(m.replace(',', ''))
            except ValueError:
                pass
    except Exception as e:
        print(f"Warning: Could not extract cash from {filepath}: {e}")
    return total

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
        
        df_brokerage = alu_utils.load_and_clean_csv(brokerage_csv)
        df_ira = alu_utils.load_and_clean_csv(ira_csv)
        
        # Extract live CASH rows via robust regex aggregation
        prev_state['total_platform_cash'] = extract_all_cash(all_accounts_csv)
        prev_state['brokerage_cash'] = extract_all_cash(brokerage_csv) + extract_all_cash(ira_csv)
        
        taxable, ira = alu_utils.disaggregate_holdings(df_brokerage, df_ira)
        
        old_tickers = set(prev_state['ticker_map'].keys())
        # ANTI-LOOP: Only track delta for taxable assets to prevent IRA false-positives
        new_tickers = set(taxable.keys())
        
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
        
        total_taxable_value = sum(data['Value $'] for data in taxable.values())
        total_ira_value = sum(data['Value $'] for data in ira.values())
        total_executed_equities = total_taxable_value + total_ira_value
        
        current_savings = prev_state.get('total_platform_cash', 0.0) - prev_state.get('brokerage_cash', 0.0)
        telemetry_payload = {
            "total_executed_equities": round(total_executed_equities, 2),
            "current_savings_balance": current_savings,
            "target_savings_balance": 85000.00,
            "tank_capacity_ratio": current_savings / 85000.00
        }
        
        routing_data = query_strategic_routing(telemetry_payload)
        
        # Execute Tax Engine (Now with API Truth)
        prev_state['tax_ledger'] = process_tax_and_wash_sales(prev_state['tax_ledger'], gains_files, sold_tickers, routing_data)
        
        # Dynamically find latest Constants version
        old_const_path = None
        old_const_text = ""
        const_files = glob.glob(os.path.join(DIR_CORE_ACTIVE, "GEM_Retirement_Master_Profile_Constants_*.txt"))
        if const_files:
            latest_const = sorted(const_files)[-1]
            old_const_path = latest_const
            const_match = re.search(r'_v(\d+)\.txt', latest_const)
            const_version = int(const_match.group(1)) if const_match else 0
            with open(latest_const, 'r', encoding='utf-8') as f:
                old_const_text = f.read()
        else:
            raise FileNotFoundError("FATAL: Core File 1 not found. Cannot perform state-preserving mutation.")
        
        # Execute Phase 4: File Generation
        new_ledger_version = prev_state['ledger_version'] + 1
        
        # Centralized combined_capital math (FIXED: added etrade_cds)
        combined_capital = total_executed_equities + prev_state.get('total_platform_cash', 0.0) + prev_state['etrade_cds'] + prev_state['ext_cds']
        
        # Calculate new drawdown gap BEFORE updating pacing engine
        target_spend, target_drawdown = calculate_zero_legacy_drawdown(combined_capital, old_const_text)
        
        # Pass the new gap to the pacing engine
        prev_state['pacing_engine'] = update_pacing_engine(prev_state['pacing_engine'], old_const_text, new_target_gap=target_drawdown)
        
        generate_master_constants(old_const_text, routing_data, const_version, new_ledger_version, combined_capital)
        generate_portfolio_ledger(taxable, ira, routing_data, prev_state, current_version=prev_state['ledger_version'])
        
        print("\n=== PHASE 4 COMPLETE ===")
        print(f"Core Files generated successfully in {DIR_CORE_ACTIVE}.")
        
        print("\n=== PHASE 5: CLEAN ROOM ARCHIVING ===")
        os.makedirs(DIR_CORE_ARCHIVE, exist_ok=True)
        os.makedirs(DIR_CSV_ARCHIVE, exist_ok=True)
        
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