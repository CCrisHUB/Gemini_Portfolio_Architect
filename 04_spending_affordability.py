#04_spending_affordability.py
#"""
#Spending Request & Affordability Evaluation Engine
#Date: 2026-09-15
#Version: 1.0.0 
#Role: Evaluates discretionary spending requests against liquidity and market telemetry.
#"""
__version__ = "1.0.0"
__date__ = "2026-09-15"

import os
import sys
import glob
import re
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
# PHASE 1: PROGRAMMATIC STATE EXTRACTION
# ==============================================================================
def extract_constants_data(constants_text: str) -> dict:
    data = {'min_statistical_days': 90}
    match_days = re.search(r'CONST_MIN_STATISTICAL_DAYS\s*:\s*(\d+)', constants_text)
    if match_days:
        data['min_statistical_days'] = int(match_days.group(1))
    return data

def extract_ledger_data(ledger_text: str) -> dict:
    data = {
        'market_status': 'UNKNOWN',
        'total_executed_equities': 0.0,
        'pacing_variance_value': 0.0,
        'milestones': []
    }
    
    match_status = re.search(r'Active Market Status Designation:\s*\[(.*?)\]', ledger_text)
    if match_status:
        data['market_status'] = match_status.group(1).strip()
        
    match_executed = re.search(r'Total Executed Holdings Market Value.*?\:\s*\$?([\d,]+\.\d{2})', ledger_text)
    if match_executed:
        data['total_executed_equities'] = float(match_executed.group(1).replace(',', ''))
        
    match_variance = re.search(r'Net Adjusted Pacing Variance:\s*([+-]?)\$?([+-]?[\d,]+\.\d{2})', ledger_text)
    if match_variance:
        sign = match_variance.group(1)
        val_str = match_variance.group(2)
        if val_str.startswith('-') or sign == '-':
            multiplier = -1.0
            val_str = val_str.replace('-', '')
        else:
            multiplier = 1.0
            val_str = val_str.replace('+', '')
        data['pacing_variance_value'] = float(val_str.replace(',', '')) * multiplier

    milestone_block_match = re.search(r'ROLLING HISTORICAL MILESTONE LEDGER.*?\n(.*?)(?:={80}|\Z)', ledger_text, re.DOTALL)
    if milestone_block_match:
        milestone_block = milestone_block_match.group(1)
        pattern = r'\[(\d{4}-\d{2}-\d{2})\s*\|.*?\s*\$?[\d,]+\.\d{2}\s*\|\s*\$?([\d,]+\.\d{2})\s*\|'
        matches = re.findall(pattern, milestone_block)
        for date_str, eq_str in matches:
            data['milestones'].append({
                'date': datetime.strptime(date_str, "%Y-%m-%d"),
                'executed_equities': float(eq_str.replace(',', ''))
            })
            
    data['milestones'] = sorted(data['milestones'], key=lambda x: x['date'])
    return data

# ==============================================================================
# PHASE 2: LIQUIDITY GATE CALCULATION
# ==============================================================================
def calculate_liquidity_gate(requested_spend: float, variance: float) -> dict:
    available_budget = variance if variance > 0 else 0.0
    is_sufficient = requested_spend <= available_budget
    return {
        'available_budget': available_budget,
        'is_sufficient': is_sufficient
    }

# ==============================================================================
# PHASE 3: MARKET TELEMETRY & COLD-START LOGIC
# ==============================================================================
def calculate_temporal_yield(ledger_data: dict, min_days: int) -> dict:
    yield_data = {
        'delta_days': 0,
        'is_cold_start': True,
        'portfolio_yield_pct': 0.0,
        'oldest_date_str': '',
        'current_date_str': datetime.now().strftime("%Y-%m-%d")
    }
    
    if not ledger_data['milestones']:
        return yield_data
        
    oldest_node = ledger_data['milestones'][0]
    current_val = ledger_data['total_executed_equities']
    oldest_val = oldest_node['executed_equities']
    
    current_date = datetime.now()
    delta = current_date - oldest_node['date']
    yield_data['delta_days'] = delta.days
    yield_data['oldest_date_str'] = oldest_node['date'].strftime("%Y-%m-%d")
    
    if yield_data['delta_days'] >= min_days:
        yield_data['is_cold_start'] = False
        if oldest_val > 0:
            yield_data['portfolio_yield_pct'] = ((current_val - oldest_val) / oldest_val) * 100.0
            
    return yield_data

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

def extract_proxy_yield_from_text(benchmark_text: str) -> float:
    match = re.search(r'([+-]?\d+\.\d+)%', benchmark_text)
    if match:
        return float(match.group(1))
    return 0.0

# ==============================================================================
# PHASE 4: THE A/B/C MULTI-DIMENSIONAL DECISION MATRIX
# ==============================================================================
def evaluate_decision_matrix(requested: float, budget: float, market_status: str, portfolio_yield: float, benchmark: float) -> str:
    """Executes the strict algorithmic evaluation of the spending request."""
    status_upper = market_status.upper()
    
    # 1. INSUFFICIENT BUDGET (Overrides all market conditions)
    if requested > budget:
        return "REJECT. You do not have the YTD liquidity to support this purchase without cannibalizing future mandatory fixed liabilities."
        
    # 2. CONDITION C (Crash / Bear Market)
    if "RED ACTIVATED" in status_upper or portfolio_yield < -15.0:
        return "REJECT. Discretionary spending is frozen. Capital preservation protocols are active to protect the cash bridge."
        
    # 3. CONDITION B (Anemic / Drag)
    if "NORMAL" in status_upper or "NEUTRAL" in status_upper or "SIDEWAYS" in status_upper:
        if portfolio_yield < 0.0 or portfolio_yield < (benchmark - 1.50):
            return "CAUTION & REDUCE. You have the baseline budget, but your portfolio is experiencing systemic drag or nominal losses. Recommend downgrading the purchase cost by 30% to 50% or postponing."
            
    # 4. CONDITION A (Excellent / Green Light)
    if "NORMAL" in status_upper or "NEUTRAL" in status_upper or "SIDEWAYS" in status_upper:
        if portfolio_yield >= 0.0 and portfolio_yield >= (benchmark - 1.50):
            return "APPROVED. Liquidity is secured, pending liabilities are funded, and the portfolio is operating at optimal efficiency."
            
    # Fallback (Just in case market status string is malformed)
    return "PENDING. Manual review required due to ambiguous market status designation in the Portfolio Ledger."

# ==============================================================================
# PHASE 5: OUTPUT PAYLOAD GENERATION (LLM FORMATTING)
# ==============================================================================
def generate_final_report(client, requested: float, budget: float, yield_data: dict, benchmark_text: str, directive: str, effective_yield: float) -> None:
    print(f"\n{ANSI_CYAN}[System] Generating Final Fiduciary Report...{ANSI_RESET}")
    
    date_str = datetime.now().strftime("%Y-%m-%d")
    base_name = f"Discretionary_Spending_Request_Audit_{date_str}"
    next_version = get_next_version_number(REPORTS_DIR, base_name)
    final_filename = f"{base_name}_v{next_version}.txt"
    final_filepath = os.path.join(REPORTS_DIR, final_filename)
    
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
            constants_file = get_latest_file(CORE_DIR, "GEM_Retirement_Master_Profile_Constants_*.txt")
            ledger_file = get_latest_file(CORE_DIR, "GEM_Retirement_Portfolio_Ledger_*.txt")
            print(f"{ANSI_GREEN}✅ Detected: {os.path.basename(constants_file)}{ANSI_RESET}")
            print(f"{ANSI_GREEN}✅ Detected: {os.path.basename(ledger_file)}{ANSI_RESET}")
            break
        except FileNotFoundError as e:
            print(f"\n{ANSI_RED}❌ ERROR: Missing Core Files in '{CORE_DIR}'.{ANSI_RESET}")
            print(f"{ANSI_YELLOW}{e}{ANSI_RESET}")
            retry = input(f"{ANSI_CYAN}Press ENTER to retry, or type 'exit' to quit: {ANSI_RESET}").strip()
            if retry.lower() == 'exit': sys.exit(0)

    constants_text = load_file_content(constants_file)
    ledger_text = load_file_content(ledger_file)
    const_data = extract_constants_data(constants_text)
    ledger_data = extract_ledger_data(ledger_text)
    
    # PHASE 2
    liquidity_data = calculate_liquidity_gate(requested_spend, ledger_data['pacing_variance_value'])
    
    # PHASE 3
    yield_data = calculate_temporal_yield(ledger_data, const_data['min_statistical_days'])
    macro_benchmark_text = retrieve_macro_benchmark(client, yield_data)
    
    benchmark_yield_pct = extract_proxy_yield_from_text(macro_benchmark_text)
    effective_portfolio_yield = benchmark_yield_pct if yield_data['is_cold_start'] else yield_data['portfolio_yield_pct']
    
    # PHASE 4
    directive = evaluate_decision_matrix(
        requested=requested_spend,
        budget=liquidity_data['available_budget'],
        market_status=ledger_data['market_status'],
        portfolio_yield=effective_portfolio_yield,
        benchmark=benchmark_yield_pct
    )
    
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

if __name__ == "__main__":
    main()