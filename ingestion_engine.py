import pandas as pd
import os
import io
import json
from datetime import datetime
from google import genai
from google.genai import types
from dotenv import load_dotenv

# Define file paths
DATA_DIR = "data"
ALL_ACCOUNTS_CSV = os.path.join(DATA_DIR, "PortfolioDownload_AllAccounts.csv")
IRA_CSV = os.path.join(DATA_DIR, "PortfolioDownload_5669.csv")

# Avenue C Semantic Memory: Ticker to Bucket Routing Map
TICKER_BUCKET_MAP = {
    'GSLC': 2, 'QUAL': 2, 'SCHG': 2, 'SCHX': 2,
    'MAIN': 3, 'O': 3, 'SCHD': 3, 
    'AVUV': 4, 'SCHA': 4, 'SCHM': 4,
    'AVDV': 5, 'EMXC': 5, 'VIGI': 5, 'VXUS': 5,
    'VIG': 7, 
    'USFR': 8
}

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
            
    for sym, data in ira_holdings.items():
        if sym.lower() not in ['cash', 'total', 'nan', ''] and 'generated' not in sym.lower() and len(sym) <= 10:
            ira_holdings[sym]['Basis $'] = round(data['Value $'] - data['Total Gain $'], 2)

    return taxable_holdings, ira_holdings

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
    filename = os.path.join(DATA_DIR, f"GEM_Retirement_Master_Profile_Constants_{today}_v{new_version}.txt")
    with open(filename, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"System: Saved {filename}")

def generate_portfolio_ledger(taxable, ira, routing_data, current_version=38):
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

    # Process Taxable (Routed via TICKER_BUCKET_MAP)
    for sym, data in sorted(taxable.items()):
        if sym.lower() in ['cash', 'total', 'nan', ''] or 'generated' in sym.lower() or len(sym) > 10: continue
        b_idx = TICKER_BUCKET_MAP.get(sym, 2) # Default to 2 if unknown
        gain_str = f"+${data['Total Gain $']:,.2f}" if data['Total Gain $'] >= 0 else f"-${abs(data['Total Gain $']):,.2f}"
        line = f"      * {sym:<4} : {data['Quantity']:.4f} shares\n        [Price: ${data['Last Price $']:.3f} | Basis: ${data['Basis $']:,.2f} | Value: ${data['Value $']:,.2f} | {gain_str}]"
        buckets[b_idx]['holdings'].append(line)
        buckets[b_idx]['total'] += data['Value $']

    total_executed_equities = sum(b['total'] for b in buckets.values())
    
    # Hardcoded Cash for this iteration (will be dynamic in future phases)
    uninvested_cash = 13123.68
    op_cash = 85000.00
    etrade_cds = 400000.00
    ext_cds = 100000.00
    etrade_platform_assets = total_executed_equities + uninvested_cash + op_cash + etrade_cds
    combined_capital = etrade_platform_assets + ext_cds

    content = f"""================================================================================
PORTFOLIO ALLOCATION LEDGER & BUCKET STRUCTURE
Date: {today} (Version {new_version})
Framework Structure: 8 Macro Asset Buckets (Single Account Architecture)
Active Market Status Designation: [{market_status}]
Reconciliation Source: Dual-CSV Ingestion (All Accounts + Account ...5669)
================================================================================

PERSISTENT YTD TAX LEDGER (TAX YEAR 2026)
--------------------------------------------------------------------------------
0% LTCG Tax Headroom Baseline (Single Filer):         $49,200.00
Federal Standard Deduction (2026):                     $16,100.00
Maximum Gross Taxable Income for 0% LTCG Bracket:     $65,300.00

Realized Tax Event Log:
  - 2026-08-14 | Legacy Brokerage (...9739) Liquidation
    * Gross Realized Capital Gains:                    +$17,317.41
    * Harvested Capital Losses:                         -$2,585.01
    * Net Realized LTCG:                               +$14,732.40
  - 2026-08-28 | Individual Brokerage (...2008) Liquidation
    * Net Realized STCG (JEPQ):                           +$273.19
  - 2026-08-31 | Individual Brokerage (...0331 & ...7851) Liquidation
    * Net Realized STCG (VOO, VB, VO):                 -$4,055.66

YTD Cumulative Tax Summary:
  - Ordinary Income YTD (Pension / Social Security):       $0.00
  - Realized Short-Term Capital Gains YTD:              -$3,782.47
  - Realized Long-Term Capital Gains (LTCG) YTD:      $14,732.40
  - Starting 0% LTCG Headroom:                        $49,200.00
  - Remaining 0% LTCG Headroom:                       $34,467.60

30-DAY WASH-SALE LOCKOUT TRACKER:
  - VB | Date Sold: 2026-09-01 | Lockout Expiry: 2026-10-01
  - VO | Date Sold: 2026-09-01 | Lockout Expiry: 2026-10-01
  - VOO | Date Sold: 2026-09-01 | Lockout Expiry: 2026-10-01

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

[BUCKET 1] LIQUIDITY & PRESERVATION
  - Identity: Short-Term Liquidity, Safety, & Risk Insulation Buffer
  - Holdings Breakdown:
      * Operational Cash (E*TRADE Savings ...1600):    $85,000.00 [In E*TRADE]
      * CD Bucket #1 (Matures 10/17/2026):            $100,000.00 [External]
      * CD Bucket #2 (Matures 04/14/2027):            $100,000.00 [In E*TRADE]
      * CD Bucket #3 (Matures 05/05/2027):            $100,000.00 [In E*TRADE]
      * CD Bucket #4 (Matures 05/05/2027):            $100,000.00 [In E*TRADE]
      * CD Bucket #5 (Matures 05/05/2027):            $100,000.00 [In E*TRADE]
  - Subtotal E*TRADE Bucket 1 Capital:               $485,000.00
  - Subtotal External Bucket 1 Capital:              $100,000.00
  - Total Bucket 1 Liquidity:                        $585,000.00
  - Status: ACTIVE / RECONCILED

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
[2026-08-29 | $1,721,814.88 | $1,136,814.88 | $585,000.00 | $0.00 | NORMAL]
[2026-08-30 | $1,733,426.88 | $1,136,814.88 | $585,000.00 | $0.00 | NORMAL]
[2026-09-01 | $1,731,829.88 | $1,133,706.20 | $598,123.68 | $0.00 | NORMAL]
[{today} | ${combined_capital:,.2f} | ${total_executed_equities:,.2f} | $598,123.68 | $0.00 | {market_status}]
================================================================================
"""
    filename = os.path.join(DATA_DIR, f"GEM_Retirement_Portfolio_Ledger_{today}_v{new_version}.txt")
    with open(filename, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"System: Saved {filename}")

def main():
    print("System: Initializing Avenue C Ingestion Engine...")
    try:
        df_all = load_and_clean_csv(ALL_ACCOUNTS_CSV)
        df_ira = load_and_clean_csv(IRA_CSV)
        
        taxable, ira = disaggregate_holdings(df_all, df_ira)
        
        total_taxable_value = sum(data['Value $'] for data in taxable.values())
        total_ira_value = sum(data['Value $'] for data in ira.values())
        total_executed_equities = total_taxable_value + total_ira_value
        
        telemetry_payload = {
            "total_executed_equities": round(total_executed_equities, 2),
            "current_savings_balance": 85000.00,
            "target_savings_balance": 85000.00,
            "tank_capacity_ratio": 1.0
        }
        
        routing_data = query_strategic_routing(telemetry_payload)
        
        # Execute Phase 4: File Generation
        generate_master_constants(routing_data, current_version=87)
        generate_portfolio_ledger(taxable, ira, routing_data, current_version=38)
        
        print("\n=== PHASE 4 COMPLETE ===")
        print("Core Files generated successfully in /data/ folder.")
            
    except Exception as e:
        print(f"\n[FATAL EXECUTION HALT] {e}")

if __name__ == "__main__":
    main()