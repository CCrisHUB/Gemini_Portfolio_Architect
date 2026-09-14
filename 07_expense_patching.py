#07_expense_patching.py
#"""
#Expense Payload Patching Engine
#Date: 2026-09-11
#Version: 1.1.0 (Decoupled Config & Centralized Archive Sweep)
#Role: Injects the Financial Ingestion Payload into Core File 1.
#"""
__version__ = "1.1.0"
__date__ = "2026-09-11"

import os
import sys
import glob
import re
import shutil
from datetime import datetime
from alu_utils import (
    DIR_CORE_ACTIVE, DIR_CORE_ARCHIVE,
    DIR_CSV_ACTIVE, DIR_CSV_ARCHIVE,
    DEEP_ARCHIVE_CORE, DEEP_ARCHIVE_CSV,
    deep_archive_sweep
)

# ==============================================================================
# ANSI UX FORMATTING CONSTANTS
# ==============================================================================
ANSI_RED = "\033[91m"
ANSI_GREEN = "\033[92m"
ANSI_YELLOW = "\033[93m"
ANSI_CYAN = "\033[96m"
ANSI_RESET = "\033[0m"

# ==============================================================================
# DIRECTORY INITIALIZATION
# ==============================================================================
for directory in [DIR_CORE_ACTIVE, DIR_CORE_ARCHIVE, DIR_CSV_ACTIVE, DIR_CSV_ARCHIVE]:
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

# ==============================================================================
# MAIN ORCHESTRATOR
# ==============================================================================
def main():
    print(f"{ANSI_CYAN}" + "="*60)
    print(" AVENUE C: EXPENSE PAYLOAD PATCHING ENGINE")
    print("="*60 + f"{ANSI_RESET}")
    
    # 1. Locate Files
    print(f"\n{ANSI_CYAN}[System] Locating Core File 1 and Ingestion Payload...{ANSI_RESET}")
    try:
        constants_file = get_latest_file(DIR_CORE_ACTIVE, "GEM_Retirement_Master_Profile_Constants_*.txt")
        print(f"{ANSI_GREEN}✅ Detected Core File 1: {os.path.basename(constants_file)}{ANSI_RESET}")
    except FileNotFoundError as e:
        print(f"{ANSI_RED}[FATAL ERROR] {e}{ANSI_RESET}")
        sys.exit(1)

    while True:
        try:
            payload_file = get_latest_file(DIR_CSV_ACTIVE, "Ingestion_Expense_Payload_FINAL_*.txt")
            print(f"{ANSI_GREEN}✅ Detected Payload: {os.path.basename(payload_file)}{ANSI_RESET}")
            break
        except FileNotFoundError:
            print(f"\n{ANSI_RED}❌ ERROR: Missing 'Ingestion_Expense_Payload_FINAL_*.txt' in '{DIR_CSV_ACTIVE}'.{ANSI_RESET}")
            retry = input(f"{ANSI_CYAN}Place the file in the folder and press ENTER to retry (or type 'exit'): {ANSI_RESET}").strip()
            if retry.lower() == 'exit': sys.exit(0)

    # 2. Read Content
    constants_text = load_file_content(constants_file)
    payload_text = load_file_content(payload_file).strip()
    
    # 3. Bounding Box Injection
    print(f"\n{ANSI_CYAN}[System] Executing Bounding Box Injection...{ANSI_RESET}")
    
    start_marker = r'# \[START COPY HERE\]'
    end_marker = r'# \[END COPY HERE\]'
    
    # Check if markers exist
    if not re.search(start_marker, constants_text) or not re.search(end_marker, constants_text):
        print(f"{ANSI_RED}[FATAL ERROR] Bounding tags missing from Core File 1. Patching aborted.{ANSI_RESET}")
        sys.exit(1)
        
    # Execute Regex Substitution
    pattern = rf'({start_marker}).*?({end_marker})'
    replacement = rf'\1\n\n{payload_text}\n\n\2'
    new_constants_text = re.sub(pattern, replacement, constants_text, flags=re.DOTALL)
    
    # 4. Version Increment & Date Update
    match = re.search(r'_v(\d+)\.txt', os.path.basename(constants_file))
    old_version = int(match.group(1)) if match else 0
    new_version = old_version + 1
    today = datetime.now().strftime("%Y-%m-%d")
    
    # Update Header Dates and Versions
    new_constants_text = re.sub(r'Date: \d{4}-\d{2}-\d{2} \(Version \d+\)', f'Date: {today} (Version {new_version})', new_constants_text)
    new_constants_text = re.sub(r'GEM_Retirement_Master_Profile_Constants_\d{4}-\d{2}-\d{2}_v\d+\.txt', f'GEM_Retirement_Master_Profile_Constants_{today}_v{new_version}.txt', new_constants_text)
    
    # 5. Save New File
    final_filename = f"GEM_Retirement_Master_Profile_Constants_{today}_v{new_version}.txt"
    final_filepath = os.path.join(DIR_CORE_ACTIVE, final_filename)
    
    with open(final_filepath, "w", encoding="utf-8") as f:
        f.write(new_constants_text)
        
    # 6. Clean Room Archiving
    old_constants_name = os.path.basename(constants_file)
    shutil.move(constants_file, os.path.join(DIR_CORE_ARCHIVE, old_constants_name))
    
    # Move the payload to the old CSV folder to keep the active directory clean
    shutil.move(payload_file, os.path.join(DIR_CSV_ARCHIVE, os.path.basename(payload_file)))
    
    # 7. Deep Archive Sweep
    print(f"\n{ANSI_CYAN}[System] Executing Deep Archive Sweep...{ANSI_RESET}")
    deep_archive_sweep(DIR_CORE_ARCHIVE, DEEP_ARCHIVE_CORE, days_old=30)
    deep_archive_sweep(DIR_CSV_ARCHIVE, DEEP_ARCHIVE_CSV, days_old=30)

    print(f"\n{ANSI_GREEN}" + "="*60)
    print(f" [SUCCESS] Payload injection successful.")
    print(f" [SUCCESS] Core File 1 Mutated: {final_filename}")
    print(f" [SUCCESS] Old Core File Archived: {old_constants_name}")
    print(" [SYSTEM] Execution Complete. Terminating.")
    print("="*60 + f"{ANSI_RESET}\n")

if __name__ == "__main__":
    main()