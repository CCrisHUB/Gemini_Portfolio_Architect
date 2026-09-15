#alu_utils.py
#"""
#Avenue C Deterministic ALU (Arithmetic Logic Unit)
#Date: 2026-09-16
#Version: 2.1.0 (Deep Freeze Archival Sweep Integration)
#Role: Isolates all deterministic parsing, math, and ledger mutations from the LLM.
#"""
__version__ = "2.1.0"
__date__ = "2026-09-16"

import os
import shutil
import time
import re
from datetime import datetime
import pandas as pd
import io

# ==============================================================================
# SECTION 1: CSV & INGESTION FUNCTIONS (From 01 & 02)
# ==============================================================================

def load_and_clean_csv(filepath: str) -> pd.DataFrame:
    """Loads and cleans E*TRADE CSV files, applying strict ASCII sanitization and regex bypassing."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        s_idx = next((i for i, line in enumerate(lines) if line.startswith("Symbol,") and "Quantity" in line), -1)
        if s_idx == -1: raise ValueError(f"FATAL: No header with 'Quantity' found in {filepath}")
        df = pd.read_csv(io.StringIO("".join(lines[s_idx:])), on_bad_lines='skip')
        df.columns = df.columns.str.strip()
        df = df[df['Symbol'].notna()]
        df['Symbol'] = df['Symbol'].astype(str).str.replace(r'[^\x20-\x7E]', '', regex=True).str.strip()
        df = df[~df['Symbol'].isin(['CASH', 'TOTAL', 'nan', ''])]
        for col in ['Quantity', 'Price Paid $', 'Last Price $', 'Value $', 'Total Gain $']:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col].astype(str).str.replace(r'[$,]', '', regex=True), errors='coerce').fillna(0.0)
        if 'Basis $' not in df.columns and 'Price Paid $' in df.columns and 'Quantity' in df.columns:
            df['Basis $'] = df['Price Paid $'] * df['Quantity']
        return df
    except Exception as e:
        print(f"Error loading CSV {filepath}: {e}")
        return pd.DataFrame()

def disaggregate_holdings(df_brokerage: pd.DataFrame, df_ira: pd.DataFrame) -> tuple:
    """Separates taxable and IRA holdings into dictionaries, destroying fractional math dust."""
    taxable, ira = {}, {}
    if not df_ira.empty and 'Symbol' in df_ira.columns:
        for _, r in df_ira.iterrows(): ira[r['Symbol']] = r.to_dict()
    if not df_brokerage.empty and 'Symbol' in df_brokerage.columns:
        for _, r in df_brokerage.iterrows():
            sym = r['Symbol']
            b_qty = float(r.get('Quantity', 0.0))
            if sym in ira:
                i_qty = float(ira[sym].get('Quantity', 0.0))
                net_qty = b_qty - i_qty
                if net_qty > 0.0001:
                    ratio = net_qty / b_qty
                    t_row = r.to_dict()
                    t_row['Quantity'] = net_qty
                    t_row['Value $'] = float(r.get('Value $', 0.0)) * ratio
                    t_row['Basis $'] = float(r.get('Basis $', 0.0)) * ratio
                    t_row['Total Gain $'] = float(r.get('Total Gain $', 0.0)) * ratio
                    taxable[sym] = t_row
            elif b_qty > 0.0001: taxable[sym] = r.to_dict()
    return taxable, ira

def get_safe_proxies(ticker: str, active_symbols: list, lockouts: dict) -> list:
    """Returns safe TLH proxies avoiding wash sales."""
    # Generic fallback map - replace with your actual proxy map
    proxy_map = {
        'VOO': ['IVV', 'SPLG', 'SCHX'],
        'SCHG': ['VUG', 'QQQM', 'IWF'],
        'SCHD': ['VYM', 'VIG', 'DGRO'],
        'AVUV': ['VBR', 'SLYV', 'IJS'],
        'VXUS': ['IXUS', 'VEA', 'IEFA']
    }
    candidates = proxy_map.get(ticker, [])
    safe = [p for p in candidates if p not in active_symbols and p not in lockouts]
    return safe

# ==============================================================================
# SECTION 2: TREND, PACING & AFFORDABILITY FUNCTIONS (From 03 & 04)
# ==============================================================================
def extract_constants_data(constants_text: str) -> dict:
    """Extracts tax limits, pacing parameters, and statistical thresholds."""
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

def extract_trend_metrics(ledger_text: str) -> dict:
    """Parses the ledger specifically for macro trend and pacing variance data."""
    data = {
        'market_status': 'UNKNOWN',
        'total_executed_equities': 0.0,
        'pacing_variance_value': 0.0,
        'milestones': []
    }
    
    match_status = re.search(r'Active Market Status Designation:\s*\[(.*?)\]', ledger_text)
    if match_status: data['market_status'] = match_status.group(1).strip()
        
    match_executed = re.search(r'Total Executed Holdings Market Value.*?\:\s*\$?([\d,]+\.\d{2})', ledger_text)
    if match_executed: data['total_executed_equities'] = float(match_executed.group(1).replace(',', ''))
        
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
    
    if not ledger_data['milestones']: return yield_data
        
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

def calculate_liquidity_gate(requested_spend: float, variance: float) -> dict:
    """Evaluates if the requested spend fits within the current pacing surplus."""
    available_budget = variance if variance > 0 else 0.0
    is_sufficient = requested_spend <= available_budget
    return {'available_budget': available_budget, 'is_sufficient': is_sufficient}

def extract_proxy_yield_from_text(benchmark_text: str) -> float:
    """Extracts the percentage float from the LLM's macro benchmark search text."""
    match = re.search(r'([+-]?\d+\.\d+)%', benchmark_text)
    if match: return float(match.group(1))
    return 0.0

def evaluate_decision_matrix(requested: float, budget: float, market_status: str, portfolio_yield: float, benchmark: float) -> str:
    """Executes the strict algorithmic evaluation of the spending request."""
    status_upper = market_status.upper()
    if requested > budget:
        return "REJECT. You do not have the YTD liquidity to support this purchase without cannibalizing future mandatory fixed liabilities."
    if "RED ACTIVATED" in status_upper or portfolio_yield < -15.0:
        return "REJECT. Discretionary spending is frozen. Capital preservation protocols are active to protect the cash bridge."
    if "NORMAL" in status_upper or "NEUTRAL" in status_upper or "SIDEWAYS" in status_upper:
        if portfolio_yield < 0.0 or portfolio_yield < (benchmark - 1.50):
            return "CAUTION & REDUCE. You have the baseline budget, but your portfolio is experiencing systemic drag or nominal losses. Recommend downgrading the purchase cost by 30% to 50% or postponing."
    if "NORMAL" in status_upper or "NEUTRAL" in status_upper or "SIDEWAYS" in status_upper:
        if portfolio_yield >= 0.0 and portfolio_yield >= (benchmark - 1.50):
            return "APPROVED. Liquidity is secured, pending liabilities are funded, and the portfolio is operating at optimal efficiency."
    return "PENDING. Manual review required due to ambiguous market status designation in the Portfolio Ledger."

# ==============================================================================
# SECTION 3: SOURCING & LIQUIDATION FUNCTIONS (From 05 & 06)
# ==============================================================================
def extract_bucket_1_cash(ledger_text: str) -> float:
    """Extracts the Operational Cash balance from Bucket 1."""
    match = re.search(r'\*\s*Operational Cash \(E\*TRADE Savings \.\.\.1600\):\s*\$?([\d,\.]+)', ledger_text)
    if match: return float(match.group(1).replace(',', ''))
    return 0.0

def extract_ledger_portfolio(ledger_text: str) -> dict:
    """Parses the Portfolio Ledger to build a structured dictionary of all holdings."""
    portfolio = {}
    bucket_blocks = re.findall(r'(\[BUCKET (\d)\].*?)(?=\n\[BUCKET|\n={80}|\Z)', ledger_text, re.DOTALL)
    for block_text, b_num in bucket_blocks:
        b_idx = int(b_num)
        portfolio[b_idx] = {'account': 'UNKNOWN', 'holdings': {}}
        acct_match = re.search(r'-\s*Account:\s*(\.\.\.\d{4})', block_text)
        if acct_match: portfolio[b_idx]['account'] = acct_match.group(1)
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

def update_ledger_text(ledger_text: str, liquidations: list, total_withdrawal: float, total_tax_impact: float, cash_withdrawal: float = 0.0) -> tuple:
    """Pure function: Mutates the ledger string for both Cash and Equity deductions."""
    new_text = ledger_text
    
    # 0. Update Bucket 1 Cash (If Applicable)
    if cash_withdrawal > 0:
        b1_match = re.search(r'(\*\s*Operational Cash \(E\*TRADE Savings \.\.\.1600\):\s*\$?)([\d,\.]+)', new_text)
        if b1_match:
            prefix = b1_match.group(1)
            old_cash = float(b1_match.group(2).replace(',', ''))
            new_cash = old_cash - cash_withdrawal
            new_text = new_text.replace(b1_match.group(0), f"{prefix}{new_cash:,.2f}")
            
        sub_match = re.search(r'(- Subtotal E\*TRADE Bucket 1 Capital:\s*\$?)([\d,\.]+)', new_text)
        if sub_match:
            prefix = sub_match.group(1)
            old_sub = float(sub_match.group(2).replace(',', ''))
            new_sub = old_sub - cash_withdrawal
            new_text = new_text.replace(sub_match.group(0), f"{prefix}{new_sub:,.2f}")
            
        tot_match = re.search(r'(- Total Bucket 1 Liquidity:\s*\$?)([\d,\.]+)', new_text)
        if tot_match:
            prefix = tot_match.group(1)
            old_tot = float(tot_match.group(2).replace(',', ''))
            new_tot = old_tot - cash_withdrawal
            new_text = new_text.replace(tot_match.group(0), f"{prefix}{new_tot:,.2f}")

    # 1. Update Equity Holdings
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

    # 2. Update Specific Bucket Subtotals (Equities)
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

    equity_withdrawal = total_withdrawal - cash_withdrawal
    new_text = deduct_macro(r'(Total Executed Holdings Market Value \(Buckets 2–8\):\s*)\$?([\d,\.]+)', new_text, equity_withdrawal)
    new_text = deduct_macro(r'(Subtotal E\*TRADE Platform Assets:\s*)\$?([\d,\.]+)', new_text, total_withdrawal)
    new_text = deduct_macro(r'(COMBINED TOTAL SYSTEM CAPITAL:\s*)\$?([\d,\.]+)', new_text, total_withdrawal)

    return new_text, new_variance, new_headroom

# ==============================================================================
# SECTION 4: ARCHIVAL & DEEP FREEZE OPERATIONS
# ==============================================================================
def execute_deep_freeze_sweep(archive_dir: str, deep_archive_dir: str) -> list:
    """
    Pure function: Sweeps an archive directory and moves files older than 30 days 
    to the deep archive directory.
    """
    moved_files = []
    if not os.path.exists(archive_dir):
        return moved_files
        
    os.makedirs(deep_archive_dir, exist_ok=True)
    
    current_time = time.time()
    thirty_days_in_seconds = 30 * 24 * 60 * 60
    
    for filename in os.listdir(archive_dir):
        filepath = os.path.join(archive_dir, filename)
        if os.path.isfile(filepath):
            file_mtime = os.path.getmtime(filepath)
            if (current_time - file_mtime) > thirty_days_in_seconds:
                dest_path = os.path.join(deep_archive_dir, filename)
                if os.path.exists(dest_path):
                    os.remove(dest_path)
                shutil.move(filepath, dest_path)
                moved_files.append(filename)
                
    return moved_files