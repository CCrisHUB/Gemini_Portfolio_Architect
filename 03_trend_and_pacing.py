#03_trend_and_pacing.py
#"""
#Trend Tracking & Financial Pacing Engine
#Date: 2026-09-16
#Version: 1.2.0 (Centralized .env Pathing & Deep Freeze Sweep)
#Role: Evaluates temporal yield, cold-start logic, and spending pacing variance.
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
# PHASE 2: MACRO BENCHMARK RETRIEVAL
# ==============================================================================
def retrieve_macro_benchmark(client, yield_data: dict) -> str:
    print(f"\n{ANSI_CYAN}[System] Initiating Live Web Search via Gemini API. Please wait...{ANSI_RESET}")
    print(f"{ANSI_YELLOW}[API DISCLOSURE] Model: {LLM_MODEL_NAME} | Tool: Google Search | Thinking: High{ANSI_RESET}")
    
    if yield_data['is_cold_start']:
        search_prompt = """
        You are a financial data retrieval engine. You have access to Google Search.
        Search for and return the LIVE trailing 3-month return (percentage) of the S&P 500 (ticker: VOO).
        Output this data as a clean, structured text summary. You MUST append a citation: [Source: Website Name].
        """
    else:
        search_prompt = f"""
        You are a financial data retrieval engine. You have access to Google Search.
        Search for and return the LIVE exact percentage return of the S&P 500 (ticker: VOO) 
        specifically for the timeframe starting on {yield_data['oldest_date_str']} and ending on {yield_data['current_date_str']}.
        Output this data as a clean, structured text summary. You MUST append a citation: [Source: Website Name].
        """
        
    try:
        search_chat = client.chats.create(
            model=LLM_MODEL_NAME,
            config=types.GenerateContentConfig(
                tools=[{"google_search": {}}],
                temperature=0.1
            )
        )
        response = search_chat.send_message(search_prompt)
        print(f"{ANSI_GREEN}[System] Live Macro Data successfully retrieved.{ANSI_RESET}")
        return response.text
    except Exception as e:
        print(f"{ANSI_RED}[FATAL ERROR] Failed to retrieve live data: {e}{ANSI_RESET}")
        sys.exit(1)

# ==============================================================================
# PHASE 3: OUTPUT PAYLOAD GENERATION (LLM FORMATTING)
# ==============================================================================
def generate_final_report(client, yield_data: dict, benchmark_text: str, spending_directive: str, market_status: str, min_days: int) -> None:
    print(f"\n{ANSI_CYAN}[System] Generating Final Fiduciary Report...{ANSI_RESET}")
    
    date_str = datetime.now().strftime("%Y-%m-%d")
    base_name = f"Financial_Trend_and_Pacing_Report_{date_str}"
    next_version = get_next_version_number(DIR_REPORTS_ACTIVE, base_name)
    final_filename = f"{base_name}_v{next_version}.txt"
    final_filepath = os.path.join(DIR_REPORTS_ACTIVE, final_filename)
    
    if yield_data['is_cold_start']:
        days_remaining = min_days - yield_data['delta_days']
        trend_instructions = f"""
        - State clearly that the portfolio is in a 'Cold-Start' phase ({yield_data['delta_days']} days old).
        - Explicitly state: "Internal yield calculations are suspended to prevent statistical noise. Comparative performance analysis will begin in {days_remaining} days."
        - Summarize the External Benchmark (S&P 500) as the current macro market weather. 
        - DO NOT diagnose the portfolio as underperforming or outperforming.
        """
        portfolio_yield_display = "N/A (Suspended - Cold Start)"
    else:
        trend_instructions = """
        - State that this is a mature ledger based on an exact calculated timeframe.
        - Output a deterministic mathematical diagnosis based on comparing the Internal Yield against the External Benchmark: [Outperforming / Alpha Generation], [Market-Matching], or [Underperforming / Systemic Drag].
        """
        portfolio_yield_display = f"{yield_data['portfolio_yield_pct']:.2f}%"

    system_prompt = f"""
    You are the "Retirement and Portfolio Architect," an uncompromised, analytical financial engineering AI. 
    Your sole mandate is to strictly format the mathematically verified data provided below into a final Markdown report.
    Do NOT alter the mathematical conclusions or invent new data. 
    
    [VERIFIED DATA PAYLOAD]
    - Portfolio Timeframe: {yield_data['delta_days']} days (Cold-Start: {yield_data['is_cold_start']})
    - Internal Portfolio Yield: {portfolio_yield_display}
    - External Benchmark (S&P 500 via Live Search): {benchmark_text}
    - Spending Directive: {spending_directive}
    - Active Market Status: {market_status}
    
    [FORMATTING MANDATE]
    Generate a highly structured text block strictly containing:
    
    File Name: {final_filename}
    ================================================================================
    FINANCIAL TREND & PACING REPORT
    Date: {date_str} (Version {next_version})
    Role: Macro Trend Tracking & Spending Governance
    File Name: {final_filename}
    ================================================================================
    
    ## Section 1: Portfolio Performance Trend (Trend 1)
    {trend_instructions}
    
    ## Section 2: Spending & Liquidity Trend (Trend 2)
    - Output the exact math and Directive provided in the payload verbatim. 
    
    ## Section 3: Forward-Looking Governance
    - Brief summary setting the baseline for any potential upcoming ad-hoc Spending Requests.
    
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
    print(" AVENUE C: TREND TRACKING & FINANCIAL PACING ENGINE")
    print("="*60 + f"{ANSI_RESET}")
    
    load_dotenv()
    if not os.environ.get("GEMINI_API_KEY"):
        print(f"{ANSI_RED}[FATAL ERROR] GEMINI_API_KEY environment variable not found.{ANSI_RESET}")
        sys.exit(1)

    client = genai.Client()
    
    # 1. Locate Core Files
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
            user_input = input(f"{ANSI_CYAN}Press ENTER to retry, or type 'exit' to quit: {ANSI_RESET}").strip()
            if user_input.lower() == 'exit': sys.exit(0)

    # 2. Parse State via ALU
    constants_text = load_file_content(constants_file)
    ledger_text = load_file_content(ledger_file)
    const_data = alu_utils.extract_constants_data(constants_text)
    ledger_data = alu_utils.extract_trend_metrics(ledger_text)
    
    # 3. Deterministic Math via ALU
    yield_data = alu_utils.calculate_temporal_yield(ledger_data, const_data['min_statistical_days'])
    spending_directive = alu_utils.evaluate_spending_variance(ledger_data['pacing_variance_value'])
    
    # UX UPGRADE: Print deterministic findings to terminal before LLM generation
    print(f"\n{ANSI_CYAN}" + "-"*60)
    print(" DETERMINISTIC ALU FINDINGS")
    print("-" * 60 + f"{ANSI_RESET}")
    print(f"Timeframe: {yield_data['delta_days']} days (Cold Start: {yield_data['is_cold_start']})")
    if not yield_data['is_cold_start']:
        print(f"Internal Yield: {yield_data['portfolio_yield_pct']:.2f}%")
    print(f"Pacing Variance: {spending_directive.split('.')[0]}")
    print(f"{ANSI_CYAN}" + "-"*60 + f"{ANSI_RESET}")
    
    # 4. Macro Telemetry & LLM Report Generation
    macro_benchmark_text = retrieve_macro_benchmark(client, yield_data)
    
    generate_final_report(
        client=client, 
        yield_data=yield_data, 
        benchmark_text=macro_benchmark_text, 
        spending_directive=spending_directive,
        market_status=ledger_data['market_status'],
        min_days=const_data['min_statistical_days']
    )

    print(f"\n{ANSI_CYAN}[System] Executing 30-Day Deep Freeze Sweep...{ANSI_RESET}")
    core_swept = alu_utils.execute_deep_freeze_sweep(DIR_CORE_ARCHIVE, DEEP_ARCHIVE_CORE)
    reports_swept = alu_utils.execute_deep_freeze_sweep(DIR_REPORTS_ARCHIVE, DEEP_ARCHIVE_REPORTS)
    total_swept = len(core_swept) + len(reports_swept)
    print(f"{ANSI_GREEN}[System] Deep Freeze Sweep complete. {total_swept} file(s) moved to offline archive.{ANSI_RESET}")

if __name__ == "__main__":
    main()