#06_standard_withdrawal.py
#"""
#Dynamic Standard Cash Withdrawal Request Engine
#Date: 2026-09-15
#Version: 1.0.0 (Hybrid Waterfall Engine)
#Role: Evaluates market state to route withdrawals between Cash (Bucket 1) and Equities (Buckets 2-8).
#"""
__version__ = "1.0.0"
__date__ = "2026-09-15"

import os
import sys
import glob
import re
import shutil
import json
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
OLD_CORE_DIR = os.path.join(BASE_DIR, "05_OLD_Core_Files")
REPORTS_DIR = os.path.join(BASE_DIR, "70 REPORTS")

for directory in [CORE_DIR, OLD_CORE_DIR, REPORTS_DIR]:
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
# PHASE 1: MACRO TELEMETRY & WATERFALL AUDIT
# ==============================================================================
def gather_waterfall_telemetry(client) -> str:
    print(f"\n{ANSI_CYAN}[System] Initiating Live Web Search for Waterfall Telemetry...{ANSI_RESET}")
    print(f"{ANSI_YELLOW}[API DISCLOSURE] Model: {LLM_MODEL_NAME} | Tool: Google Search | Thinking: High{ANSI_RESET}")
    
    search_prompt = """
    You are a financial data retrieval engine. You have access to Google Search.
    Search for and return the LIVE 7-day and 30-day performance trends for the following core benchmarks:
    S&P 500, VOO, SCHG, and SCHD.
    
    Based on this data, explicitly categorize the current active market state as ONE of the following:
    [DIP / CORRECTION], [NEUTRAL / SIDEWAYS], or [RALLY / EXPANSION].
    
    Output this data as a clean, structured text summary. Append citations: [Source: Website Name].
    """
    try:
        search_chat = client.chats.create(
            model=LLM_MODEL_NAME,
            config=types.GenerateContentConfig(tools=[{"google_search": {}}], temperature=0.1)
        )
        response = search_chat.send_message(search_prompt)
        print(f"{ANSI_GREEN}[System] Waterfall Telemetry successfully retrieved.{ANSI_RESET}")
        return response.text
    except Exception as e:
        print(f"{ANSI_RED}[WARNING] Failed to retrieve live data: {e}. Proceeding without live macro context.{ANSI_RESET}")
        return "LIVE MACRO DATA UNAVAILABLE."

def waterfall_audit_loop(client, withdrawal_amount: float, current_cash: float, search_data: str, custom_instructions: str):
    print(f"\n{ANSI_CYAN}[System] Initializing CIO Waterfall Audit...{ANSI_RESET}")
    
    chat_session = client.chats.create(
        model=LLM_MODEL_NAME,
        config=types.GenerateContentConfig(
            temperature=0.1,
            system_instruction=custom_instructions,
            tools=[{"google_search": {}}]
        )
    )
    
    target_cash = 85000.00
    floor_cash = 20000.00
    tank_ratio = current_cash / target_cash if target_cash > 0 else 1.0
    
    initial_prompt = f"""
    You are the Fiduciary Financial Architect. Execute a Dynamic Sourcing & Cash Buffer Waterfall Audit.
    
    [DATA PAYLOAD]
    - Target Withdrawal Amount: ${withdrawal_amount:,.2f}
    - Current Bucket 1 Operational Cash: ${current_cash:,.2f}
    - CONST_SAVINGS_TARGET: ${target_cash:,.2f}
    - CONST_SAVINGS_FLOOR: ${floor_cash:,.2f}
    - Tank Capacity Ratio: {tank_ratio*100:.1f}%
    
    [MACRO TELEMETRY]
    {search_data}
    
    [WATERFALL MATRIX RULES]
    1. If Market = DIP/CORRECTION: Prioritize sourcing from Cash to avoid selling equities at a loss, UNLESS Cash drops below the $20k Floor.
    2. If Market = RALLY/EXPANSION: Prioritize sourcing from Equities (Tax-Loss Harvesting or Rebalancing) to preserve Cash, especially if Cash is below the $85k Target.
    3. If Market = NEUTRAL: Recommend a balanced split or standard TLH.
    
    Evaluate the data and recommend the exact dollar allocation split: $X from Cash / $Y from Equities.
    Output your analysis strictly formatted as an 80-character line-wrapped Markdown text block.
    """
    
    transcript = ""
    try:
        response = chat_session.send_message(initial_prompt)
        print(f"\n{ANSI_YELLOW}--- CIO WATERFALL AUDIT ---{ANSI_RESET}")
        print(f"{response.text}")
        print(f"{ANSI_YELLOW}---------------------------{ANSI_RESET}")
        transcript += f"--- CIO WATERFALL AUDIT ---\n{response.text}\n---------------------------\n"
    except Exception as e:
        print(f"{ANSI_RED}[ERROR] AI generation failed: {e}{ANSI_RESET}")
        return chat_session, transcript
        
    print(f"\n{ANSI_GREEN}[System] You can now ask follow-up questions or challenge the AI's logic.{ANSI_RESET}")
    print("Type 'done' or 'exit' when you are ready to proceed to the final execution menu.")
    
    while True:
        user_input = input(f"\n{ANSI_CYAN}[You]: {ANSI_RESET}").strip()
        if user_input.lower() in ['done', 'exit']:
            print(f"\n{ANSI_CYAN}[System] Audit session finalized.{ANSI_RESET}")
            break
        if not user_input: continue
            
        try:
            reply = chat_session.send_message(user_input)
            print(f"\n{ANSI_YELLOW}--- AI RESPONSE ---{ANSI_RESET}")
            print(f"{reply.text}")
            print(f"{ANSI_YELLOW}-------------------{ANSI_RESET}")
            transcript += f"\n[User]: {user_input}\n\n--- AI RESPONSE ---\n{reply.text}\n-------------------\n"
        except Exception as e:
            print(f"{ANSI_RED}[ERROR] Communication failed: {e}{ANSI_RESET}")

    return chat_session, transcript

# ==============================================================================
# PHASE 2: EQUITY EXECUTION (IF APPLICABLE)
# ==============================================================================
def fetch_live_prices(client, selected_lots: list) -> dict:
    tickers = [lot['ticker'] for lot in selected_lots]
    print(f"\n{ANSI_CYAN}[System] Fetching live market prices for {tickers}...{ANSI_RESET}")
    prompt = f"""
    You are a financial API. Find the CURRENT LIVE market price for the following tickers: {tickers}.
    CRITICAL: Output ONLY a valid JSON object mapping the ticker string to the float price.
    Example format: {{"VOO": 450.23, "USFR": 50.12}}
    """
    live_prices = {}
    try:
        chat = client.chats.create(model=LLM_MODEL_NAME, config=types.GenerateContentConfig(tools=[{"google_search": {}}], temperature=0.0))
        response = chat.send_message(prompt)
        json_match = re.search(r'\{.*?\}', response.text.strip(), re.DOTALL)
        if json_match:
            live_prices = json.loads(json_match.group(0))
            print(f"{ANSI_GREEN}[System] Live prices secured.{ANSI_RESET}")
    except Exception as e:
        print(f"{ANSI_RED}[WARNING] Live Pricing Failed: {e}. Falling back to ledger prices.{ANSI_RESET}")
        
    for lot in selected_lots:
        t = lot['ticker']
        if t not in live_prices or not isinstance(live_prices[t], (int, float)):
            live_prices[t] = lot['ledger_price']
    return live_prices

# ==============================================================================
# PHASE 3: REPORT GENERATION
# ==============================================================================
def generate_sourcing_report(cash_withdrawal: float, equity_withdrawal: float, liquidations: list, total_withdrawal: float, total_tax_impact: float, new_var: float, new_hr: float, new_file: str, chat_transcript: str):
    date_str = datetime.now().strftime("%Y-%m-%d")
    base_name = f"Standard_Withdrawal_and_Sourcing_Plan_{date_str}"
    next_version = get_next_version_number(REPORTS_DIR, base_name)
    final_filename = f"{base_name}_v{next_version}.txt"
    final_filepath = os.path.join(REPORTS_DIR, final_filename)
    
    report_text = f"""File Name: {final_filename}
================================================================================
DYNAMIC STANDARD CASH WITHDRAWAL REPORT
Date: {date_str} (Version {next_version})
Role: Waterfall Sourcing & Ledger Integrity
File Name: {final_filename}
================================================================================

1. WATERFALL SOURCING EXECUTION:
  - Total Withdrawal Requested: ${total_withdrawal:,.2f}
  - Sourced from Bucket 1 (Operational Cash): ${cash_withdrawal:,.2f}
  - Sourced from Buckets 2-8 (Equities): ${equity_withdrawal:,.2f}
"""
    if liquidations:
        report_text += "\n2. TARGETED EQUITY LIQUIDATION PLAN:\n"
        for liq in liquidations:
            report_text += f"  - Sell {liq['sell_shares']:.4f} shares of {liq['ticker']} (Bucket {liq['bucket']} / Acct {liq['account']}) @ ${liq['sell_price']:.2f}\n"
            report_text += f"    * Proceeds: ${liq['sell_amount']:,.2f} | Realized Tax Impact: ${liq['realized_gain']:,.2f}\n"
            
    polarity = "Surplus (Underspending)" if new_var >= 0 else "Deficit (Overspending)"
    
    report_text += f"""
3. TAX EFFICIENCY AUDIT & HEADROOM RECONCILIATION:
  - Net Transaction Tax Impact: ${total_tax_impact:,.2f}
  - Projected Remaining 0% LTCG Headroom: ${new_hr:,.2f}

4. DATE-AWARE PACING ENGINE STATUS:
  - Updated Net Pacing Variance: ${new_var:,.2f} -> [{polarity}]

5. CORE FILE LEDGER INTEGRATION:
  - Portfolio Ledger successfully rebuilt and rewritten.
  - Reconciled Total System Capital dynamically reduced by ${total_withdrawal:,.2f}.
  - New Active Ledger: {os.path.basename(new_file)}

================================================================================
6. CIO WATERFALL AUDIT LOG (CHAT TRANSCRIPT):
================================================================================
{chat_transcript}
================================================================================
"""
    with open(final_filepath, "w", encoding="utf-8") as f:
        f.write(report_text)
    return final_filepath

# ==============================================================================
# MAIN ORCHESTRATOR
# ==============================================================================
def main():
    print(f"{ANSI_CYAN}" + "="*60)
    print(" AVENUE C: DYNAMIC STANDARD CASH WITHDRAWAL ENGINE")
    print("="*60 + f"{ANSI_RESET}")
    
    load_dotenv()
    if not os.environ.get("GEMINI_API_KEY"):
        print(f"{ANSI_RED}[FATAL ERROR] GEMINI_API_KEY environment variable not found.{ANSI_RESET}")
        sys.exit(1)
    client = genai.Client()
    
    # 1. Robust User Input
    print(f"\n{ANSI_CYAN}Please enter the exact total withdrawal amount required:{ANSI_RESET}")
    while True:
        user_input = input(f"{ANSI_YELLOW}Amount (e.g., $10,000): {ANSI_RESET}").strip()
        total_withdrawal = extract_currency(user_input)
        if total_withdrawal > 0: break
        print(f"{ANSI_RED}[ERROR] Invalid amount detected.{ANSI_RESET}")
            
    # 2. Locate & Parse Core Files
    print(f"\n{ANSI_CYAN}[System] Locating Core Files...{ANSI_RESET}")
    try:
        constants_file = get_latest_file(CORE_DIR, "GEM_Retirement_Master_Profile_Constants_*.txt")
        ledger_file = get_latest_file(CORE_DIR, "GEM_Retirement_Portfolio_Ledger_*.txt")
        instructions_file = get_latest_file(CORE_DIR, "Fiduciary_Architect_Instructions_*.txt")
    except Exception as e:
        print(f"{ANSI_RED}[FATAL ERROR] {e}{ANSI_RESET}"); sys.exit(1)

    ledger_text = load_file_content(ledger_file)
    custom_instructions = load_file_content(instructions_file)
    portfolio = alu_utils.extract_ledger_portfolio(ledger_text)
    current_cash = alu_utils.extract_bucket_1_cash(ledger_text)
    
    # 3. Macro Telemetry & Waterfall Audit
    search_data = gather_waterfall_telemetry(client)
    chat_session, chat_transcript = waterfall_audit_loop(client, total_withdrawal, current_cash, search_data, custom_instructions)
    
    # 4. Deterministic Split Routing
    print(f"\n{ANSI_CYAN}" + "="*60)
    print(" FINAL EXECUTION ROUTING")
    print("="*60 + f"{ANSI_RESET}")
    print(f"Total Withdrawal Required: ${total_withdrawal:,.2f}")
    print(f"Current Bucket 1 Cash: ${current_cash:,.2f}")
    
    while True:
        cash_input = input(f"\n{ANSI_YELLOW}Enter amount to source from Bucket 1 CASH (0 to {total_withdrawal}): {ANSI_RESET}").strip()
        cash_withdrawal = extract_currency(cash_input)
        if 0 <= cash_withdrawal <= total_withdrawal:
            if cash_withdrawal > current_cash:
                print(f"{ANSI_RED}[ERROR] You only have ${current_cash:,.2f} in Bucket 1.{ANSI_RESET}")
                continue
            break
        print(f"{ANSI_RED}[ERROR] Invalid amount.{ANSI_RESET}")
        
    equity_withdrawal = total_withdrawal - cash_withdrawal
    print(f"{ANSI_GREEN}[System] Routing: ${cash_withdrawal:,.2f} from Cash | ${equity_withdrawal:,.2f} from Equities.{ANSI_RESET}")
    
    # 5. Equity Execution (If Applicable)
    liquidations = []
    total_tax_impact = 0.0
    if equity_withdrawal > 0:
        print(f"\n{ANSI_CYAN}Please enter any Buckets to EXEMPT from Equity Sourcing (e.g., '8' or '4,5').{ANSI_RESET}")
        exempt_input = input(f"{ANSI_YELLOW}Exempt Buckets (Press ENTER for none): {ANSI_RESET}").strip()
        user_exemptions = [int(x) for x in re.findall(r'\d', exempt_input)] if exempt_input else []
        final_exemptions = list(set([1, 6] + user_exemptions))
        
        quant_baseline_lots = alu_utils.select_tax_optimized_lots(portfolio, equity_withdrawal, final_exemptions)
        baseline_tickers = ", ".join([lot['ticker'] for lot in quant_baseline_lots])
        
        print(f"\n{ANSI_CYAN}The Quant Baseline selected: {ANSI_YELLOW}[{baseline_tickers}]{ANSI_RESET}")
        print("To execute the Baseline, press ENTER.")
        print("To override, type the specific tickers (e.g., 'SCHG') and press ENTER.")
        
        final_lots = []
        while True:
            override_input = input(f"\n{ANSI_YELLOW}Your Selection: {ANSI_RESET}").strip().upper()
            if not override_input:
                final_lots = quant_baseline_lots
                break
            else:
                override_tickers = [t.strip() for t in re.split(r'[, ]+', override_input) if t.strip()]
                final_lots = alu_utils.get_lots_by_tickers(portfolio, override_tickers, final_exemptions)
                if final_lots: break
                print(f"{ANSI_RED}[ERROR] Tickers not found. Try again.{ANSI_RESET}")
                
        live_prices = fetch_live_prices(client, final_lots)
        liquidations = alu_utils.calculate_exact_liquidations(final_lots, live_prices, equity_withdrawal)
        total_tax_impact = sum(liq['realized_gain'] for liq in liquidations)

    # 6. Rebuild File Text via ALU
    new_text, new_var, new_hr = alu_utils.update_ledger_text(ledger_text, liquidations, total_withdrawal, total_tax_impact, cash_withdrawal)
    
    # 7. Generate File Header Versioning & Save
    match = re.search(r'_v(\d+)\.txt', os.path.basename(ledger_file))
    old_version = int(match.group(1)) if match else 0
    new_version = old_version + 1
    today = datetime.now().strftime("%Y-%m-%d")
    
    new_text = re.sub(r'Date: \d{4}-\d{2}-\d{2} \(Version \d+\)', f'Date: {today} (Version {new_version})', new_text)
    new_text = re.sub(r'GEM_Retirement_Portfolio_Ledger_\d{4}-\d{2}-\d{2}_v\d+\.txt', f'GEM_Retirement_Portfolio_Ledger_{today}_v{new_version}.txt', new_text)
    
    final_filepath = os.path.join(CORE_DIR, f"GEM_Retirement_Portfolio_Ledger_{today}_v{new_version}.txt")
    with open(final_filepath, "w", encoding="utf-8") as f:
        f.write(new_text)
    
    # 8. Execute Clean Room Archiving
    old_ledger_name = os.path.basename(ledger_file)
    shutil.move(ledger_file, os.path.join(OLD_CORE_DIR, old_ledger_name))
    
    # 9. Generate Permanent Report
    report_path = generate_sourcing_report(cash_withdrawal, equity_withdrawal, liquidations, total_withdrawal, total_tax_impact, new_var, new_hr, final_filepath, chat_transcript)
    
    # 10. Final Output
    print(f"\n{ANSI_GREEN}" + "="*60)
    print(f" [SUCCESS] Portfolio Ledger Mutated: {os.path.basename(final_filepath)}")
    print(f" [SUCCESS] Old Ledger Archived: {old_ledger_name}")
    print(f" [SUCCESS] Sourcing Plan Saved to: {report_path}")
    print(" [SYSTEM] Execution Complete. Terminating.")
    print("="*60 + f"{ANSI_RESET}\n")

if __name__ == "__main__":
    main()