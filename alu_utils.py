#alu_utils.py
#"""
#Avenue C Arithmetic Logic Unit (ALU) Utilities
#Date: 2026-09-12
#Version: 1.2.0 (Deterministic TLH Proxy Mapping)
#Role: Shared deterministic math and CSV parsing functions.
#"""
__version__ = "1.2.0"
__date__ = "2026-09-12"

import pandas as pd
import numpy as np
import os
import io

# ==============================================================================
# DETERMINISTIC TLH PROXY MAP (IRS WASH-SALE COMPLIANT)
# ==============================================================================
TLH_PROXY_MAP = {
    'VOO': ['VTI', 'SCHX', 'VV'],
    'SCHX': ['VOO', 'VTI', 'VV'],
    'SCHD': ['VYM', 'HDV', 'FDVV'],
    'SCHG': ['VUG', 'QQQ', 'IWF'],
    'AVUV': ['VBR', 'IJS', 'SLYV'],
    'VXUS': ['IXUS', 'VEU', 'SPDW'],
    'VIG': ['DGRO', 'VDIGX', 'SCHD'],
    'DGRO': ['VIG', 'SCHD', 'VDIGX'],
    'QUAL': ['SPHQ', 'JQUA', 'XLG'],
    'GSLC': ['USMV', 'SPLV', 'SPY'],
    'MAIN': ['ARCC', 'OBDC', 'FSK'],
    'O': ['VNQ', 'SCHH', 'XLRE'],
    'SCHA': ['VB', 'IJR', 'SPSM'],
    'SCHM': ['VO', 'IWR', 'MDY'],
    'AVDV': ['ISCF', 'SCHC', 'GWX'],
    'EMXC': ['VWO', 'IEMG', 'EEM'],
    'VIGI': ['VYMI', 'SCHY', 'IDV'],
    'USFR': ['SGOV', 'BIL', 'SHV']
}

def get_safe_proxies(ticker, active_symbols, lockouts):
    """Returns a list of pre-vetted proxies that do not violate wash-sale or overlap rules."""
    candidates = TLH_PROXY_MAP.get(ticker, [])
    safe = [c for c in candidates if c not in active_symbols and c not in lockouts]
    return safe

# ==============================================================================
# CSV PARSING & DISAGGREGATION
# ==============================================================================
def load_and_clean_csv(filepath):
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"FATAL: Missing required file: {filepath}")
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
    required_cols = ['Symbol', 'Quantity', 'Last Price $', 'Value $', 'Price Paid $', 'Total Gain $']
    for col in required_cols:
        if col not in df_all.columns or col not in df_ira.columns:
            raise ValueError(f"FATAL: Missing required column '{col}' in CSVs.")

    df_all = df_all.copy()
    df_ira = df_ira.copy()
    
    df_all['Symbol'] = df_all['Symbol'].astype(str).str.strip()
    df_ira['Symbol'] = df_ira['Symbol'].astype(str).str.strip()

    for col in ['Quantity', 'Last Price $', 'Value $', 'Price Paid $', 'Total Gain $']:
        df_all[col] = pd.to_numeric(df_all[col].astype(str).str.replace(r'[$,]', '', regex=True), errors='coerce').fillna(0)
        df_ira[col] = pd.to_numeric(df_ira[col].astype(str).str.replace(r'[$,]', '', regex=True), errors='coerce').fillna(0)

    def filter_garbage(df):
        mask = (
            ~df['Symbol'].str.lower().isin(['cash', 'total', 'nan', '']) & 
            ~df['Symbol'].str.lower().str.contains('generated') & 
            (df['Symbol'].str.len() <= 10)
        )
        return df[mask].set_index('Symbol')

    df_all_clean = filter_garbage(df_all)
    df_ira_clean = filter_garbage(df_ira)

    df_all_clean['Basis $'] = df_all_clean['Value $'] - df_all_clean['Total Gain $']
    df_ira_clean['Basis $'] = df_ira_clean['Value $'] - df_ira_clean['Total Gain $']

    merged = df_all_clean.join(df_ira_clean, how='left', lsuffix='_all', rsuffix='_ira')
    
    for col in ['Quantity_ira', 'Value $_ira', 'Total Gain $_ira', 'Basis $_ira']:
        merged[col] = merged[col].fillna(0)

    merged['Quantity_tax'] = merged['Quantity_all'] - merged['Quantity_ira']
    merged['Basis $_tax'] = merged['Basis $_all'] - merged['Basis $_ira']

    master_price = merged['Last Price $_all']
    
    merged['Sync_Value_ira'] = merged['Quantity_ira'] * master_price
    merged['Sync_Gain_ira'] = merged['Sync_Value_ira'] - merged['Basis $_ira']
    merged['Sync_Price_Paid_ira'] = np.where(merged['Quantity_ira'] > 0, merged['Basis $_ira'] / merged['Quantity_ira'], 0.0)
    
    merged['Sync_Value_tax'] = merged['Quantity_tax'] * master_price
    merged['Sync_Gain_tax'] = merged['Sync_Value_tax'] - merged['Basis $_tax']
    merged['Sync_Price_Paid_tax'] = np.where(merged['Quantity_tax'] > 0, merged['Basis $_tax'] / merged['Quantity_tax'], 0.0)

    taxable_holdings = {}
    clean_ira_holdings = {}

    for sym, row in merged.iterrows():
        acq_date_all = row['Date Acquired_all'] if 'Date Acquired_all' in row and pd.notna(row['Date Acquired_all']) else 'Various'
        acq_date_ira = row['Date Acquired_ira'] if 'Date Acquired_ira' in row and pd.notna(row['Date Acquired_ira']) else 'Various'

        if row['Quantity_ira'] > 0:
            clean_ira_holdings[sym] = {
                'Quantity': round(row['Quantity_ira'], 4),
                'Last Price $': row['Last Price $_all'],
                'Value $': round(row['Sync_Value_ira'], 2),
                'Price Paid $': round(row['Sync_Price_Paid_ira'], 4),
                'Total Gain $': round(row['Sync_Gain_ira'], 2),
                'Basis $': round(row['Basis $_ira'], 2),
                'Date Acquired': acq_date_ira
            }
        
        if row['Quantity_tax'] > 0.001:
            if row['Quantity_ira'] == 0:
                taxable_holdings[sym] = {
                    'Quantity': row['Quantity_all'],
                    'Last Price $': row['Last Price $_all'],
                    'Value $': row['Value $_all'],
                    'Price Paid $': row['Price Paid $_all'],
                    'Total Gain $': row['Total Gain $_all'],
                    'Basis $': round(row['Basis $_all'], 2),
                    'Date Acquired': acq_date_all
                }
            else:
                taxable_holdings[sym] = {
                    'Quantity': round(row['Quantity_tax'], 4),
                    'Last Price $': row['Last Price $_all'],
                    'Value $': round(row['Sync_Value_tax'], 2),
                    'Price Paid $': round(row['Sync_Price_Paid_tax'], 4),
                    'Total Gain $': round(row['Sync_Gain_tax'], 2),
                    'Basis $': round(row['Basis $_tax'], 2),
                    'Date Acquired': acq_date_all
                }

    ira_only = df_ira_clean[~df_ira_clean.index.isin(df_all_clean.index)]
    for sym, row in ira_only.iterrows():
        acq_date = row['Date Acquired'] if 'Date Acquired' in row and pd.notna(row['Date Acquired']) else 'Various'
        clean_ira_holdings[sym] = {
            'Quantity': row['Quantity'],
            'Last Price $': row['Last Price $'],
            'Value $': row['Value $'],
            'Price Paid $': row['Price Paid $'],
            'Total Gain $': row['Total Gain $'],
            'Basis $': round(row['Basis $'], 2),
            'Date Acquired': acq_date
        }

    return taxable_holdings, clean_ira_holdings