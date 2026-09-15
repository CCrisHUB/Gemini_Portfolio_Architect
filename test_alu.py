#test_alu.py
#"""
#Avenue C - ALU Golden Test Harness
#Date: 2026-09-15
#Role: Unit test suite to prevent LLM Regression Entropy in alu_utils.py.
#"""
import unittest
import pandas as pd
import os
import io
import alu_utils

# ANSI Colors for terminal output
ANSI_RED = "\033[91m"
ANSI_GREEN = "\033[92m"
ANSI_RESET = "\033[0m"

class TestAvenueCALU(unittest.TestCase):

    def setUp(self):
        """Creates temporary hostile data files to test ingestion armor."""
        self.test_csv_path = "test_hostile_ingestion.csv"
        
        # Simulated E*TRADE Dual-Header with \ufeff BOM, Zero-Width Space (\u200b), and null rows
        hostile_csv_content = """View Summary - All Positions
Filters applied: 
Symbol,Security type(s),Sort by,Sort order,
,All,Symbol,Asc,

Symbol,Last Price $,Change $,Change %,Quantity,Price Paid $,Day's Gain $,Total Gain $,Total Gain %,Value $
\ufeffVIG  ,238.58,-0.85,-0.36,161.3840,246.3694,-137.1800,-1257.0900,-3.1617,38502.9947
\u200bAVUV,124.02,-0.48,-0.39,277.4470,126.12,-133.1700,-582.6400,-1.6651,34408.9769
CASH,,,,,,,,,690.22,
TOTAL,,,,,1096162.19,-2568.66,24319.32,2.22,1121171.73,
"""
        with open(self.test_csv_path, 'w', encoding='utf-8') as f:
            f.write(hostile_csv_content)

    def tearDown(self):
        """Cleans up temporary files."""
        if os.path.exists(self.test_csv_path):
            os.remove(self.test_csv_path)

    def test_01_csv_metadata_bypass_and_ascii_vaporizer(self):
        """Tests that load_and_clean_csv skips E*TRADE metadata and vaporizes Unicode."""
        df = alu_utils.load_and_clean_csv(self.test_csv_path)
        
        # 1. Ensure it didn't crash on the first header
        self.assertIn('Quantity', df.columns, "Failed to bypass metadata filter block.")
        
        # 2. Ensure CASH and TOTAL were dropped
        symbols = df['Symbol'].tolist()
        self.assertNotIn('CASH', symbols, "Failed to filter CASH row.")
        self.assertNotIn('TOTAL', symbols, "Failed to filter TOTAL row.")
        
        # 3. Ensure ASCII Vaporizer worked (No BOM \ufeff or \u200b, stripped spaces)
        self.assertIn('VIG', symbols, "ASCII Vaporizer failed to clean VIG.")
        self.assertIn('AVUV', symbols, "ASCII Vaporizer failed to clean AVUV.")

    def test_02_floating_point_dust_vaporization(self):
        """Tests that disaggregate_holdings ignores fractional 1e-14 differences."""
        # Create DataFrames with mathematically identical but floating-point sensitive data
        df_brok = pd.DataFrame({
            'Symbol': ['VIG', 'SCHD'],
            'Quantity': [161.3840, 2000.0000],
            'Value $': [38502.99, 68000.00]
        })
        
        df_ira = pd.DataFrame({
            'Symbol': ['VIG', 'SCHD'],
            # Simulating microscopic floating point drift (e.g. 161.3840 - 161.3839999999)
            'Quantity': [161.38399999999, 1000.0000] 
        })
        
        taxable, ira = alu_utils.disaggregate_holdings(df_brok, df_ira)
        
        # VIG should be completely removed from taxable due to 0.0001 threshold
        self.assertNotIn('VIG', taxable, "Floating Point Dust Vaporizer FAILED! VIG leaked into taxable.")
        
        # SCHD should have exactly 1000 shares remaining in taxable
        self.assertIn('SCHD', taxable)
        self