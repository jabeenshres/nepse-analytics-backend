"""
Management command to categorize existing stocks into stock types.

This script analyzes stock symbols and names to categorize them as:
- mutual_fund: Mutual funds (typically ending with -U or containing "Mutual Fund")
- debenture: Debentures (containing "Debenture" in name)
- promoter_share: Promoter shares (containing "Promoter" in name)
- preferred_stock: Preferred stocks (containing "Preferred" or "PS" suffix)
- stock: Regular stocks (default for all others)

Run with: python manage.py categorize_stocks
"""

from django.core.management.base import BaseCommand
from django.db import transaction
from stock_data.models import Stock
import re


class Command(BaseCommand):
    help = 'Categorize existing stocks into stock types (stock, mutual_fund, debenture, etc.)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be changed without making actual changes',
        )
        parser.add_argument(
            '--verbose',
            action='store_true',
            help='Show detailed output for each stock',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        verbose = options['verbose']
        
        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN MODE - No changes will be made'))
        
        # Get all stocks
        stocks = Stock.objects.all()
        total = stocks.count()
        
        self.stdout.write(f'\nAnalyzing {total} stocks...\n')
        
        # Counters
        categorized = {
            'stock': 0,
            'mutual_fund': 0,
            'debenture': 0,
            'promoter_share': 0,
            'preferred_stock': 0,
        }
        
        # Patterns for categorization
        mutual_fund_patterns = [
            r'.*\d+U$',  # Ends with number followed by U (e.g., NMBHF1U, NBF2)
            r'.*-U$',    # Ends with -U
            r'.*MF\d*$', # Ends with MF or MF followed by number
            r'mutual fund',
            r'investment fund',
            r'equity fund',     # Matches MBLEF (MBL Equity Fund), SFEF (Sunrise Focused Equity Fund)
            r'balanced fund',   # Matches GIBF1 (Global IME Balanced Fund)
            r'value fund',      # Matches LVF2 (Laxmi Value Fund 2)
            r'growth fund',     # Matches NICGF (NIC Asia Growth Fund)
            r'select fund',     # Matches PSF (Prabhu Select Fund)
            r'bluechip fund',   # Matches SBCF (Sunrise Bluechip Fund)
            r'scheme',
        ]
        
        debenture_patterns = [
            r'debenture',
            r'bond',
            r'.*D\d{2,}$',  # Ends with D followed by 2+ digits (e.g., NBLD85)
        ]
        
        promoter_patterns = [
            r'promoter',
            r'.*-PO$',  # Ends with -PO
        ]
        
        preferred_patterns = [
            r'preferred',
            r'.*-PS$',  # Ends with -PS
            r'preference',
        ]
        
        # Common mutual fund symbols in NEPSE
        known_mutual_funds = {
            'NMBHF1', 'NBF2', 'NBF3', 'NICBF', 'NIBLPF', 'NIBSF1', 'NIBSF2',
            'NEF', 'LEMF', 'SIGS1', 'SIGS2', 'SIGS3', 'CMF1', 'CMF2',
            'GIMES1', 'PSF', 'SFMF', 'NMB50', 'NMBA', 'NICGF', 'SAEF',
            'SBCF', 'SEF', 'SFFIL', 'SLBSL', 'SIGS', 'GIBF1', 'GIGB1',
            'SLICL', 'LICNF', 'KLPF', 'KSBBL', 'KBSH', 'KBLF', 'JBNL',
            'JBNLG', 'HIDCL', 'GRDBL', 'GILB', 'GBD80/81', 'GBILD84/85',
            'GLICL', 'GLH', 'SICL', 'SBLD83', 'SBLD84', 'SBLD86', 'RSDC',
            'RMDC', 'RMDC1', 'RMDC2', 'MKLB', 'MLBSL', 'MLBS', 'MERO',
            'MEROB', 'LVF1', 'LVF2', 'LBSL', 'LBBL', 'LFLC', 'KKHC',
            # Equity and Balanced Funds
            'MBLEF', 'SFEF', 'NSIF2', 'RMF1', 'RMF2', 'MNMF1', 'C30MF',
        }
        
        stocks_to_update = []
        
        for stock in stocks:
            symbol_upper = stock.symbol.upper()
            name_lower = stock.security_name.lower() if stock.security_name else ''
            combined = f"{symbol_upper} {name_lower}"
            
            new_type = 'stock'  # Default
            
            # Check for mutual funds first (most common misclassification issue)
            if symbol_upper in known_mutual_funds:
                new_type = 'mutual_fund'
            else:
                # Check mutual fund patterns
                for pattern in mutual_fund_patterns:
                    if re.search(pattern, combined, re.IGNORECASE):
                        new_type = 'mutual_fund'
                        break
                
                # If not mutual fund, check for debentures
                if new_type == 'stock':
                    for pattern in debenture_patterns:
                        if re.search(pattern, combined, re.IGNORECASE):
                            new_type = 'debenture'
                            break
                
                # Check for promoter shares
                if new_type == 'stock':
                    for pattern in promoter_patterns:
                        if re.search(pattern, combined, re.IGNORECASE):
                            new_type = 'promoter_share'
                            break
                
                # Check for preferred stocks
                if new_type == 'stock':
                    for pattern in preferred_patterns:
                        if re.search(pattern, combined, re.IGNORECASE):
                            new_type = 'preferred_stock'
                            break
            
            # Update counter
            categorized[new_type] += 1
            
            # Check if update is needed
            if stock.stock_type != new_type:
                if verbose:
                    self.stdout.write(
                        f"  {stock.symbol}: {stock.stock_type} -> {new_type} ({stock.security_name})"
                    )
                stock.stock_type = new_type
                stocks_to_update.append(stock)
        
        # Apply updates
        if not dry_run and stocks_to_update:
            with transaction.atomic():
                Stock.objects.bulk_update(stocks_to_update, ['stock_type'], batch_size=100)
            self.stdout.write(
                self.style.SUCCESS(f'\nUpdated {len(stocks_to_update)} stocks')
            )
        elif dry_run and stocks_to_update:
            self.stdout.write(
                self.style.WARNING(f'\nWould update {len(stocks_to_update)} stocks (dry run)')
            )
        else:
            self.stdout.write('\nNo stocks needed updating')
        
        # Print summary
        self.stdout.write('\n' + '=' * 50)
        self.stdout.write('CATEGORIZATION SUMMARY')
        self.stdout.write('=' * 50)
        for stock_type, count in categorized.items():
            percentage = (count / total * 100) if total > 0 else 0
            self.stdout.write(f"  {stock_type:20s}: {count:5d} ({percentage:5.1f}%)")
        self.stdout.write('=' * 50)
        self.stdout.write(f"  {'TOTAL':20s}: {total:5d}")
        self.stdout.write('=' * 50 + '\n')
        
        # Show breakdown by category
        if verbose:
            self.stdout.write('\nStocks by category:\n')
            for stock_type in categorized.keys():
                type_stocks = Stock.objects.filter(stock_type=stock_type).values_list('symbol', flat=True)[:20]
                if type_stocks:
                    self.stdout.write(f"\n{stock_type.upper()} (showing first 20):")
                    self.stdout.write(f"  {', '.join(type_stocks)}")
