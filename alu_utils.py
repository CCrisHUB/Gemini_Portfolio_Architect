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

# ==============================================================================
# AVENUE C: SOURCING & LIQUIDATION ALU FUNCTIONS
# ==============================================================================
import re

def extract_constants_data(constants_text: str) -> dict:
    """Extracts tax limits, pacing parameters, and statistical thresholds from the Master Constants file."""
    data = {'ltcg_limit': 0.0, 'std_deduction': 0.0, 'annual_drawdown_gap': 0.0, 'min_statistical_days': 90}
    
    match_ltcg = re.search(r'CONST_ACTIVE_0PCT_LTCG_LIMIT:\s*\$?([\d,]+\.\d{2})', constants_text)
    if match_ltcg: data['ltcg_limit'] = float(match_ltcg.group(1).replace(',', ''))
    
    match_std = re.search(r'CONST_ACTIVE_STD_DEDUCTION:\s*\$?([\d,]+\.\d{2})', constants_text)
    if match_std: data['std_deduction'] = float(match_std.group(1).replace(',', ''))
    
    match_gap = re.search(r'CONST_TARGET_NET_DRAWDOWN_GAP:\s*\$?([\d,]+\.\d{2})', constants_text)
    if match_gap: data['annual_drawdown_gap'] = float(match_gap.group(1).replace(',', ''))
    
    match_days = re.search(r'CONST_MIN_STATISTICAL_DAYS\s*:\s*(\d+)', constants_text)
    if match_days: data['min_statistical_days'] = int(match_days.group(1))
        
    return data

def extract_ledger_portfolio(ledger_text: str) -> dict:
    """Parses the Portfolio Ledger to build a structured dictionary of all holdings."""
    portfolio = {}
    bucket_blocks = re.findall(r'(\[BUCKET (\d)\].*?)(?=\n\[BUCKET|\n={80}|\Z)', ledger_text, re.DOTALL)
    for block_text, b_num in bucket_blocks:
        b_idx = int(b_num)
        portfolio[b_idx] = {'account': 'UNKNOWN', 'holdings': {}}
        acct_match = re.search(r'-\s*Account:\s*(\.\.\.\d{4})', block_text)
        if acct_match:
            portfolio[b_idx]['account'] = acct_match.group(1)
        holding_pattern = r'\*\s+([A-Z]+)\s+:\s+([\d\.]+)\s+shares\s*\n\s*\[Price:\s*\$?([\d\.]+)\s*\|\s*Basis:\s*\$?([\d,\.]+)\s*\|\s*Value:\s*\$?([\d,\.]+)\s*\|\s*([+-]?\$?[\d,\.]+)\]'
        holdings = re.findall(holding_pattern, block_text)
        for h in holdings:
            ticker, shares, price, basis, val, gain = h
            gain_val = gain.replace('$', '').replace(',', '').replace('+', '')
            portfolio[b_idx]['holdings'][ticker] = {
                'shares': float(shares), 'price': float(price), 'basis': float(basis.replace(',', '')),
                'value': float(val.replace(',', '')), 'gain': float(gain_val), 'original_text': h
            }
    return portfolio

def select_tax_optimized_lots(portfolio: dict, target_amount: float, exemptions: list) -> list:
    """Flattens the portfolio, excludes exempt buckets, and sorts strictly by percentage loss."""
    flat_holdings = []
    for b_idx, b_data in portfolio.items():
        if b_idx not in exemptions:
            for ticker, t_data in b_data['holdings'].items():
                flat_holdings.append({
                    'ticker': ticker, 'bucket': b_idx, 'account': b_data['account'],
                    'shares': t_data['shares'], 'basis': t_data['basis'], 'value': t_data['value'],
                    'gain': t_data['gain'], 'ledger_price': t_data['price']
                })
    flat_holdings.sort(key=lambda x: (x['gain'] / x['basis']) if x['basis'] > 0 else 0)
    
    selected_lots = []
    cumulative_value = 0.0
    for lot in flat_holdings:
        if cumulative_value >= target_amount: break
        selected_lots.append(lot)
        cumulative_value += lot['value']
    return selected_lots

def get_lots_by_tickers(portfolio: dict, tickers: list, exemptions: list) -> list:
    """Fetches specific lots if the user overrides the Quant Baseline."""
    selected_lots = []
    for b_idx, b_data in portfolio.items():
        if b_idx not in exemptions:
            for ticker, t_data in b_data['holdings'].items():
                if ticker in tickers:
                    selected_lots.append({
                        'ticker': ticker, 'bucket': b_idx, 'account': b_data['account'],
                        'shares': t_data['shares'], 'basis': t_data['basis'], 'value': t_data['value'],
                        'gain': t_data['gain'], 'ledger_price': t_data['price']
                    })
    return selected_lots

def calculate_exact_liquidations(selected_lots: list, live_prices: dict, target_amount: float) -> list:
    """Calculates exact fractional shares to sell and realized tax impact."""
    liquidations = []
    remaining_target = target_amount
    for lot in selected_lots:
        if remaining_target <= 0.01: break
        ticker = lot['ticker']
        live_price = live_prices[ticker]
        lot_max_value = lot['shares'] * live_price
        
        if lot_max_value <= remaining_target:
            sell_amount = lot_max_value
            sell_shares = lot['shares']
        else:
            sell_amount = remaining_target
            sell_shares = remaining_target / live_price
            
        basis_per_share = lot['basis'] / lot['shares'] if lot['shares'] > 0 else 0
        sold_basis = sell_shares * basis_per_share
        realized_gain = sell_amount - sold_basis
        
        liquidations.append({
            'ticker': ticker, 'bucket': lot['bucket'], 'account': lot['account'],
            'sell_shares': sell_shares, 'sell_price': live_price, 'sell_amount': sell_amount,
            'realized_gain': realized_gain, 'old_shares': lot['shares'], 'old_basis': lot['basis'], 
            'old_value': lot['value'], 'old_gain': lot['gain']
        })
        remaining_target -= sell_amount
    return liquidations

def update_ledger_text(ledger_text: str, liquidations: list, total_withdrawal: float, total_tax_impact: float) -> tuple:
    """Pure function: Mutates the ledger string and returns the new text, variance, and headroom."""
    new_text = ledger_text
    
    # 1. Update Holdings
    for liq in liquidations:
        t = liq['ticker']
        new_shares = liq['old_shares'] - liq['sell_shares']
        new_basis = liq['old_basis'] - (liq['sell_shares'] * (liq['old_basis'] / liq['old_shares']))
        new_val = liq['old_value'] - liq['sell_amount']
        new_gain = liq['old_gain'] - liq['realized_gain']
        
        gain_str = f"+${new_gain:,.2f}" if new_gain >= 0 else f"-${abs(new_gain):,.2f}"
        old_pattern = rf'\*\s+{t}\s+:\s+[\d\.]+\s+shares\s*\n\s*\[Price:\s*\$?[\d\.]+\s*\|\s*Basis:\s*\$?[\d,\.]+\s*\|\s*Value:\s*\$?[\d,\.]+\s*\|\s*[+-]?\$?[\d,\.]+\]'
        
        if new_shares < 0.001:
            new_text = re.sub(old_pattern + r'\n?', '', new_text)
        else:
            new_line = f"* {t:<4} : {new_shares:.4f} shares\n        [Price: ${liq['sell_price']:.3f} | Basis: ${new_basis:,.2f} | Value: ${new_val:,.2f} | {gain_str}]"
            new_text = re.sub(old_pattern, new_line, new_text)

    # 2. Update Specific Bucket Subtotals
    bucket_deductions = {}
    for liq in liquidations:
        b = liq['bucket']
        bucket_deductions[b] = bucket_deductions.get(b, 0.0) + liq['sell_amount']
        
    for b, amount in bucket_deductions.items():
        block_match = re.search(rf'\[BUCKET {b}\].*?(?=\n\[BUCKET|\n={80}|\Z)', new_text, re.DOTALL)
        if block_match:
            block_text = block_match.group(0)
            val_match = re.search(r'(- Account Value \(Executed Equities\):\s*)\$?([\d,\.]+)', block_text)
            if val_match:
                prefix = val_match.group(1)
                old_val = float(val_match.group(2).replace(',', ''))
                new_val = old_val - amount
                new_block_text = block_text.replace(val_match.group(0), f"{prefix}${new_val:,.2f}")
                new_text = new_text.replace(block_text, new_block_text)

    # 3. Update Tax Headroom
    new_headroom = 0.0
    headroom_match = re.search(r'Remaining 0% LTCG Headroom:\s*([+-]?)\$?([\d,\.]+)', new_text)
    if headroom_match:
        sign = -1.0 if headroom_match.group(1) == '-' else 1.0
        old_headroom = float(headroom_match.group(2).replace(',', '')) * sign
        new_headroom = old_headroom - total_tax_impact 
        hr_str = f"+${new_headroom:,.2f}" if new_headroom >= 0 else f"-${abs(new_headroom):,.2f}"
        new_text = re.sub(r'(Remaining 0% LTCG Headroom:\s*)[+-]?\$?[\d,\.]+', r'\g<1>' + hr_str.replace('\\', '\\\\'), new_text)

    # 4. Update Pacing Variance
    new_variance = 0.0
    pacing_match = re.search(r'Net Adjusted Pacing Variance:\s*([+-]?)\$?([+-]?[\d,\.]+)', new_text)
    if pacing_match:
        sign = pacing_match.group(1)
        val_str = pacing_match.group(2)
        multiplier = -1.0 if val_str.startswith('-') or sign == '-' else 1.0
        old_variance = float(val_str.replace('-', '').replace('+', '').replace(',', '')) * multiplier
        new_variance = old_variance - total_withdrawal
        var_str = f"+${new_variance:,.2f}" if new_variance >= 0 else f"-${abs(new_variance):,.2f}"
        new_text = re.sub(r'(Net Adjusted Pacing Variance:\s*)[+-]?\$?[+-]?[\d,\.]+', r'\g<1>' + var_str.replace('\\', '\\\\'), new_text)

    # 5. Update Total Capital Macros 
    def deduct_macro(pattern, text, amount):
        match = re.search(pattern, text)
        if match:
            prefix = match.group(1)
            old_val = float(match.group(2).replace(',', ''))
            new_val = old_val - amount
            return re.sub(pattern, rf"{prefix}${new_val:,.2f}", text)
        return text

    new_text = deduct_macro(r'(Total Executed Holdings Market Value \(Buckets 2–8\):\s*)\$?([\d,\.]+)', new_text, total_withdrawal)
    new_text = deduct_macro(r'(Subtotal E\*TRADE Platform Assets:\s*)\$?([\d,\.]+)', new_text, total_withdrawal)
    new_text = deduct_macro(r'(COMBINED TOTAL SYSTEM CAPITAL:\s*)\$?([\d,\.]+)', new_text, total_withdrawal)

    return new_text, new_variance, new_headroom

# ==============================================================================
# AVENUE C: TREND & PACING ALU FUNCTIONS
# ==============================================================================
from datetime import datetime

def extract_trend_metrics(ledger_text: str) -> dict:
    """Parses the ledger specifically for macro trend and pacing variance data."""
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
        multiplier = -1.0 if val_str.startswith('-') or sign == '-' else 1.0
        data['pacing_variance_value'] = float(val_str.replace('-', '').replace('+', '').replace(',', '')) * multiplier

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

def calculate_temporal_yield(ledger_data: dict, min_days: int) -> dict:
    """Calculates the exact portfolio yield percentage and evaluates cold-start logic."""
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

def evaluate_spending_variance(variance: float) -> str:
    """Evaluates pacing variance and returns the strict deterministic directive."""
    if variance <= -5000.00:
        return (f"Deficit: -${abs(variance):,.2f}. "
                "DIRECTIVE (Condition 2.A): You are overspending against your YTD target and pending liabilities. "
                "Delay major discretionary purchases or expensive travel.")
    elif variance >= 5000.00:
        return (f"Surplus: +${variance:,.2f}. "
                "DIRECTIVE (Condition 2.B): You are underspending. You have a verified budget surplus "
                "and can afford to make a major discretionary purchase or book a trip.")
    else:
        status = f"+${variance:,.2f}" if variance >= 0 else f"-${abs(variance):,.2f}"
        return (f"Neutral: {status}. "
                "DIRECTIVE (Condition 2.C): Your spending is precisely on target. Keep spending at the current pace.")