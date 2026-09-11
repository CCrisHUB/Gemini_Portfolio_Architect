#02_performance_audit.py
#"""
#Fund Performance & Structural Audit Engine
#Date: 2026-09-11
#Version: 1.0.3 (Modern SDK & Dotenv Patch)
#Role: Ingests CSVs, evaluates tax-loss targets, and interfaces with Gemini API.
#"""
__version__ = "1.0.3"
__date__ = "2026-09-11"

import os
import sys
import glob
import re
import shutil
import io
import pandas as pd
from datetime import datetime
from google import genai
from google.genai import types
from dotenv import load_dotenv

# ==============================================================================
# ANSI UX FORMATTING CONSTANTS
# ==============================================================================
ANSI_RED = "\033[91m"
ANSI_GREEN = "\033[92m"
ANSI_YELLOW = "\033[93m"
ANSI_CYAN = "\033[96m"
ANSI_RESET = "\033[0m"

# ==============================================================================
# MASTER CONFIGURATION & DIRECTORY STRUCTURE
# ==============================================================================
LLM_MODEL_NAME = 'gemini-3.1-pro-preview'
YIELD_TRAPS = ['JEPI', 'JEPQ', 'QYLD', 'RYLD', 'XYLD']

# Hardcoded Paths based on user environment
BASE_DIR = r"C:\10_Projects\Gemini_Portfolio_Architect"
CORE_DIR = os.path.join(BASE_DIR, "00_CORE_Files")
OLD_CORE_DIR = os.path.join(BASE_DIR, "05_OLD_Core_Files")
CSV_CURRENT_DIR = os.path.join(BASE_DIR, "20_CSV_Downloads_Current")
CSV_OLD_DIR = os.path.join(BASE_DIR, "50_OLD_CSV_Files")
REPORTS_DIR = os.path.join(BASE_DIR, "70 REPORTS")

# Ensure all required directories exist
for directory in [CORE_DIR, OLD_CORE_DIR, CSV_CURRENT_DIR, CSV_OLD_DIR, REPORTS_DIR]:
    os.makedirs(directory, exist_ok=True)

# ==============================================================================
# HELPER FUNCTIONS (FILE I/O)
# ==============================================================================
def get_latest_file(directory: str, pattern: str) -> str:
    """Finds the latest file in a specific directory matching a glob pattern."""
    search_path = os.path.join(directory, pattern)
    files = glob.glob(search_path)
    if not files:
        raise FileNotFoundError(f"No files found matching pattern: {pattern} in {directory}")
    files.sort(key=os.path.getmtime, reverse=True)
    return files[0]

def load_file_content(filepath: str) -> str:
    if not filepath or not os.path.exists(filepath):
        return ""
    with open(filepath, 'r', encoding='utf-8') as f:
        return f.read()

def cleanup_csv_files():
    """Moves all CSV files from the current staging folder to the old folder."""
    print(f"\n{ANSI_CYAN}[System] Moving processed CSV files to OLD directory...{ANSI_RESET}")
    csv_files = glob.glob(os.path.join(CSV_CURRENT_DIR, "*.csv"))
    
    for file_path in csv_files:
        filename = os.path.basename(file_path)
        dest_path = os.path.join(CSV_OLD_DIR, filename)
        
        if os.path.exists(dest_path):
            os.remove(dest_path)
            
        shutil.move(file_path, dest_path)
    print(f"{ANSI_GREEN}[System] Successfully moved {len(csv_files)} CSV file(s) to {CSV_OLD_DIR}.{ANSI_RESET}")

# ==============================================================================
# PHASE 1: DATA INGESTION & RECONCILIATION ENGINE
# ==============================================================================
def extract_wash_sale_lockouts(ledger_text: str) -> dict:
    lockouts = {}
    if "30-DAY WASH-SALE LOCKOUT TRACKER:" in ledger_text:
        try:
            section = ledger_text.split("30-DAY WASH-SALE LOCKOUT TRACKER:")[1].split("---")[0]
            pattern = r"-\s+([A-Z]+)\s+\|\s+Date Sold:\s+[\d-]+\s+\|\s+Lockout Expiry:\s+([\d-]+)"
            matches = re.findall(pattern, section)
            current_date = datetime.now().date()
            
            for ticker, expiry_str in matches:
                expiry_date = datetime.strptime(expiry_str, "%Y-%m-%d").date()
                if expiry_date >= current_date:
                    lockouts[ticker] = expiry_date
        except Exception as e:
            print(f"{ANSI_YELLOW}[WARNING] Failed to parse wash-sale lockouts: {e}{ANSI_RESET}")
    return lockouts

def load_and_clean_csv(filepath: str) -> pd.DataFrame:
    """Robust E*TRADE CSV parser that bypasses preambles."""
    print(f"{ANSI_CYAN}[System] Parsing {os.path.basename(filepath)}...{ANSI_RESET}")
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    header_index = -1
    for i, line in enumerate(lines):
        if line.strip().startswith("Symbol"):
            header_index = i
            break
    if header_index == -1:
        raise ValueError(f"FATAL: Could not find the main data table header in {filepath}.")
    clean_csv_string = "".join(lines[header_index:])
    df = pd.read_csv(io.StringIO(clean_csv_string), on_bad_lines='skip')
    df.columns = df.columns.str.strip()
    return df

def sanitize_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Standardizes columns, strips currency strings, and removes garbage rows."""
    df.rename(columns={
        'Qty': 'Quantity', 
        'Value ($)': 'Value', 'Value $': 'Value', 
        'Price ($)': 'Price', 'Last Price $': 'Price',
        'Cost Basis ($)': 'Cost_Basis', 'Cost Basis': 'Cost_Basis'
    }, inplace=True, errors='ignore')
    
    df.dropna(subset=['Symbol'], inplace=True)
    df['Symbol'] = df['Symbol'].astype(str).str.strip()
    
    for col in ['Quantity', 'Value', 'Price', 'Cost_Basis', 'Total Gain $']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col].astype(str).str.replace(r'[$,]', '', regex=True), errors='coerce').fillna(0)
            
    # Calculate total Cost_Basis if missing but Total Gain is present
    if 'Cost_Basis' not in df.columns and 'Total Gain $' in df.columns:
        df['Cost_Basis'] = df['Value'] - df['Total Gain $']
        
    df = df[~df['Symbol'].str.lower().isin(['cash', 'total', 'nan', ''])]
    df = df[~df['Symbol'].str.lower().str.contains('generated')]
    df = df[df['Symbol'].str.len() <= 10]
    return df

def process_csvs(consolidated_path: str, ira_path: str) -> pd.DataFrame:
    df_all = sanitize_dataframe(load_and_clean_csv(consolidated_path))
    df_ira = sanitize_dataframe(load_and_clean_csv(ira_path))

    ira_grouped = df_ira.groupby('Symbol').agg({'Quantity': 'sum', 'Value': 'sum', 'Cost_Basis': 'sum'}).reset_index()
    ira_grouped['Account_Type'] = 'IRA_5669'

    all_grouped = df_all.groupby('Symbol').agg({'Quantity': 'sum', 'Value': 'sum', 'Cost_Basis': 'sum', 'Price': 'first'}).reset_index()

    merged = pd.merge(all_grouped, ira_grouped[['Symbol', 'Quantity', 'Value', 'Cost_Basis']], on='Symbol', how='left', suffixes=('_Total', '_IRA'))
    
    for col in ['Quantity_IRA', 'Value_IRA', 'Cost_Basis_IRA']:
        merged[col] = merged[col].fillna(0)

    merged['Quantity_Taxable'] = merged['Quantity_Total'] - merged['Quantity_IRA']
    merged['Value_Taxable'] = merged['Value_Total'] - merged['Value_IRA']
    merged['Cost_Basis_Taxable'] = merged['Cost_Basis_Total'] - merged['Cost_Basis_IRA']

    final_rows = []
    for _, row in merged.iterrows():
        if row['Quantity_IRA'] > 0:
            final_rows.append({
                'Symbol': row['Symbol'], 'Quantity': row['Quantity_IRA'], 'Value': row['Value_IRA'],
                'Cost_Basis': row['Cost_Basis_IRA'], 'Price': row['Price'],
                'Account_Type': 'IRA_5669', 'Tax_Status': 'EXEMPT'
            })
        if row['Quantity_Taxable'] > 0:
            final_rows.append({
                'Symbol': row['Symbol'], 'Quantity': row['Quantity_Taxable'], 'Value': row['Value_Taxable'],
                'Cost_Basis': row['Cost_Basis_Taxable'], 'Price': row['Price'],
                'Account_Type': 'TAXABLE', 'Tax_Status': 'HARVESTABLE'
            })

    return pd.DataFrame(final_rows)

# ==============================================================================
# PHASE 2: TRIAGE & MATERIALITY LOGIC
# ==============================================================================
def identify_audit_targets(df_portfolio: pd.DataFrame) -> list:
    targets = []
    taxable_df = df_portfolio[df_portfolio['Tax_Status'] == 'HARVESTABLE'].copy()
    
    taxable_df['Unrealized_GL_Value'] = taxable_df['Value'] - taxable_df['Cost_Basis']
    taxable_df['Unrealized_GL_Pct'] = taxable_df['Unrealized_GL_Value'] / taxable_df['Cost_Basis']
    
    for _, row in taxable_df.iterrows():
        ticker = row['Symbol']
        gl_value = row['Unrealized_GL_Value']
        gl_pct = row['Unrealized_GL_Pct']
        
        is_target, reason = False, ""
        
        if ticker in YIELD_TRAPS:
            is_target, reason = True, "STRUCTURAL YIELD TRAP"
        elif gl_value < 0:
            abs_loss, abs_loss_pct = abs(gl_value), abs(gl_pct)
            if abs_loss > 1000.00:
                is_target, reason = True, f"MATERIAL LOSS (>${abs_loss:,.2f})"
            elif abs_loss_pct > 0.05:
                is_target, reason = True, f"MATERIAL LOSS PCT (>{abs_loss_pct*100:.2f}%)"
                
        if is_target:
            targets.append({
                'Symbol': ticker, 'Account_Type': row['Account_Type'], 'Cost_Basis': row['Cost_Basis'],
                'Value': row['Value'], 'Unrealized_GL': gl_value, 'Unrealized_GL_Pct': gl_pct, 'Reason': reason
            })

    targets_sorted = sorted(targets, key=lambda x: x['Unrealized_GL'])
    return targets_sorted[:5]

def print_triage_summary(targets: list):
    print(f"\n{ANSI_CYAN}" + "="*60)
    print(" PHASE 2: TRIAGE COMPLETE - TARGETS IDENTIFIED")
    print("="*60 + f"{ANSI_RESET}")
    if not targets:
        print(f"{ANSI_YELLOW}[System] No positions meet the materiality threshold for harvesting.{ANSI_RESET}")
    for t in targets:
        print(f"-> {t['Symbol']} | {t['Reason']}")
        print(f"   Value: ${t['Value']:,.2f} | Basis: ${t['Cost_Basis']:,.2f} | G/L: ${t['Unrealized_GL']:,.2f} ({t['Unrealized_GL_Pct']*100:.2f}%)")
    print(f"{ANSI_CYAN}" + "="*60 + f"{ANSI_RESET}\n")

# ==============================================================================
# PHASE 3: PRE-FLIGHT PROMPT & LIVE MACRO DATA RETRIEVAL
# ==============================================================================
def get_ad_hoc_inquiry() -> str:
    print(f"{ANSI_CYAN} PRE-FLIGHT CHECK: AD-HOC INQUIRIES & CAPITAL DEPLOYMENT")
    print("="*60 + f"{ANSI_RESET}")
    print("Do you have any specific capital deployment requests or ad-hoc questions?")
    print("(e.g., 'I cashed a $100k CD, where should I deploy it?' or 'Should I buy XYZ?')")
    print("Press ENTER to skip and run the standard audit.")
    
    user_input = input(f"\n{ANSI_CYAN}Your Inquiry: {ANSI_RESET}").strip()
    if user_input:
        print(f"\n{ANSI_CYAN}[System] Ad-hoc inquiry registered. Integrating into search parameters...{ANSI_RESET}")
    else:
        print(f"\n{ANSI_CYAN}[System] No ad-hoc inquiry. Proceeding with standard audit...{ANSI_RESET}")
    return user_input

def gather_live_macro_data(targets: list, ad_hoc_query: str) -> str:
    print(f"{ANSI_CYAN}[System] Initiating Live Web Search via Gemini API...{ANSI_RESET}")
    
    client = genai.Client()
    target_tickers = [t['Symbol'] for t in targets]
    
    search_prompt = f"""
    You are a financial data retrieval engine. You have access to Google Search.
    Search for and return the LIVE current data for the following:
    
    1. Target Tickers for Tax-Loss Harvesting: {target_tickers}
       - Find their current Expense Ratio, 1-year, and 3-year trailing returns.
       - Identify 1 or 2 highly correlated proxy ETFs tracking a DIFFERENT index.
       
    2. User Ad-Hoc Inquiry: "{ad_hoc_query}"
       - If specific tickers are mentioned, search for their Expense Ratio, Yield, and 1-year return.
       - If deploying cash is mentioned, search for current macro conditions (e.g., S&P 500 30-day trend).
       
    Output this data as a clean, structured text summary. DO NOT provide advice yet.
    """
    try:
        response = client.models.generate_content(
            model=LLM_MODEL_NAME,
            contents=search_prompt,
            config=types.GenerateContentConfig(
                tools=[{"google_search": {}}]
            )
        )
        print(f"{ANSI_GREEN}[System] Live Macro Data successfully retrieved.{ANSI_RESET}")
        return response.text
    except Exception as e:
        print(f"{ANSI_RED}[FATAL ERROR] Failed to retrieve live data: {e}{ANSI_RESET}")
        sys.exit(1)

# ==============================================================================
# PHASE 4: LLM INTEGRATION & INTERACTIVE CHAT LOOP
# ==============================================================================
def generate_and_review_proposal(portfolio_data: str, search_data: str, ad_hoc_query: str, lockouts: dict, custom_instructions: str):
    print(f"\n{ANSI_CYAN}[System] Initializing {LLM_MODEL_NAME} (Thinking Level: High)...{ANSI_RESET}")
    
    client = genai.Client()
    
    chat_session = client.chats.create(
        model=LLM_MODEL_NAME,
        config=types.GenerateContentConfig(
            temperature=0.1,
            system_instruction=custom_instructions
        )
    )
    
    initial_prompt = f"""
    You are the Retirement and Portfolio Architect. Execute a Fund Performance & Structural Audit.
    
    [DATA PAYLOAD]
    1. Portfolio Math & Targets (Calculated via Python):
    {portfolio_data}
    
    2. Active Wash-Sale Lockouts (DO NOT RECOMMEND THESE AS PROXIES):
    {lockouts}
    
    3. Live Macro & Search Data (Retrieved via Web Search):
    {search_data}
    
    4. User Ad-Hoc Inquiry:
    "{ad_hoc_query}"
    
    [MANDATE]
    Analyze the targets. Recommend Tax-Loss Harvesting proxies based strictly on the live search data. 
    Ensure no wash-sale overlap. Answer the user's ad-hoc inquiry with mathematical justification.
    
    Output the entire response strictly formatted as an 80-character line-wrapped Markdown text block.
    Do not include conversational filler outside the markdown block.
    """
    
    print(f"{ANSI_CYAN}[System] AI is analyzing data and writing the initial proposal. Please wait...{ANSI_RESET}")
    try:
        response = chat_session.send_message(initial_prompt)
        proposal_text = response.text
    except Exception as e:
        print(f"{ANSI_RED}[FATAL ERROR] AI generation failed: {e}{ANSI_RESET}")
        sys.exit(1)
        
    date_str = datetime.now().strftime("%Y-%m-%d")
    proposal_filename = f"Fund_Performance_and_Structural_Audit_{date_str}_PROPOSAL.txt"
    proposal_filepath = os.path.join(REPORTS_DIR, proposal_filename)
    
    with open(proposal_filepath, "w", encoding="utf-8") as f:
        f.write(proposal_text)
        
    print(f"\n{ANSI_GREEN}" + "="*60)
    print(f" [SUCCESS] Initial Proposal saved to: {proposal_filepath}")
    print("="*60 + f"{ANSI_RESET}")
    print("Please open the file in VS Code to review the AI's recommendations.")
    print("You can now ask follow-up questions, challenge the proxies, or ask for clarification.")
    print("Type 'accept' when you are satisfied to generate the final official file.")
    
    while True:
        user_input = input(f"\n{ANSI_CYAN}[You]: {ANSI_RESET}").strip()
        if user_input.lower() == 'accept':
            print(f"\n{ANSI_CYAN}[System] Proposal accepted. Finalizing audit...{ANSI_RESET}")
            break
        if not user_input:
            continue
            
        print(f"{ANSI_CYAN}[System] Sending to {LLM_MODEL_NAME}...{ANSI_RESET}")
        try:
            reply = chat_session.send_message(user_input)
            print(f"\n{ANSI_GREEN}[AI]:\n{reply.text}{ANSI_RESET}")
        except Exception as e:
            print(f"{ANSI_RED}[ERROR] Communication failed: {e}{ANSI_RESET}")

    return chat_session

# ==============================================================================
# PHASE 5: FINAL MARKDOWN RENDERING & FILE GENERATION
# ==============================================================================
def get_next_version_number(directory: str, base_filename: str) -> int:
    """Scans the REPORTS directory to find the next version number."""
    files = os.listdir(directory)
    max_version = 0
    pattern = re.compile(rf"{base_filename}_v(\d+)\.txt")
    for file in files:
        match = pattern.match(file)
        if match:
            version = int(match.group(1))
            if version > max_version:
                max_version = version
    return max_version + 1

def finalize_audit(chat_session):
    print(f"\n{ANSI_CYAN}[System] Compiling final agreed-upon state...{ANSI_RESET}")
    date_str = datetime.now().strftime("%Y-%m-%d")
    base_name = f"Fund_Performance_and_Structural_Audit_{date_str}"
    
    next_version = get_next_version_number(REPORTS_DIR, base_name)
    final_filename = f"{base_name}_v{next_version}.txt"
    final_filepath = os.path.join(REPORTS_DIR, final_filename)
    
    final_prompt = f"""
    The user has accepted the audit. 
    Generate the FINAL, official report incorporating all agreed-upon changes.
    
    MANDATORY FORMATTING RULES:
    1. Output strictly formatted with soft word-boundary wrapping (max 80 columns).
    2. Do NOT wrap the output in ```markdown or ```text code blocks.
    3. Include this exact standardized metadata block header at the very top:

    File Name: {final_filename}
    ================================================================================
    FUND PERFORMANCE & STRUCTURAL AUDIT
    Date: {date_str} (Version {next_version})
    Role: Macro Asset & Tax Lot Performance Audit
    File Name: {final_filename}
    ================================================================================
    """
    
    print(f"{ANSI_CYAN}[System] Generating final official file: {final_filepath}...{ANSI_RESET}")
    try:
        response = chat_session.send_message(final_prompt)
        final_text = response.text
        if final_text.startswith("```"):
            final_text = "\n".join(final_text.split("\n")[1:-1])
    except Exception as e:
        print(f"{ANSI_RED}[FATAL ERROR] Failed to generate final report: {e}{ANSI_RESET}")
        sys.exit(1)
        
    with open(final_filepath, "w", encoding="utf-8") as f:
        f.write(final_text.strip())
        
    print(f"\n{ANSI_GREEN}" + "="*60)
    print(f" [SUCCESS] Final Audit saved to: {final_filepath}")
    print(" [SYSTEM] Execution Complete. Terminating.")
    print("="*60 + f"{ANSI_RESET}\n")

# ==============================================================================
# MAIN EXECUTION ORCHESTRATOR
# ==============================================================================
def main():
    print(f"{ANSI_CYAN}" + "="*60)
    print(" AVENUE C: FUND PERFORMANCE & STRUCTURAL AUDIT ENGINE")
    print("="*60 + f"{ANSI_RESET}")
    
    # 0. API Key Check & Dotenv Load
    load_dotenv()
    if not os.environ.get("GEMINI_API_KEY"):
        print(f"{ANSI_RED}[FATAL ERROR] GEMINI_API_KEY environment variable not found.{ANSI_RESET}")
        print(f"{ANSI_YELLOW}Please ensure your .env file is present and contains GEMINI_API_KEY=your_key{ANSI_RESET}")
        sys.exit(1)

    # 1. Locate Core Files
    while True:
        try:
            ledger_file = get_latest_file(CORE_DIR, "GEM_Retirement_Portfolio_Ledger_*.txt")
            instructions_file = get_latest_file(CORE_DIR, "GEM_Retirement_and_Portfolio_Architect_Custom_Instructions_*.txt")
            print(f"{ANSI_GREEN}✅ Detected: {os.path.basename(ledger_file)}{ANSI_RESET}")
            print(f"{ANSI_GREEN}✅ Detected: {os.path.basename(instructions_file)}{ANSI_RESET}")
            break
        except FileNotFoundError:
            print(f"\n{ANSI_RED}❌ ERROR: Missing Core Files in '{CORE_DIR}'.{ANSI_RESET}")
            print(f"{ANSI_YELLOW}Please ensure both the Portfolio Ledger and Custom Instructions are present.{ANSI_RESET}")
            user_input = input(f"{ANSI_CYAN}Press ENTER to retry, or type 'exit' to quit: {ANSI_RESET}").strip()
            if user_input.lower() == 'exit': sys.exit(0)

    # 2. Locate CSV Files
    while True:
        try:
            consolidated_csv = get_latest_file(CSV_CURRENT_DIR, "PortfolioDownload_AllAccounts*.csv")
            ira_csv = get_latest_file(CSV_CURRENT_DIR, "PortfolioDownload_5669*.csv")
            print(f"{ANSI_GREEN}✅ Detected: {os.path.basename(consolidated_csv)}{ANSI_RESET}")
            print(f"{ANSI_GREEN}✅ Detected: {os.path.basename(ira_csv)}{ANSI_RESET}")
            break
        except FileNotFoundError:
            print(f"\n{ANSI_RED}❌ ERROR: I did not detect the required CSV files in the '{CSV_CURRENT_DIR}' folder.{ANSI_RESET}")
            print(f"{ANSI_YELLOW}Please ensure both 'AllAccounts' and '5669' CSVs are present.{ANSI_RESET}")
            user_input = input(f"{ANSI_CYAN}Place them in the folder and press ENTER to retry (or type 'exit'): {ANSI_RESET}").strip()
            if user_input.lower() == 'exit': sys.exit(0)

    # 3. Extract Lockouts
    ledger_text = load_file_content(ledger_file)
    lockouts = extract_wash_sale_lockouts(ledger_text)
    
    # 4. Process CSVs & Triage
    df_portfolio = process_csvs(consolidated_csv, ira_csv)
    targets = identify_audit_targets(df_portfolio)
    print_triage_summary(targets)
    
    # 5. Pre-Flight & Search
    ad_hoc_query = get_ad_hoc_inquiry()
    search_data = gather_live_macro_data(targets, ad_hoc_query) if (targets or ad_hoc_query) else "No search required."
    
    # 6. LLM Integration
    custom_instructions = load_file_content(instructions_file)
    portfolio_data_str = "\n".join([str(t) for t in targets]) if targets else "No harvestable targets identified."
    
    chat_session = generate_and_review_proposal(
        portfolio_data=portfolio_data_str,
        search_data=search_data,
        ad_hoc_query=ad_hoc_query,
        lockouts=lockouts,
        custom_instructions=custom_instructions
    )
    
    # 7. Finalize & Cleanup
    finalize_audit(chat_session)
    cleanup_csv_files()

if __name__ == "__main__":
    main()