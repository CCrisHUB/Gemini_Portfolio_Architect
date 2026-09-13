#03_trend_and_pacing.py
#"""
#Trend Tracking & Financial Pacing Engine
#Date: 2026-09-15
#Version: 1.1.0 (ALU Refactor & UX Transparency Upgrade)
#Role: Evaluates temporal yield, cold-start logic, and spending pacing variance.
#"""
__version__ = "1.1.0"
__date__ = "2026-09-15"

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
# MASTER CONFIGURATION & DIRECTORY STRUCTURE
# ==============================================================================
LLM_MODEL_NAME = 'gemini-3.1-pro-preview'

BASE_DIR = r"C:\10_Projects\Gemini_Portfolio_Architect"
CORE_DIR = os.path.join(BASE_DIR, "00_CORE_Files")
REPORTS_DIR = os.path.join(BASE_DIR, "70 REPORTS")

for directory in [CORE_DIR, REPORTS_DIR]:
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
    next_version = get_next_version_number(REPORTS_DIR, base_name)
    final_filename = f"{base_name}_v{next_version}.txt"
    final_filepath = os.path.join(REPORTS_DIR, final_filename)
    
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
            constants_file = get_latest_file(CORE_DIR, "GEM_Retirement_Master_Profile_Constants_*.txt")
            ledger_file = get_latest_file(CORE_DIR, "GEM_Retirement_Portfolio_Ledger_*.txt")
            print(f"{ANSI_GREEN}✅ Detected: {os.path.basename(constants_file)}{ANSI_RESET}")
            print(f"{ANSI_GREEN}✅ Detected: {os.path.basename(ledger_file)}{ANSI_RESET}")
            break
        except FileNotFoundError as e:
            print(f"\n{ANSI_RED}❌ ERROR: Missing Core Files in '{CORE_DIR}'.{ANSI_RESET}")
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

if __name__ == "__main__":
    main()