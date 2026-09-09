import pandas as pd
import os

def find_header_row(filepath):
    """
    Dynamically seeks the actual CSV header row, bypassing E*TRADE metadata blocks.
    Looks for the standard E*TRADE column identifiers.
    """
    with open(filepath, 'r', encoding='utf-8') as f:
        for i, line in enumerate(f):
            # E*TRADE data tables typically begin with a row containing 'Symbol'
            if 'Symbol' in line and ('Quantity' in line or 'Value' in line or 'Last Price' in line):
                return i
    return 0 # Fallback to 0 if not found

def test_parsing(file_path, name):
    if not os.path.exists(file_path):
        print(f"[FATAL ERROR] File not found: {file_path}")
        return None
        
    header_idx = find_header_row(file_path)
    print(f"--- {name} ---")
    print(f"Target File: {file_path}")
    print(f"Detected Header at Row Index: {header_idx}")
    
    # Read CSV skipping the metadata rows and bypassing malformed footer rows
    try:
        # on_bad_lines='skip' ensures that E*TRADE's summary footers don't crash the parser.
        # It dynamically reads all valid holding rows, whether there are 10 or 10,000.
        df = pd.read_csv(file_path, skiprows=header_idx, skip_blank_lines=True, on_bad_lines='skip')
        
        # Anti-GIGO: Strip trailing whitespace and invisible characters from column names
        df.columns = df.columns.str.strip().str.replace(r'[^\x20-\x7E]', '', regex=True)
        
        print(f"Total Rows Parsed: {len(df)}")
        print(f"Columns Detected: {list(df.columns)}\n")
        return df
    except Exception as e:
        print(f"[FATAL ERROR] Pandas failed to parse {name}: {e}\n")
        return None

if __name__ == "__main__":
    print("=== E*TRADE CSV PARSING DIAGNOSTIC ===\n")
    
    # Adjust paths if your data folder is named differently
    path_all = os.path.join("data", "PortfolioDownload_AllAccounts.csv")
    path_5669 = os.path.join("data", "PortfolioDownload_5669.csv")
    
    df_all = test_parsing(path_all, "ALL ACCOUNTS CSV")
    df_5669 = test_parsing(path_5669, "ACCOUNT 5669 CSV")
    
    if df_all is not None and df_5669 is not None:
        print("=== PARSING TEST COMPLETE ===")
        print("If the columns look correct, we are ready for Phase 3.")