"""
API views for floorsheet data management.

Provides endpoints to:
- Upload and parse floorsheet HTML from merolagani.com
- Retrieve stored floorsheet data
- Analyze floorsheet patterns (broker activity, self-trades, etc.)
"""
from datetime import datetime, timedelta
from decimal import Decimal

from django.db.models import Sum, Count, Avg, F, Q
from django.db.models.functions import TruncDate
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny

from .models import Stock, FloorsheetData
from .floorsheet_scraper import (
    MerolaganiFloorsheetScraper,
    parse_floorsheet_html,
    save_floorsheet_to_db
)
from .nepalstock_floorsheet_scraper import NepalstockFloorsheetScraper


class FloorsheetUploadView(APIView):
    """
    Upload and parse floorsheet HTML content.
    
    POST /api/stock_data/floorsheet/upload/
    
    Body:
        {
            "symbol": "MBJC",
            "html_content": "<html>...</html>"
        }
    
    Returns parsed transactions and saves to database.
    """
    permission_classes = [AllowAny]
    
    def post(self, request):
        symbol = request.data.get('symbol')
        html_content = request.data.get('html_content')
        save_to_db = request.data.get('save_to_db', True)
        
        if not symbol:
            return Response(
                {'error': 'symbol is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if not html_content:
            return Response(
                {'error': 'html_content is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Verify stock exists
        try:
            stock = Stock.objects.get(symbol=symbol.upper())
        except Stock.DoesNotExist:
            return Response(
                {'error': f"Stock with symbol '{symbol}' not found"},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Parse HTML using classmethod (no need to instantiate)
        transactions, metadata = MerolaganiFloorsheetScraper.scrape_from_html(
            html_content, symbol.upper()
        )
        
        # Save to database if requested (use bulk insert for better performance)
        save_stats = None
        if save_to_db and transactions:
            save_stats = save_floorsheet_to_db(
                transactions, 
                symbol.upper(), 
                skip_existing=True,
                bulk_insert=True  # Use bulk insert for better performance
            )
        
        # Prepare response
        response_data = {
            'symbol': symbol.upper(),
            'parse_metadata': metadata,
            'transactions_count': len(transactions),
        }
        
        if save_stats:
            response_data['save_stats'] = save_stats
        
        # Include sample transactions (first 10)
        if transactions:
            response_data['sample_transactions'] = [
                {
                    'transaction_date': t.transaction_date.strftime('%Y-%m-%d'),
                    'transaction_no': t.transaction_no,
                    'buyer_broker': t.buyer_broker,
                    'seller_broker': t.seller_broker,
                    'quantity': t.quantity,
                    'rate': float(t.rate),
                    'amount': float(t.amount),
                }
                for t in transactions[:10]
            ]
        
        return Response(response_data)


class FloorsheetScrapeView(APIView):
    """
    Scrape floorsheet data directly from merolagani.com using Selenium.
    
    POST /api/stock_data/floorsheet/scrape/
    
    Body (single symbol):
        {
            "symbol": "MBJC",
            "date_from": "01/22/2026",  // Optional: MM/DD/YYYY format
            "date_to": "02/01/2026",    // Optional: MM/DD/YYYY format
            "save_to_db": true,
            "scrape_all_pages": true
        }
    
    Body (multiple symbols):
        {
            "symbols": ["MBJC", "NABIL", "NICA"],
            "date_from": "01/22/2026",
            "date_to": "02/01/2026",
            "save_to_db": true,
            "scrape_all_pages": true
        }
    
    Body (ALL symbols - no symbol/symbols provided):
        {
            "date_from": "01/22/2026",
            "date_to": "02/01/2026",
            "save_to_db": true
        }
    
    Symbol Handling:
        - If 'symbol' provided: scrapes single symbol
        - If 'symbols' provided (list or comma-separated string): scrapes multiple symbols
        - If neither provided: scrapes ALL symbols from Stock table
    
    Date Handling:
        - If no dates provided: fetches data for the last 10 days
        - Dates must be in MM/DD/YYYY format (e.g., "02/01/2026", "12/31/2025")
        - Dates already in database are automatically skipped
    
    This uses Selenium WebDriver to:
    1. Loop through each symbol
    2. Loop through each date in the range
    3. Skip dates that already have data in database
    4. Scrape ALL pages of data (handles pagination)
    5. Save only new transactions to database
    """
    permission_classes = [AllowAny]
    
    # Date format expected by merolagani.com
    DATE_FORMAT = "%m/%d/%Y"
    
    def post(self, request):
        # Accept either 'symbol' (string) or 'symbols' (list)
        # If neither provided, scrape ALL symbols from Stock table
        symbol = request.data.get('symbol')
        symbols = request.data.get('symbols', [])
        date_from = request.data.get('date_from')
        date_to = request.data.get('date_to')
        save_to_db = request.data.get('save_to_db', True)
        scrape_all_pages = request.data.get('scrape_all_pages', True)
        
        # Build symbols list
        if symbol and not symbols:
            symbols = [symbol]
        elif isinstance(symbols, str):
            # Handle comma-separated string
            symbols = [s.strip() for s in symbols.split(',') if s.strip()]
        
        # If no symbols provided, fetch ALL symbols from Stock table
        # Filter to only regular stocks (stock_type == 'stock'), not mutual funds or others
        if not symbols:
            all_stocks = Stock.objects.filter(stock_type='stock').values_list('symbol', flat=True)
            symbols = list(all_stocks)
            
            if not symbols:
                return Response(
                    {'error': 'No stocks found in database (filtered by stock_type=stock)'},
                    status=status.HTTP_404_NOT_FOUND
                )
            
            print(f"No symbols provided - scraping ALL {len(symbols)} stocks (stock_type=stock) from database")
        
        # Verify all stocks exist
        invalid_symbols = []
        valid_symbols = []
        for sym in symbols:
            try:
                Stock.objects.get(symbol=sym.upper())
                valid_symbols.append(sym.upper())
            except Stock.DoesNotExist:
                invalid_symbols.append(sym)
        
        if invalid_symbols and not valid_symbols:
            return Response(
                {'error': f"No valid stocks found. Invalid symbols: {', '.join(invalid_symbols)}"},
                status=status.HTTP_404_NOT_FOUND
            )
        
        if invalid_symbols:
            print(f"Warning: Skipping invalid symbols: {', '.join(invalid_symbols)}")
        
        # If no dates provided, default to last 10 days
        if not date_from and not date_to:
            today = datetime.now()
            date_to = today.strftime(self.DATE_FORMAT)
            date_from = (today - timedelta(days=10)).strftime(self.DATE_FORMAT)
        
        # Validate date format if provided
        if date_from:
            try:
                datetime.strptime(date_from, self.DATE_FORMAT)
            except ValueError:
                return Response(
                    {'error': f"Invalid date_from format. Use MM/DD/YYYY (e.g., '02/01/2026')"},
                    status=status.HTTP_400_BAD_REQUEST
                )
        
        if date_to:
            try:
                datetime.strptime(date_to, self.DATE_FORMAT)
            except ValueError:
                return Response(
                    {'error': f"Invalid date_to format. Use MM/DD/YYYY (e.g., '02/01/2026')"},
                    status=status.HTTP_400_BAD_REQUEST
                )
        
        # Initialize scraper
        scraper = MerolaganiFloorsheetScraper(headless=True)
        
        try:
            # Handle multiple symbols
            if len(valid_symbols) > 1:
                results = scraper.scrape_multiple_symbols(
                    symbols=valid_symbols,
                    date_from=date_from,
                    date_to=date_to,
                    scrape_all_pages=scrape_all_pages,
                    skip_existing_dates=True,
                    save_to_db=save_to_db
                )
                
                response_data = {
                    'date_range': {'from': date_from, 'to': date_to},
                    'results': results
                }
                
                if invalid_symbols:
                    response_data['skipped_invalid_symbols'] = invalid_symbols
                
                return Response(response_data)
            
            # Single symbol - original behavior
            symbol = valid_symbols[0]
            transactions, metadata = scraper.scrape_from_url(
                symbol=symbol,
                date_from=date_from,
                date_to=date_to,
                scrape_all_pages=scrape_all_pages,
                skip_existing_dates=True
            )
            
            # Save to database if requested
            save_stats = None
            if save_to_db and transactions:
                save_stats = save_floorsheet_to_db(transactions, symbol.upper())
            
            # Prepare response
            response_data = {
                'symbol': symbol.upper(),
                'date_range': {
                    'from': date_from,
                    'to': date_to
                },
                'scrape_metadata': metadata,
                'transactions_count': len(transactions),
            }
            
            if save_stats:
                response_data['save_stats'] = save_stats
            
            # Include sample transactions (first 10)
            if transactions:
                response_data['sample_transactions'] = [
                    {
                        'transaction_date': t.transaction_date.strftime('%Y-%m-%d'),
                        'transaction_no': t.transaction_no,
                        'buyer_broker': t.buyer_broker,
                        'seller_broker': t.seller_broker,
                        'quantity': t.quantity,
                        'rate': float(t.rate),
                        'amount': float(t.amount),
                    }
                    for t in transactions[:10]
                ]
            
            return Response(response_data)
            
        except Exception as e:
            return Response(
                {'error': f'Scraping failed: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        finally:
            # Always close the WebDriver
            scraper.close()


class NepalstockFloorsheetScrapeView(APIView):
    """
    Scrape ALL floorsheet data directly from nepalstock.com using Selenium.
    
    POST /api/stock_data/floorsheet/nepalstock-scrape/
    
    Body:
        {
            "save_to_db": true,  // Optional: Save to database (default: true)
            "headless": true     // Optional: Run in headless mode (default: true)
        }
    
    This scraper:
    1. Loads the nepalstock.com floorsheet page (no filters)
    2. Sets "Items Per Page" to 500
    3. Clicks the "Filter" button
    4. Extracts ALL data from the table (all symbols)
    5. Maps "Contract Number" to transaction_no
    6. Extracts symbol from each row
    7. Saves to database grouped by symbol using FloorsheetData model
    
    Note: The scraper uses the same FloorsheetData model as merolagani.com scraper.
    No symbol or date filters are applied - it scrapes ALL available data.
    """
    permission_classes = [AllowAny]
    
    def post(self, request):
        save_to_db = request.data.get('save_to_db', True)
        headless = request.data.get('headless', False)  # Default to False for easier debugging
        
        scraper = None
        try:
            scraper = NepalstockFloorsheetScraper(headless=headless)
            
            # Scrape all data (no symbol/date filters)
            transactions, metadata = scraper.scrape_from_url(
                save_to_db=save_to_db
            )
            
            # Build response
            response_data = {
                'success': True,
                'transactions_count': len(transactions),
                'symbols_found': metadata.get('symbols_found', []),
                'metadata': metadata,
            }
            
            if save_to_db:
                response_data['save_info'] = {
                    'saved_to_db': True,
                    'symbols_saved': len(metadata.get('symbols_found', []))
                }
            
            # Include sample transactions (first 5)
            if transactions:
                response_data['sample_transactions'] = [
                    {
                        'symbol': item.get('symbol', 'UNKNOWN'),
                        'transaction_date': item['transaction'].transaction_date.strftime('%Y-%m-%d'),
                        'transaction_no': item['transaction'].transaction_no,
                        'buyer_broker': item['transaction'].buyer_broker,
                        'seller_broker': item['transaction'].seller_broker,
                        'quantity': item['transaction'].quantity,
                        'rate': float(item['transaction'].rate),
                        'amount': float(item['transaction'].amount),
                    }
                    for item in transactions[:5]
                ]
            
            return Response(response_data, status=status.HTTP_200_OK)
            
        except Exception as e:
            return Response(
                {'error': f'Scraping failed: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        finally:
            # Always close the WebDriver
            if scraper:
                scraper.close()


class FloorsheetDataView(APIView):
    """
    Retrieve floorsheet data from database.
    
    GET /api/stock_data/floorsheet/data/?symbol=MBJC&days=7
    
    Query Parameters:
        - symbol: Stock symbol (required)
        - days: Number of days to fetch (default: 7)
        - start_date: Start date (YYYY-MM-DD)
        - end_date: End date (YYYY-MM-DD)
        - buyer: Filter by buyer broker number
        - seller: Filter by seller broker number
        - limit: Max records (default: 1000)
    """
    permission_classes = [AllowAny]
    
    def get(self, request):
        symbol = request.query_params.get('symbol')
        
        if not symbol:
            return Response(
                {'error': 'symbol query parameter is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            stock = Stock.objects.get(symbol=symbol.upper())
        except Stock.DoesNotExist:
            return Response(
                {'error': f"Stock with symbol '{symbol}' not found"},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Build query filters
        queryset = FloorsheetData.objects.filter(stock=stock)
        
        # Date filters
        start_date = request.query_params.get('start_date')
        end_date = request.query_params.get('end_date')
        days = request.query_params.get('days', 7)
        
        if start_date:
            try:
                start = datetime.strptime(start_date, '%Y-%m-%d').date()
                queryset = queryset.filter(transaction_date__gte=start)
            except ValueError:
                return Response(
                    {'error': 'Invalid start_date format. Use YYYY-MM-DD'},
                    status=status.HTTP_400_BAD_REQUEST
                )
        elif not end_date:
            # Default to last N days
            try:
                days_int = int(days)
                start = datetime.now().date() - timedelta(days=days_int)
                queryset = queryset.filter(transaction_date__gte=start)
            except ValueError:
                pass
        
        if end_date:
            try:
                end = datetime.strptime(end_date, '%Y-%m-%d').date()
                queryset = queryset.filter(transaction_date__lte=end)
            except ValueError:
                return Response(
                    {'error': 'Invalid end_date format. Use YYYY-MM-DD'},
                    status=status.HTTP_400_BAD_REQUEST
                )
        
        # Broker filters
        buyer = request.query_params.get('buyer')
        seller = request.query_params.get('seller')
        
        if buyer:
            try:
                queryset = queryset.filter(buyer_broker=int(buyer))
            except ValueError:
                pass
        
        if seller:
            try:
                queryset = queryset.filter(seller_broker=int(seller))
            except ValueError:
                pass
        
        # Limit results
        limit = int(request.query_params.get('limit', 1000))
        queryset = queryset.order_by('-transaction_date', '-transaction_no')[:limit]
        
        # Build response
        transactions = list(queryset.values(
            'transaction_date',
            'transaction_no',
            'buyer_broker',
            'seller_broker',
            'quantity',
            'rate',
            'amount',
            'scraped_at'
        ))
        
        # Calculate summary stats
        summary = queryset.aggregate(
            total_quantity=Sum('quantity'),
            total_amount=Sum('amount'),
            avg_rate=Avg('rate'),
            transaction_count=Count('id')
        )
        
        return Response({
            'symbol': symbol.upper(),
            'count': len(transactions),
            'summary': summary,
            'transactions': transactions
        })


class FloorsheetAnalysisView(APIView):
    """
    Analyze floorsheet patterns for a stock.
    
    GET /api/stock_data/floorsheet/analysis/?symbol=MBJC&days=30
    
    Provides:
        - Broker activity analysis (most active buyers/sellers)
        - Self-trade detection (same broker on both sides)
        - Large block trades
        - Daily volume patterns
    """
    permission_classes = [AllowAny]
    
    def get(self, request):
        symbol = request.query_params.get('symbol')
        days = int(request.query_params.get('days', 30))
        
        if not symbol:
            return Response(
                {'error': 'symbol query parameter is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            stock = Stock.objects.get(symbol=symbol.upper())
        except Stock.DoesNotExist:
            return Response(
                {'error': f"Stock with symbol '{symbol}' not found"},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Get date range
        end_date = datetime.now().date()
        start_date = end_date - timedelta(days=days)
        
        queryset = FloorsheetData.objects.filter(
            stock=stock,
            transaction_date__gte=start_date,
            transaction_date__lte=end_date
        )
        
        if not queryset.exists():
            return Response({
                'symbol': symbol.upper(),
                'message': 'No floorsheet data found for the specified period',
                'date_range': {
                    'start': start_date.isoformat(),
                    'end': end_date.isoformat()
                }
            })
        
        # Analyze broker activity
        top_buyers = list(queryset.values('buyer_broker').annotate(
            total_quantity=Sum('quantity'),
            total_amount=Sum('amount'),
            transaction_count=Count('id')
        ).order_by('-total_quantity')[:10])
        
        top_sellers = list(queryset.values('seller_broker').annotate(
            total_quantity=Sum('quantity'),
            total_amount=Sum('amount'),
            transaction_count=Count('id')
        ).order_by('-total_quantity')[:10])
        
        # Self-trades (same broker on both sides)
        self_trades = queryset.filter(
            buyer_broker=F('seller_broker')
        ).aggregate(
            count=Count('id'),
            total_quantity=Sum('quantity'),
            total_amount=Sum('amount')
        )
        
        total_stats = queryset.aggregate(
            total_trades=Count('id'),
            total_quantity=Sum('quantity'),
            total_amount=Sum('amount')
        )
        
        self_trade_percentage = 0
        if total_stats['total_quantity']:
            self_trade_percentage = (
                (self_trades['total_quantity'] or 0) / total_stats['total_quantity']
            ) * 100
        
        # Large block trades (top 1% by quantity)
        avg_qty = queryset.aggregate(avg=Avg('quantity'))['avg'] or 0
        large_trade_threshold = avg_qty * 5  # 5x average
        
        large_trades = list(queryset.filter(
            quantity__gte=large_trade_threshold
        ).order_by('-quantity').values(
            'transaction_date',
            'transaction_no',
            'buyer_broker',
            'seller_broker',
            'quantity',
            'rate',
            'amount'
        )[:20])
        
        # Daily volume pattern
        daily_volume = list(queryset.annotate(
            date=TruncDate('transaction_date')
        ).values('date').annotate(
            total_quantity=Sum('quantity'),
            total_amount=Sum('amount'),
            trade_count=Count('id'),
            avg_rate=Avg('rate')
        ).order_by('date'))
        
        # Broker concentration (Herfindahl-Hirschman Index approximation)
        buyer_shares = queryset.values('buyer_broker').annotate(
            share=Sum('quantity')
        )
        total_qty = sum(b['share'] for b in buyer_shares) or 1
        buyer_hhi = sum((b['share'] / total_qty * 100) ** 2 for b in buyer_shares)
        
        return Response({
            'symbol': symbol.upper(),
            'date_range': {
                'start': start_date.isoformat(),
                'end': end_date.isoformat()
            },
            'overview': {
                'total_trades': total_stats['total_trades'],
                'total_quantity': total_stats['total_quantity'],
                'total_amount': float(total_stats['total_amount'] or 0),
                'unique_buyers': queryset.values('buyer_broker').distinct().count(),
                'unique_sellers': queryset.values('seller_broker').distinct().count(),
            },
            'top_buyers': top_buyers,
            'top_sellers': top_sellers,
            'self_trades': {
                'count': self_trades['count'],
                'total_quantity': self_trades['total_quantity'],
                'total_amount': float(self_trades['total_amount'] or 0),
                'percentage_of_volume': round(self_trade_percentage, 2)
            },
            'large_block_trades': {
                'threshold_quantity': round(large_trade_threshold, 0),
                'trades': large_trades
            },
            'daily_volume': daily_volume,
            'concentration': {
                'buyer_hhi': round(buyer_hhi, 2),
                'interpretation': (
                    'Highly concentrated' if buyer_hhi > 2500 
                    else 'Moderately concentrated' if buyer_hhi > 1500 
                    else 'Competitive/Distributed'
                )
            }
        })


class BrokerActivityView(APIView):
    """
    Track specific broker's activity across stocks.
    
    GET /api/stock_data/floorsheet/broker/?broker=57&days=30
    
    Query Parameters:
        - broker: Broker number (required)
        - days: Number of days (default: 30)
        - symbol: Optional - filter to specific stock
        - role: 'buyer', 'seller', or 'both' (default: 'both')
    """
    permission_classes = [AllowAny]
    
    def get(self, request):
        broker = request.query_params.get('broker')
        
        if not broker:
            return Response(
                {'error': 'broker query parameter is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            broker_num = int(broker)
        except ValueError:
            return Response(
                {'error': 'broker must be a number'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        days = int(request.query_params.get('days', 30))
        role = request.query_params.get('role', 'both')
        symbol = request.query_params.get('symbol')
        
        end_date = datetime.now().date()
        start_date = end_date - timedelta(days=days)
        
        # Build base query
        base_filter = {
            'transaction_date__gte': start_date,
            'transaction_date__lte': end_date
        }
        
        if symbol:
            try:
                stock = Stock.objects.get(symbol=symbol.upper())
                base_filter['stock'] = stock
            except Stock.DoesNotExist:
                return Response(
                    {'error': f"Stock with symbol '{symbol}' not found"},
                    status=status.HTTP_404_NOT_FOUND
                )
        
        # Filter by role
        if role == 'buyer':
            queryset = FloorsheetData.objects.filter(
                buyer_broker=broker_num, **base_filter
            )
        elif role == 'seller':
            queryset = FloorsheetData.objects.filter(
                seller_broker=broker_num, **base_filter
            )
        else:  # both
            queryset = FloorsheetData.objects.filter(
                Q(buyer_broker=broker_num) | Q(seller_broker=broker_num),
                **base_filter
            )
        
        # Aggregate by stock
        stocks_as_buyer = FloorsheetData.objects.filter(
            buyer_broker=broker_num, **base_filter
        ).values(
            'stock__symbol'
        ).annotate(
            bought_quantity=Sum('quantity'),
            bought_amount=Sum('amount'),
            buy_count=Count('id')
        ).order_by('-bought_quantity')
        
        stocks_as_seller = FloorsheetData.objects.filter(
            seller_broker=broker_num, **base_filter
        ).values(
            'stock__symbol'
        ).annotate(
            sold_quantity=Sum('quantity'),
            sold_amount=Sum('amount'),
            sell_count=Count('id')
        ).order_by('-sold_quantity')
        
        # Combine into net position
        net_positions = {}
        
        for item in stocks_as_buyer:
            sym = item['stock__symbol']
            net_positions[sym] = {
                'symbol': sym,
                'bought_quantity': item['bought_quantity'],
                'bought_amount': float(item['bought_amount'] or 0),
                'buy_count': item['buy_count'],
                'sold_quantity': 0,
                'sold_amount': 0,
                'sell_count': 0
            }
        
        for item in stocks_as_seller:
            sym = item['stock__symbol']
            if sym in net_positions:
                net_positions[sym]['sold_quantity'] = item['sold_quantity']
                net_positions[sym]['sold_amount'] = float(item['sold_amount'] or 0)
                net_positions[sym]['sell_count'] = item['sell_count']
            else:
                net_positions[sym] = {
                    'symbol': sym,
                    'bought_quantity': 0,
                    'bought_amount': 0,
                    'buy_count': 0,
                    'sold_quantity': item['sold_quantity'],
                    'sold_amount': float(item['sold_amount'] or 0),
                    'sell_count': item['sell_count']
                }
        
        # Calculate net
        for sym in net_positions:
            pos = net_positions[sym]
            pos['net_quantity'] = pos['bought_quantity'] - pos['sold_quantity']
            pos['net_amount'] = pos['bought_amount'] - pos['sold_amount']
            pos['net_position'] = 'ACCUMULATING' if pos['net_quantity'] > 0 else 'DISTRIBUTING'
        
        # Sort by absolute net quantity
        sorted_positions = sorted(
            net_positions.values(),
            key=lambda x: abs(x['net_quantity']),
            reverse=True
        )
        
        # Summary stats
        total_bought = sum(p['bought_quantity'] for p in net_positions.values())
        total_sold = sum(p['sold_quantity'] for p in net_positions.values())
        
        return Response({
            'broker': broker_num,
            'date_range': {
                'start': start_date.isoformat(),
                'end': end_date.isoformat()
            },
            'summary': {
                'total_bought_quantity': total_bought,
                'total_sold_quantity': total_sold,
                'net_quantity': total_bought - total_sold,
                'overall_position': 'ACCUMULATING' if total_bought > total_sold else 'DISTRIBUTING',
                'stocks_traded': len(net_positions)
            },
            'positions': sorted_positions
        })
