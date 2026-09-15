#run_tests.py
import os
import shutil
import importlib
from datetime import datetime

# Dynamically import the module
engine = importlib.import_module("01_ingestion_engine")

MOCK_VXUS_CSV = """Account Summary
Account,Net Account Value,Total Gain $,Total Gain %,Day's Gain Unrealized $,Day's Gain Unrealized %,Day's Gain Realized $,Available For Withdrawal,Cash Purchasing Power
"Individual Brokerage -2641",146777.72,-1870.80,-1.26,-611.88,-.42,-1495.43,.00,8.28

SEARCH CRITERIA
Account,Start Date,End  Date,Symbol,Security Type,Covered,Term
"Individual Brokerage -2641",01/01/2026,09/15/2026,All,Stocks  Options  Mutual Funds  Bonds  ETFs  ,All,All,


TAXABLE G&L SUMMARY
Total Gain Realized,Short-Term Gain Realized,Long-Term Gain Realized,Deferred Loss,Total Commissions & Fees
-1495.43,-1495.43,.00,.00,1.12,
TAXABLE G&L DETAILS
Symbol,Quantity,Date,Cost/Share $,Total Cost $,Date,Price/Share $,Proceeds $,Gain $,Deferred Loss $,Term,Lot Selection
VXUS,567.099,--,--,49981.27,--,--,48485.844479475,-1495.43,--,Short,--
    Sell,567,08/17/2026,88.13,49972.54,09/15/2026,85.50,48477.380175,-1495.16,--,Short,FIFO,
    Sell,0.099,08/17/2026,88.13,8.73,09/15/2026,85.50,8.464304475,-.26,--,Short,FIFO,
Total,,,,49981.27,,,48485.84,-1495.43,.00,
Generated at Sep 15 2026 11:25 AM ET"""

MOCK_SCHG_CSV = """Account Summary
Account,Net Account Value,Total Gain $,Total Gain %,Day's Gain Unrealized $,Day's Gain Unrealized %,Day's Gain Realized $,Available For Withdrawal,Cash Purchasing Power
"Individual Brokerage -0331",468675.43,32649.09,7.49,-1351.10,-.29,-3418.11,.00,57.92

SEARCH CRITERIA
Account,Start Date,End  Date,Symbol,Security Type,Covered,Term
"Individual Brokerage -0331",01/01/2026,09/15/2026,All,Stocks  Options  Mutual Funds  Bonds  ETFs  ,All,All,


TAXABLE G&L SUMMARY
Total Gain Realized,Short-Term Gain Realized,Long-Term Gain Realized,Deferred Loss,Total Commissions & Fees
-4491.24,-4491.24,.00,.00,7.47,
TAXABLE G&L DETAILS
Symbol,Quantity,Date,Cost/Share $,Total Cost $,Date,Price/Share $,Proceeds $,Gain $,Deferred Loss $,Term,Lot Selection
SCHG,5885,--,--,209535.42,--,--,206117.316955,-3418.11,--,Short,--
    Sell,5885,08/17/2026,35.60,209535.42,09/15/2026,35.02,206117.316955,-3418.11,--,Short,FIFO,
VOO,140.478,--,--,99977.42,--,--,98904.289975508,-1073.13,--,Short,--
    Sell,70.126,08/05/2026,712.00,49929.71,08/31/2026,704.06,49372.589962164,-557.12,.00,Short,FIFO,
    Sell,70.352,08/10/2026,711.39,50047.71,08/31/2026,704.06,49531.700013344,-516.01,.00,Short,FIFO,
Total,,,,309512.84,,,305021.61,-4491.24,.00,
Generated at Sep 15 2026 11:26 AM ET"""

MOCK_LEDGER = """================================================================================
PORTFOLIO ALLOCATION LEDGER & BUCKET STRUCTURE
Date: 2026-09-15 (Version 47)
Framework Structure: 8 Macro Asset Buckets (Single Account Architecture)
Active Market Status Designation: [NEUTRAL / SIDEWAYS]
Reconciliation Source: Dual-CSV Ingestion (All Accounts + Account ...5669)
================================================================================

PERSISTENT YTD TAX LEDGER (TAX YEAR 2026)
--------------------------------------------------------------------------------
0% LTCG Tax Headroom Baseline (Single Filer):         $49,450.00
Federal Standard Deduction (2026):                     $16,100.00
Maximum Gross Taxable Income for 0% LTCG Bracket:     $65,550.00

Realized Tax Event Log:
  - 2026-08-14 | Legacy Brokerage (...9739) Liquidation
    * Gross Realized Capital Gains:                    +$17,317.41
    * Harvested Capital Losses:                         -$2,585.01
    * Net Realized LTCG:                               +$14,732.40
  - 2026-08-28 | Individual Brokerage (...2008) Liquidation
    * Net Realized STCG (JEPQ):                           +$273.19
  - 2026-08-31 | Individual Brokerage (...0331 & ...7851) Liquidation
    * Net Realized STCG (VOO, VB, VO):                 -$4,055.66

  - 2026-09-11 | Realized Gains Ingestion (VIG_2026_09_11)
    * Net Realized STCG: $-1,981.81

YTD Cumulative Tax Summary:
  - Ordinary Income YTD (Pension / Social Security):       $0.00
  - Realized Short-Term Capital Gains YTD:              -$5,764.28
  - Realized Long-Term Capital Gains (LTCG) YTD:      +$14,732.40
  - Starting 0% LTCG Headroom:                        $49,450.00
  - Remaining 0% LTCG Headroom:                       $34,717.60

30-DAY WASH-SALE LOCKOUT TRACKER:
  - VB | Date Sold: 2026-09-01 | Lockout Expiry: 2026-10-01
  - VO | Date Sold: 2026-09-01 | Lockout Expiry: 2026-10-01
  - VOO | Date Sold: 2026-09-01 | Lockout Expiry: 2026-10-01

--------------------------------------------------------------------------------

DATE-AWARE SPENDING PACING ENGINE & LIABILITY FORECAST
--------------------------------------------------------------------------------
Current Date: 2026-09-15
Annual Target Net Drawdown Gap: $71,618.55

  - Total A (Paced YTD Target):                   $50,623.52
  - Total B (Actual YTD Drawdown):                     $0.00
  - Pacing Variance (Gross):                     +$50,623.52 (Under paced target)
  
  - Pending Fixed Liabilities (YTD Remaining):    $27,583.99
  - Net Adjusted Pacing Variance:                +$23,039.53 (Surplus)

--------------------------------------------------------------------------------

[BUCKET 1] LIQUIDITY & PRESERVATION
  - Identity: Short-Term Liquidity, Safety, & Risk Insulation Buffer
  - Holdings Breakdown:
      * Operational Cash (E*TRADE Savings ...1600):    $97,667.41 [In E*TRADE]
  - Subtotal E*TRADE Bucket 1 Capital:               $497,667.41
  - Subtotal External Bucket 1 Capital:              $100,000.00
  - Total Bucket 1 Liquidity:                        $597,667.41
  - Status: ACTIVE / RECONCILED

--------------------------------------------------------------------------------

[BUCKET 2] U.S. LARGE-CAP CORE & GROWTH
  - Account: ...0331
  - Holdings (CSV Reconciled):
      * GSLC : 1039.0000 shares
  - Account Value (Executed Equities): $471,333.98
  - Status: ACTIVE / RECONCILED

--------------------------------------------------------------------------------

[BUCKET 6] TRADITIONAL IRA (TAX-SHELTERED CORE)
  - Account: ...5669
  - Holdings (CSV Reconciled):
      * SCHD : 1072.0000 shares
  - Account Value (Executed Equities): $75,315.47
  - Status: ACTIVE / RECONCILED

--------------------------------------------------------------------------------
================================================================================
ROLLING HISTORICAL MILESTONE LEDGER (TRAILING 8 QUARTERS)
--------------------------------------------------------------------------------
[Date | Total Capital | Executed Equities | Cash/CD Bridge | YTD Drawdown | Market Status]
[2026-09-15 | $1,718,845.17 | $1,120,481.51 | $598,363.66 | $0.00 | NEUTRAL / SIDEWAYS]
================================================================================
"""

def setup_test_env():
    print("Setting up self-contained test environment...")
    os.makedirs("test_env/00_CORE_Files", exist_ok=True)
    os.makedirs("test_env/20_CSV_Downloads_Current", exist_ok=True)
    
    with open("test_env/20_CSV_Downloads_Current/RealizedGains_VXUS.csv", "w", encoding="utf-8") as f:
        f.write(MOCK_VXUS_CSV)
        
    with open("test_env/20_CSV_Downloads_Current/RealizedGains_SCHG.csv", "w", encoding="utf-8") as f:
        f.write(MOCK_SCHG_CSV)
        
    with open("test_env/00_CORE_Files/GEM_Retirement_Portfolio_Ledger_2026-09-15_v47.txt", "w", encoding="utf-8") as f:
        f.write(MOCK_LEDGER)

def run_tax_parsing_test():
    print("\n--- RUNNING TAX PARSING INTEGRATION TEST ---")
    
    prev_state = engine.parse_previous_ledger("test_env/00_CORE_Files")
    original_tax_ledger = prev_state['tax_ledger']
    
    print("\n[BASELINE STCG]: -$5,764.28 (Expected from v47)")
    
    gains_files = [
        "test_env/20_CSV_Downloads_Current/RealizedGains_VXUS.csv",
        "test_env/20_CSV_Downloads_Current/RealizedGains_SCHG.csv"
    ]
    sold_tickers = {'VXUS', 'SCHG'}
    
    routing_data = {
        'std_deduction': 16100.0,
        'ltcg_limit': 49450.0
    }
    
    print("\nExecuting process_tax_and_wash_sales()...")
    updated_tax_ledger = engine.process_tax_and_wash_sales(
        original_tax_ledger, 
        gains_files, 
        sold_tickers, 
        routing_data, 
        prev_state
    )
    
    print("\n" + "="*80)
    print("MUTATED TAX LEDGER OUTPUT:")
    print("="*80)
    print(updated_tax_ledger)
    print("="*80)
    
    print("\n[VERIFICATION CHECKLIST]")
    print("1. Does 'Realized Short-Term Capital Gains YTD' equal -$10,677.82?")
    print("2. Are VXUS and SCHG added to the 30-DAY WASH-SALE LOCKOUT TRACKER?")
    print("3. Are the two new events logged under 'Realized Tax Event Log'?")

def cleanup():
    print("\nCleaning up test environment...")
    shutil.rmtree("test_env")

if __name__ == "__main__":
    try:
        setup_test_env()
        run_tax_parsing_test()
    finally:
        cleanup()