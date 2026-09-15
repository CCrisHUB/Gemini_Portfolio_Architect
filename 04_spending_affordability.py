#04_spending_affordability.py
#"""
#Spending Request & Affordability Evaluation Engine
#Date: 2026-09-16
#Version: 1.2.0 (Centralized .env Pathing & Deep Freeze Sweep)
#Role: Evaluates discretionary spending requests against liquidity and market telemetry.
#"""
__version__ = "1.2.0"
__date__ = "2026-09-16"

import os
import sys
import glob
import re
from datetime import datetime
from google import genai
from google.genai import types
from dotenv import load_dotenv
import alu_utils

# ==============================================================================
# ANSI UX FORMATTING CONSTANTS
# ==============================================================================
ANSI_RED = "\033[91m"
ANSI_GREEN = "\033[92m"
ANSI_YELLOW = "\033[93m"
ANSI_CYAN = "\033[96m"
ANSI_RESET = "\033[0m"

# ==============================================================================
# MASTER CONFIGURATION & DIRECTORY STRUCTURE (GEMINI PORTFOLIO ARCHITECT)
# ==============================================================================
LLM_MODEL_NAME = 'gemini-3.1-pro-preview'

load_dotenv()  # Load environment variables globally

GEMINI_ROOT = os.environ.get("GEMINI_ROOT", r"C:\OneDrive\10_Projects\Gemini_Portfolio_Architect")
GEMINI_DEEP_ARCHIVE_ROOT = os.environ.get("GEMINI_DEEP_ARCHIVE_ROOT", r"C:\Archive\Gemini_Portfolio_Architect")

# Active Directories
DIR_CORE_ACTIVE = os.path.join(GEMINI_ROOT, "00_CORE_Files")
DIR_CSV_ACTIVE = os.path.join(GEMINI_ROOT, "20_CSV_Downloads_Current")
DIR_REPORTS_ACTIVE = os.path.join(GEMINI_ROOT, "70_REPORTS")
DIR_STATEMENTS_ACTIVE = os.path.join(GEMINI_ROOT, "80_STATEMENTS")

# Archive Directories
DIR_CORE_ARCHIVE = os.path.join(GEMINI_ROOT, "05_OLD_Core_Files")
DIR_CSV_ARCHIVE = os.path.join(GEMINI_ROOT, "50_OLD_CSV_Files")
DIR_REPORTS_ARCHIVE = os.path.join(GEMINI_ROOT, "75_OLD_REPORTS")
DIR_STATEMENTS_ARCHIVE = os.path.join(GEMINI_ROOT, "85_OLD_STATEMENTS")

# Deep Archive Directories
DEEP_ARCHIVE_CORE = os.path.join(GEMINI_DEEP_ARCHIVE_ROOT, "05_OLD_Core_Files")
DEEP_ARCHIVE_CSV = os.path.join(GEMINI_DEEP_ARCHIVE_ROOT, "50_OLD_CSV_Files")
DEEP_ARCHIVE_REPORTS = os.path.join(GEMINI_DEEP_ARCHIVE_ROOT, "75_OLD_REPORTS")
DEEP_ARCHIVE_STATEMENTS = os.path.join(GEMINI_DEEP_ARCHIVE_ROOT, "85_OLD_STATEMENTS")

for directory in [DIR_CORE_ACTIVE, DIR_REPORTS_ACTIVE]:
    os.makedirs(directory, exist_ok=True)

# ==============================================================================
# HELPER FUNCTIONS
# ==============================================================================
def get_latest_file(directory: str, pattern: str) -> str:
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

def extract_currency(text_input: str) -> float:
    match = re.search(r'([+-]?\$?[\d,]+\.?\d*)', text_input)
    if match:
        clean_str = match.group(1).replace('$', '').replace(',', '')
        try:
            return float(clean_str)
        except ValueError:
            return 0.0
    return 0.0

def get_next_version_number(directory: str, base_filename: str) -> int:
    if not os.path.exists(directory):
        return 1
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

# ==============================================================================
# PHASE 3: MARKET TELEMETRY
# ==============================================================================
def retrieve_macro_benchmark(client, yield_data: dict) -> str:
    print(f"\n{ANSI_CYAN}[System] Initiating Live Web Search via Gemini API. Please wait...{ANSI_RESET}")
    print(f"{ANSI_YELLOW}[API DISCLOSURE] Model: {LLM_MODEL_NAME} | Tool: Google Search | Thinking: High{ANSI_RESET}")
    
    if yield_data['is_cold_start']:
        search_prompt = """
        You are a financial data retrieval engine. You have access to Google Search.
        Search for and return the LIVE trailing 3-month return (percentage) of the S&P 500 (ticker: VOO).
        Output this data as a clean, structured text summary. Ensure the exact percentage is clearly stated (e.g., '+5.16%').
        """
    else:
        search_prompt = f"""
        You are a financial data retrieval engine. You have access to Google Search.
        Search for and return the LIVE exact percentage return of the S&P 500 (ticker: VOO) 
        specifically for the timeframe starting on {yield_data['oldest_date_str']} and ending on {yield_data['current_date_str']}.
        Output this data as a clean, structured text summary. Ensure the exact percentage is clearly stated.
        """
        
    try:
        search_chat = client.chats.create(
            model=LLM_MODEL_NAME,
            config=types.GenerateContentConfig(tools=[{"google_search": {}}], temperature=0.1)
        )
        response = search_chat.send_message(search_prompt)
        print(f"{ANSI_GREEN}[System] Live Macro Data successfully retrieved.{ANSI_RESET}")
        return response.text
    except Exception as e:
        print(f"{ANSI_RED}[FATAL ERROR] Failed to retrieve live data: {e}{ANSI_RESET}")
        sys.exit(1)

# ==============================================================================
# PHASE 5: OUTPUT PAYLOAD GENERATION (LLM FORMATTING)
# ==============================================================================
def generate_final_report(client, requested: float, budget: float, yield_data: dict, benchmark_text: str, directive: str, effective_yield: float) -> None:
    print(f"\n{ANSI_CYAN}[System] Generating Final Fiduciary Report...{ANSI_RESET}")
    
    date_str = datetime.now().strftime("%Y-%m-%d")
    base_name = f"Discretionary_Spending_Request_Audit_{date_str}"
    next_version = get_next_version_number(DIR_REPORTS_ACTIVE, base_name)
    final_filename = f"{base_name}_v{next_version}.txt"
    final_filepath = os.path.join(DIR_REPORTS_ACTIVE, final_filename)
    
    if yield_data['is_cold_start']:
        yield_str = f"{effective_yield:.2f}% (Cold-Start Macro Proxy Active)"
    else:
        yield_str = f"{effective_yield:.2f}%"

    system_prompt = f"""
    You are the "Retirement and Portfolio Architect," an uncompromised, analytical financial engineering AI. 
    Your mandate is to format the mathematically verified decision matrix into a final Markdown report.
    Do NOT alter the math or the Final Directive.
    
    [VERIFIED DATA PAYLOAD]
    - Requested Amount: ${requested:,.2f}
    - Available Budget: ${budget:,.2f}
    - Effective Portfolio Yield: {yield_str}
    - External Benchmark Text: {benchmark_text}
    - Final Governance Directive: {directive}
    
    [FORMATTING MANDATE]
    Generate a highly structured text block strictly containing:
    
    File Name: {final_filename}
    ================================================================================
    DISCRETIONARY SPENDING REQUEST AUDIT
    Date: {date_str} (Version {next_version})
    Role: Affordability Evaluation & Liquidity Governance
    File Name: {final_filename}
    ================================================================================
    
    ## Section 1: Liquidity Check
    - Clearly state the Requested Amount versus the Available Budget.
    
    ## Section 2: Market Telemetry
    - Summarize the Portfolio Yield against the Benchmark Status. Note if Cold-Start proxy logic was utilized.
    
    ## Section 3: Final Governance Directive
    - Output the EXACT text of the Final Governance Directive provided in the payload. 
    - If Approved or Caution, remind the user that discretionary funds should be sourced from the Bucket 1 E*TRADE Savings buffer to insulate the core portfolio.
    
    Output strictly formatted with soft word-boundary wrapping (max 80 columns).
    Do NOT wrap the output in ```markdown or ```text code blocks.
    """
    
    try:
        chat = client.chats.create(
            model=LLM_MODEL_NAME,
            config=types.GenerateContentConfig(temperature=0.1)
        )
        response = chat.send_message(system_prompt)
        report_text = response.text.strip()
        
        if report_text.startswith("```"):
            report_text = "\n".join(report_text.split("\n")[1:-1])
            
        with open(final_filepath, "w", encoding="utf-8") as f:
            f.write(report_text)
            
        print(f"\n{ANSI_GREEN}" + "="*60)
        print(f" [SUCCESS] Final Report saved to: {final_filepath}")
        print(" [SYSTEM] Execution Complete. Terminating.")
        print("="*60 + f"{ANSI_RESET}\n")
        
    except Exception as e:
        print(f"{ANSI_RED}[FATAL ERROR] Failed to generate final report: {e}{ANSI_RESET}")
        sys.exit(1)

# ==============================================================================
# MAIN ORCHESTRATOR
# ==============================================================================
def main():
    print(f"{ANSI_CYAN}" + "="*60)
    print(" AVENUE C: SPENDING REQUEST & AFFORDABILITY ENGINE")
    print("="*60 + f"{ANSI_RESET}")
    
    load_dotenv()
    if not os.environ.get("GEMINI_API_KEY"):
        print(f"{ANSI_RED}[FATAL ERROR] GEMINI_API_KEY environment variable not found.{ANSI_RESET}")
        sys.exit(1)

    client = genai.Client()
    print(f"{ANSI_GREEN}[System] Core framework and API initialized.{ANSI_RESET}")
    
    # PHASE 0
    print(f"\n{ANSI_CYAN}Please enter your requested discretionary spend amount:{ANSI_RESET}")
    print("(e.g., '$18,000 for a Europe Trip' or '1500')")
    while True:
        user_input = input(f"{ANSI_YELLOW}Request: {ANSI_RESET}").strip()
        requested_spend = extract_currency(user_input)
        if requested_spend > 0:
            print(f"{ANSI_GREEN}[System] Registered Spend Request: ${requested_spend:,.2f}{ANSI_RESET}")
            break
        else:
            print(f"{ANSI_RED}[ERROR] Could not detect a valid dollar amount. Please try again.{ANSI_RESET}")
    
    # PHASE 1
    print(f"\n{ANSI_CYAN}[System] Locating Core Files...{ANSI_RESET}")
    constants_file = None
    ledger_file = None
    while True:
        try:
            constants_file = get_latest_file(DIR_CORE_ACTIVE, "GEM_Retirement_Master_Profile_Constants_*.txt")
            ledger_file = get_latest_file(DIR_CORE_ACTIVE, "GEM_Retirement_Portfolio_Ledger_*.txt")
            print(f"{ANSI_GREEN}✅ Detected: {os.path.basename(constants_file)}{ANSI_RESET}")
            print(f"{ANSI_GREEN}✅ Detected: {os.path.basename(ledger_file)}{ANSI_RESET}")
            break
        except FileNotFoundError as e:
            print(f"\n{ANSI_RED}❌ ERROR: Missing Core Files in '{DIR_CORE_ACTIVE}'.{ANSI_RESET}")
            print(f"{ANSI_YELLOW}{e}{ANSI_RESET}")
            retry = input(f"{ANSI_CYAN}Press ENTER to retry, or type 'exit' to quit: {ANSI_RESET}").strip()
            if retry.lower() == 'exit': sys.exit(0)

    constants_text = load_file_content(constants_file)
    ledger_text = load_file_content(ledger_file)
    
    # Parse State via ALU (Reusing functions from 03)
    const_data = alu_utils.extract_constants_data(constants_text)
    ledger_data = alu_utils.extract_trend_metrics(ledger_text)
    
    # PHASE 2
    liquidity_data = alu_utils.calculate_liquidity_gate(requested_spend, ledger_data['pacing_variance_value'])
    
    # PHASE 3
    yield_data = alu_utils.calculate_temporal_yield(ledger_data, const_data['min_statistical_days'])
    macro_benchmark_text = retrieve_macro_benchmark(client, yield_data)
    
    benchmark_yield_pct = alu_utils.extract_proxy_yield_from_text(macro_benchmark_text)
    effective_portfolio_yield = benchmark_yield_pct if yield_data['is_cold_start'] else yield_data['portfolio_yield_pct']
    
    # PHASE 4
    directive = alu_utils.evaluate_decision_matrix(
        requested=requested_spend,
        budget=liquidity_data['available_budget'],
        market_status=ledger_data['market_status'],
        portfolio_yield=effective_portfolio_yield,
        benchmark=benchmark_yield_pct
    )
    
    # UX UPGRADE: Print deterministic findings to terminal before LLM generation
    print(f"\n{ANSI_CYAN}" + "-"*60)
    print(" DETERMINISTIC ALU FINDINGS")
    print("-" * 60 + f"{ANSI_RESET}")
    print(f"Requested Spend: ${requested_spend:,.2f}")
    print(f"Available Budget: ${liquidity_data['available_budget']:,.2f}")
    print(f"Effective Yield: {effective_portfolio_yield:.2f}%")
    print(f"Benchmark Yield: {benchmark_yield_pct:.2f}%")
    print(f"Directive: {directive.split('.')[0]}")
    print(f"{ANSI_CYAN}" + "-"*60 + f"{ANSI_RESET}")
    
    # PHASE 5
    generate_final_report(
        client=client,
        requested=requested_spend,
        budget=liquidity_data['available_budget'],
        yield_data=yield_data,
        benchmark_text=macro_benchmark_text,
        directive=directive,
        effective_yield=effective_portfolio_yield
    )

    print(f"\n{ANSI_CYAN}[System] Executing 30-Day Deep Freeze Sweep...{ANSI_RESET}")
    core_swept = alu_utils.execute_deep_freeze_sweep(DIR_CORE_ARCHIVE, DEEP_ARCHIVE_CORE)
    reports_swept = alu_utils.execute_deep_freeze_sweep(DIR_REPORTS_ARCHIVE, DEEP_ARCHIVE_REPORTS)
    total_swept = len(core_swept) + len(reports_swept)
    print(f"{ANSI_GREEN}[System] Deep Freeze Sweep complete. {total_swept} file(s) moved to offline archive.{ANSI_RESET}")

if __name__ == "__main__":
    main()