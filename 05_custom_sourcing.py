#05_custom_sourcing.py
#"""
#Dynamic Custom Sourcing & Liquidation Engine
#Date: 2026-09-15
#Version: 2.0.4 (UX Polish: Streamlined Execution Prompt)
#Role: Executes tax-optimized liquidations, live macro telemetry, LLM Fiduciary Audit, and ledger updates.
#"""
__version__ = "2.0.4"
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
# HELPER FUNCTIONS (FILE I/O)
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
# PHASE 1: MACRO TELEMETRY & CIO AUDIT LOOP
# ==============================================================================
def gather_live_macro_data(client, target_lots: list) -> str:
    print(f"\n{ANSI_CYAN}[System] Initiating Live Web Search via Gemini API...{ANSI_RESET}")
    print(f"{ANSI_YELLOW}[API DISCLOSURE] Model: {LLM_MODEL_NAME} | Tool: Google Search | Thinking: High{ANSI_RESET}")
    
    target_tickers = [lot['ticker'] for lot in target_lots]
    
    search_prompt = f"""
    You are a financial data retrieval engine. You have access to Google Search.
    
    [DATA PROVENANCE MANDATE]
    RESTRICT ALL SEARCHES to Tier-1 financial institutions (e.g., Morningstar, Bloomberg, Reuters, Federal Reserve, WSJ). 
    EXCLUDE all social media, Reddit, and opinion blogs.
    
    Search for and return the LIVE current data for the following:
    1. Macro-Economic Climate: Current US market cycle, interest rate trends, and leading/lagging sectors.
    2. Target Tickers for Liquidation: {target_tickers}
       - Find their 30-day trend and any immediate macroeconomic headwinds/tailwinds.
       
    Output this data as a clean, structured text summary. For EVERY data point, append a citation: [Source: Website Name].
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
        print(f"{ANSI_RED}[WARNING] Failed to retrieve live data: {e}. Proceeding without live macro context.{ANSI_RESET}")
        return "LIVE MACRO DATA UNAVAILABLE."

def fiduciary_audit_loop(client, quant_lots: list, search_data: str, custom_instructions: str, ledger_text: str, withdrawal_amount: float):
    print(f"\n{ANSI_CYAN}[System] Initializing CIO Fiduciary Audit...{ANSI_RESET}")
    print(f"{ANSI_YELLOW}[API DISCLOSURE] Model: {LLM_MODEL_NAME} | Thinking Level: High{ANSI_RESET}")
    
    chat_session = client.chats.create(
        model=LLM_MODEL_NAME,
        config=types.GenerateContentConfig(
            temperature=0.1,
            system_instruction=custom_instructions,
            tools=[{"google_search": {}}]
        )
    )
    
    quant_proposal_str = "\n".join([f"- {lot['ticker']} (Bucket {lot['bucket']}): Value ${lot['value']:,.2f} | Gain/Loss: ${lot['gain']:,.2f}" for lot in quant_lots])
    
    initial_prompt = f"""
    You are the Fiduciary Financial Architect. Execute a Sourcing & Liquidation Audit.
    
    [DATA PAYLOAD]
    1. Macro Portfolio State (Master Ledger):
    {ledger_text}
    
    2. Target Withdrawal Amount: ${withdrawal_amount:,.2f}
    
    3. The Quant Baseline Proposal (Mathematically sorted by % loss):
    {quant_proposal_str}
    
    4. Live Macro & Search Data:
    {search_data}
    
    [FIDUCIARY MANDATE]
    Review the Quant Baseline Proposal. Does it make macroeconomic sense to liquidate these specific assets right now based on the live search data? 
    If the algorithm selected a ticker that is currently at a cyclical bottom or facing a temporary headwind that will reverse, you MUST advise the user to override the algorithm and suggest a better alternative from their portfolio.
    If the algorithm's choice is sound, validate it.
    
    [STRICT NEGATIVE CONSTRAINT]
    Do NOT recommend sourcing funds from Bucket 1 (Cash/Liquidity). The user has explicitly chosen to preserve cash and execute an equity liquidation. Your recommendation MUST be an equity liquidation from the available taxable buckets.
    
    Output your analysis strictly formatted as an 80-character line-wrapped Markdown text block.
    """
    
    transcript = ""
    print(f"{ANSI_CYAN}[System] AI is analyzing the Quant Baseline against Macro Realities. Please wait...{ANSI_RESET}")
    try:
        response = chat_session.send_message(initial_prompt)
        print(f"\n{ANSI_YELLOW}--- CIO FIDUCIARY AUDIT ---{ANSI_RESET}")
        print(f"{response.text}")
        print(f"{ANSI_YELLOW}---------------------------{ANSI_RESET}")
        transcript += f"--- CIO FIDUCIARY AUDIT ---\n{response.text}\n---------------------------\n"
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
        if not user_input:
            continue
            
        print(f"{ANSI_CYAN}[System] Sending to {LLM_MODEL_NAME}...{ANSI_RESET}")
        try:
            reply = chat_session.send_message(user_input)
            print(f"\n{ANSI_YELLOW}--- AI RESPONSE ---{ANSI_RESET}")
            print(f"{reply.text}")
            print(f"{ANSI_YELLOW}-------------------{ANSI_RESET}")
            transcript += f"\n[User]: {user_input}\n"
            transcript += f"\n--- AI RESPONSE ---\n{reply.text}\n-------------------\n"
        except Exception as e:
            print(f"{ANSI_RED}[ERROR] Communication failed: {e}{ANSI_RESET}")

    return chat_session, transcript

# ==============================================================================
# PHASE 2: EXECUTION, LIVE PRICING & FILE REBUILDING
# ==============================================================================
def fetch_live_prices(client, selected_lots: list) -> dict:
    tickers = [lot['ticker'] for lot in selected_lots]
    print(f"\n{ANSI_CYAN}[System] Fetching live market prices for {tickers}...{ANSI_RESET}")
    
    prompt = f"""
    You are a financial API. You have access to Google Search.
    Find the CURRENT LIVE market price for the following tickers: {tickers}.
    CRITICAL: Output ONLY a valid JSON object mapping the ticker string to the float price.
    Do NOT include markdown formatting, backticks, or citations.
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
        else:
            raise ValueError("No JSON found.")
    except Exception as e:
        print(f"{ANSI_RED}[WARNING] Live Pricing Failed: {e}. Falling back to ledger prices.{ANSI_RESET}")
        
    for lot in selected_lots:
        t = lot['ticker']
        if t not in live_prices or not isinstance(live_prices[t], (int, float)):
            live_prices[t] = lot['ledger_price']
    return live_prices

def generate_sourcing_report(liquidations: list, withdrawal_amount: float, total_tax_impact: float, new_var: float, new_hr: float, new_file: str, chat_transcript: str):
    date_str = datetime.now().strftime("%Y-%m-%d")
    base_name = f"Liquidation_and_Sourcing_Plan_{date_str}"
    next_version = get_next_version_number(REPORTS_DIR, base_name)
    final_filename = f"{base_name}_v{next_version}.txt"
    final_filepath = os.path.join(REPORTS_DIR, final_filename)
    
    report_text = f"""File Name: {final_filename}
================================================================================
EXECUTIVE LIQUIDATION & SOURCING REPORT
Date: {date_str} (Version {next_version})
Role: Tax-Optimized Sourcing & Ledger Integrity
File Name: {final_filename}
================================================================================

1. TARGETED LIQUIDATION PLAN (Execute in Brokerage):
"""
    for liq in liquidations:
        report_text += f"  - Sell {liq['sell_shares']:.4f} shares of {liq['ticker']} (Bucket {liq['bucket']} / Acct {liq['account']}) @ ${liq['sell_price']:.2f}\n"
        report_text += f"    * Proceeds: ${liq['sell_amount']:,.2f} | Realized Tax Impact: ${liq['realized_gain']:,.2f}\n"
        
    polarity = "Surplus (Underspending)" if new_var >= 0 else "Deficit (Overspending)"
    
    report_text += f"""
2. TAX EFFICIENCY AUDIT & HEADROOM RECONCILIATION:
  - Net Transaction Tax Impact: ${total_tax_impact:,.2f}
  - Projected Remaining 0% LTCG Headroom: ${new_hr:,.2f}

3. DATE-AWARE PACING ENGINE STATUS:
  - Withdrawal Requested: ${withdrawal_amount:,.2f}
  - Updated Net Pacing Variance: ${new_var:,.2f} -> [{polarity}]

4. CORE FILE LEDGER INTEGRATION:
  - Portfolio Ledger successfully rebuilt and rewritten.
  - Reconciled Total System Capital dynamically reduced by ${withdrawal_amount:,.2f}.
  - New Active Ledger: {os.path.basename(new_file)}

================================================================================
5. CIO FIDUCIARY AUDIT LOG (CHAT TRANSCRIPT):
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
    print(" AVENUE C: HYBRID QUANT + CIO SOURCING ENGINE")
    print("="*60 + f"{ANSI_RESET}")
    
    load_dotenv()
    if not os.environ.get("GEMINI_API_KEY"):
        print(f"{ANSI_RED}[FATAL ERROR] GEMINI_API_KEY environment variable not found.{ANSI_RESET}")
        sys.exit(1)
    client = genai.Client()
    
    # 1. Robust User Input
    print(f"\n{ANSI_CYAN}Please enter the exact withdrawal amount required:{ANSI_RESET}")
    while True:
        user_input = input(f"{ANSI_YELLOW}Amount (e.g., $10,000): {ANSI_RESET}").strip()
        withdrawal_amount = extract_currency(user_input)
        if withdrawal_amount > 0: break
        print(f"{ANSI_RED}[ERROR] Invalid amount detected. Please enter a valid number.{ANSI_RESET}")
            
    print(f"\n{ANSI_CYAN}Please enter any Buckets to EXEMPT (e.g., '8' or '4,5').{ANSI_RESET}")
    while True:
        try:
            exempt_input = input(f"{ANSI_YELLOW}Exempt Buckets (Press ENTER for none): {ANSI_RESET}").strip()
            user_exemptions = [int(x) for x in re.findall(r'\d', exempt_input)] if exempt_input else []
            final_exemptions = list(set([1, 6] + user_exemptions))
            break
        except Exception as e:
            print(f"{ANSI_RED}[ERROR] Invalid input. Please enter numbers separated by commas.{ANSI_RESET}")
    
    # 2. Locate & Parse Core Files
    print(f"\n{ANSI_CYAN}[System] Locating Core Files...{ANSI_RESET}")
    try:
        constants_file = get_latest_file(CORE_DIR, "GEM_Retirement_Master_Profile_Constants_*.txt")
        ledger_file = get_latest_file(CORE_DIR, "GEM_Retirement_Portfolio_Ledger_*.txt")
        instructions_file = get_latest_file(CORE_DIR, "Fiduciary_Architect_Instructions_*.txt")
    except Exception as e:
        print(f"{ANSI_RED}[FATAL ERROR] {e}{ANSI_RESET}"); sys.exit(1)

    const_data = alu_utils.extract_constants_data(load_file_content(constants_file))
    ledger_text = load_file_content(ledger_file)
    custom_instructions = load_file_content(instructions_file)
    portfolio = alu_utils.extract_ledger_portfolio(ledger_text)
    
    # 3. Generate Quant Baseline Proposal
    print(f"{ANSI_CYAN}[System] Calculating Quant Baseline Proposal...{ANSI_RESET}")
    quant_baseline_lots = alu_utils.select_tax_optimized_lots(portfolio, withdrawal_amount, final_exemptions)
    
    if not quant_baseline_lots:
        print(f"{ANSI_RED}[FATAL ERROR] No active non-exempt holdings found to liquidate.{ANSI_RESET}"); sys.exit(1)
        
    # 4. Macro Telemetry & CIO Audit
    search_data = gather_live_macro_data(client, quant_baseline_lots)
    chat_session, chat_transcript = fiduciary_audit_loop(client, quant_baseline_lots, search_data, custom_instructions, ledger_text, withdrawal_amount)
    
    # 5. Human-in-the-Loop Override Trapping (UX FIX APPLIED HERE)
    baseline_tickers = ", ".join([lot['ticker'] for lot in quant_baseline_lots])
    
    print(f"\n{ANSI_CYAN}" + "="*60)
    print(" FINAL EXECUTION CONFIRMATION")
    print("="*60 + f"{ANSI_RESET}")
    print(f"The Quant Baseline selected: {ANSI_YELLOW}[{baseline_tickers}]{ANSI_RESET}\n")
    print("To execute the Baseline, press ENTER.")
    print("To execute the AI's advice, type the ticker(s) (e.g., SCHG) and press ENTER.")
    
    final_lots = []
    while True:
        override_input = input(f"\n{ANSI_YELLOW}Your Selection: {ANSI_RESET}").strip().upper()
        if not override_input:
            final_lots = quant_baseline_lots
            print(f"{ANSI_GREEN}[System] Baseline [{baseline_tickers}] accepted. Proceeding with execution...{ANSI_RESET}")
            break
        else:
            override_tickers = [t.strip() for t in re.split(r'[, ]+', override_input) if t.strip()]
            final_lots = alu_utils.get_lots_by_tickers(portfolio, override_tickers, final_exemptions)
            
            if not final_lots:
                print(f"{ANSI_RED}[ERROR] None of the entered tickers were found in non-exempt buckets. Try again.{ANSI_RESET}")
                continue
                
            total_override_value = sum(lot['value'] for lot in final_lots)
            if total_override_value < withdrawal_amount:
                print(f"{ANSI_RED}[WARNING] Selected tickers only have a combined value of ${total_override_value:,.2f}.")
                print(f"This is less than the requested withdrawal of ${withdrawal_amount:,.2f}.{ANSI_RESET}")
                retry = input(f"{ANSI_YELLOW}Do you want to select different tickers? (y/n): {ANSI_RESET}").strip().lower()
                if retry == 'y':
                    continue
            
            print(f"{ANSI_GREEN}[System] Override accepted. Proceeding with execution...{ANSI_RESET}")
            break

    # 6. Live Pricing & Exact Math Execution
    live_prices = fetch_live_prices(client, final_lots)
    liquidations = alu_utils.calculate_exact_liquidations(final_lots, live_prices, withdrawal_amount)
    total_tax_impact = sum(liq['realized_gain'] for liq in liquidations)
    
    # 7. Rebuild File Text via ALU
    new_text, new_var, new_hr = alu_utils.update_ledger_text(ledger_text, liquidations, withdrawal_amount, total_tax_impact)
    
    # 8. Generate File Header Versioning & Save
    match = re.search(r'_v(\d+)\.txt', os.path.basename(ledger_file))
    old_version = int(match.group(1)) if match else 0
    new_version = old_version + 1
    today = datetime.now().strftime("%Y-%m-%d")
    
    new_text = re.sub(r'Date: \d{4}-\d{2}-\d{2} \(Version \d+\)', f'Date: {today} (Version {new_version})', new_text)
    new_text = re.sub(r'GEM_Retirement_Portfolio_Ledger_\d{4}-\d{2}-\d{2}_v\d+\.txt', f'GEM_Retirement_Portfolio_Ledger_{today}_v{new_version}.txt', new_text)
    
    final_filepath = os.path.join(CORE_DIR, f"GEM_Retirement_Portfolio_Ledger_{today}_v{new_version}.txt")
    with open(final_filepath, "w", encoding="utf-8") as f:
        f.write(new_text)
    
    # 9. Execute Clean Room Archiving
    old_ledger_name = os.path.basename(ledger_file)
    shutil.move(ledger_file, os.path.join(OLD_CORE_DIR, old_ledger_name))
    
    # 10. Generate Permanent Report (with Chat Transcript)
    report_path = generate_sourcing_report(liquidations, withdrawal_amount, total_tax_impact, new_var, new_hr, final_filepath, chat_transcript)
    
    # 11. Final Output
    print(f"\n{ANSI_GREEN}" + "="*60)
    print(f" [SUCCESS] Portfolio Ledger Mutated: {os.path.basename(final_filepath)}")
    print(f" [SUCCESS] Old Ledger Archived: {old_ledger_name}")
    print(f" [SUCCESS] Sourcing Plan Saved to: {report_path}")
    print(" [SYSTEM] Execution Complete. Terminating.")
    print("="*60 + f"{ANSI_RESET}\n")

if __name__ == "__main__":
    main()