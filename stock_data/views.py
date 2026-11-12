"""
Views for stock data management.
"""
import logging
from rest_framework import viewsets, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import AllowAny
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import SearchFilter, OrderingFilter
from django.db.models import Count, F, Max, Prefetch, Q, Window
from django.db.models.functions import RowNumber
from django.shortcuts import get_object_or_404
from datetime import datetime

from .models import StockData, Stock
from .serializers import StockDataSerializer, StockSerializer, StockListSerializer
from .utils import NepalStockScraper
from .structure_data import StockSequenceGenerator
from .pagination import StockDataPagination, StockPagination
from .filters import StockDataFilter, StockFilter
from .constants import (
    DATE_FORMAT,
    DEFAULT_PAGE_SIZE,
    SEARCH_PARAM,
    GAINER_PARAM,
    DATE_PARAM,
    GAINER_TRUE_VALUES,
    GAINER_FALSE_VALUES,
    NEPAL_STOCK_BASE_URL,
)
from accounts.permissions import IsAdminOrManager

# Stock type constants
STOCK_TYPE_PARAM = 'stock_type'
DEFAULT_STOCK_TYPE = 'stock'  # Default to regular stocks only
ALL_STOCK_TYPES = 'all'  # Use this value to show all types

logger = logging.getLogger(__name__)


class StockDataViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing stock data entries.
    
    Provides CRUD operations for stock data with pagination and filtering.
    
    Filtering:
    - date: Exact date (YYYY-MM-DD)
    - date__gte: Date greater than or equal
    - date__lte: Date less than or equal
    - stock__symbol: Exact symbol match
    - stock__symbol__icontains: Symbol contains (case-insensitive)
    - stock__security_name__icontains: Security name contains
    - close_price__gte: Close price greater than or equal
    - close_price__lte: Close price less than or equal
    - is_gainer: true/false (close_price > open_price)
    - has_lstm_prediction: true/false
    - has_rf_prediction: true/false
    - ordering: Order by date, close_price, volume, value
    
    Example: /api/stock-data/entries/?date=2024-01-15&is_gainer=true&ordering=-close_price
    """
    queryset = StockData.objects.select_related('stock').all()
    serializer_class = StockDataSerializer
    pagination_class = StockDataPagination
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_class = StockDataFilter
    search_fields = ['stock__symbol', 'stock__security_name']
    ordering_fields = ['date', 'close_price', 'total_traded_quantity', 'total_traded_value']
    ordering = ['-date']  # Default ordering


class StockViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing stocks.
    
    Provides CRUD operations for stocks with pagination and filtering.
    
    Filtering:
    - symbol: Exact symbol match
    - symbol__icontains: Symbol contains (case-insensitive)
    - security_name__icontains: Security name contains
    - security_id: Exact security ID
    - stock_type: Filter by stock type (stock, mutual_fund, debenture, promoter_share, preferred_stock)
                  Default: 'stock' (regular stocks only)
                  Use 'all' to show all types
    - has_lstm_metrics: true/false
    - has_rf_metrics: true/false
    - ordering: Order by symbol, security_name, security_id
    - search: Search in symbol and security_name
    - include_data: true/false - Include nested stock data (default: true)
    - data_limit: int - Number of nested entries to include (default: 5, max: 50)
    
    Example: /api/stock-data/?symbol__icontains=NBL&stock_type=stock&include_data=false
             /api/stock-data/?stock_type=mutual_fund (show only mutual funds)
             /api/stock-data/?stock_type=all (show all security types)
    """
    queryset = Stock.objects.all()
    serializer_class = StockSerializer
    pagination_class = StockPagination
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_class = StockFilter
    search_fields = ['symbol', 'security_name']
    ordering_fields = ['symbol', 'security_name', 'security_id', 'stock_type']
    ordering = ['symbol']  # Default ordering

    def get_queryset(self):
        """
        Filter queryset by stock_type.
        Default: Only regular stocks (stock_type='stock')
        Use stock_type=all to get all types
        """
        queryset = super().get_queryset()
        stock_type = self.request.query_params.get(STOCK_TYPE_PARAM, DEFAULT_STOCK_TYPE)
        
        if stock_type.lower() != ALL_STOCK_TYPES:
            # Filter by specific stock type (default is 'stock')
            queryset = queryset.filter(stock_type=stock_type)

        if self.action in ('list', 'retrieve'):
            # Total history count without loading the history itself.
            queryset = queryset.annotate(_data_count=Count('data'))

            include_data = (
                self.request.query_params.get('include_data', 'true').lower()
                in ('true', '1', 'yes')
            )
            if include_data:
                # Prefetch only the rows the serializer will actually return.
                # Prefetching all ~497 rows per stock took ~2 s for a 100-stock
                # page and produced a 254 KB response.
                limit = 60 if self.action == 'retrieve' else 5
                recent = (
                    StockData.objects
                    .annotate(rn=Window(
                        expression=RowNumber(),
                        partition_by=[F('stock_id')],
                        order_by=F('date').desc(),
                    ))
                    .filter(rn__lte=limit)
                    .order_by('-date')
                )
                queryset = queryset.prefetch_related(
                    Prefetch('data', queryset=recent, to_attr='recent_data')
                )

        return queryset

    def get_serializer_class(self):
        """Return appropriate serializer based on action."""
        if self.action in ['list', 'retrieve']:
            return StockListSerializer
        return StockSerializer

    def get_serializer_context(self):
        """Add context for serializer to control nested data."""
        context = super().get_serializer_context()
        
        # Get query parameters for nested data control
        include_data_param = self.request.query_params.get('include_data', 'true')
        include_data = include_data_param.lower() in ['true', '1', 'yes']
        
        # Detail pages render a 60-candle chart; list rows only need the latest.
        default_limit = 60 if self.action == 'retrieve' else 5
        try:
            data_limit = int(self.request.query_params.get('data_limit', default_limit))
            data_limit = min(max(data_limit, 0), 60)  # Clamp between 0 and 60
        except (ValueError, TypeError):
            data_limit = default_limit
        
        context['include_data'] = include_data
        context['data_limit'] = data_limit
        
        return context


class LoadStockDataView(APIView):
    """
    API view for fetching and loading stock data from Nepal Stock Exchange.
    
    Requires admin or manager permissions.
    """
    # permission_classes = [IsAdminOrManager]

    def post(self, request, format=None):
        """
        Fetch stock data from Nepal Stock Exchange for a date range.
        
        Args:
            request.data['date_from']: Start date in YYYY-MM-DD format (required)
            request.data['date_to']: End date in YYYY-MM-DD format or "latest" (required)
        
        Returns:
            Response with success message, statistics, and error
        """
        date_from_str = request.data.get("date_from")
        date_to_str = request.data.get("date_to")
        
        # Validate required parameters
        if not date_from_str:
            return Response(
                {"error": "date_from is required (format: YYYY-MM-DD)"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if not date_to_str:
            return Response(
                {"error": "date_to is required (format: YYYY-MM-DD or 'latest')"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        scraper = None
        save_to_db = request.data.get("save_to_db", True)
        if isinstance(save_to_db, str):
            save_to_db = save_to_db.strip().lower() not in ("false", "0", "no", "")

        headless = request.data.get("headless", True)
        if isinstance(headless, str):
            headless = headless.strip().lower() not in ("false", "0", "no", "")

        stats = {
            'total_dates': 0,
            'dates_processed': 0,
            'dates_skipped': 0,
            'dates_failed': 0,
            'stocks_created': 0,
            'stocks_updated': 0,
            'trading_days': 0,
            'rows_parsed': 0,
            'rows_created': 0,
            'rows_skipped': 0,
            'unresolved_symbols': [],
            'error_messages': [],
        }

        try:
            # Parse date_from
            try:
                date_from = datetime.strptime(date_from_str, DATE_FORMAT).date()
            except ValueError:
                return Response(
                    {"error": f"Invalid date_from format: {date_from_str}. Use YYYY-MM-DD."},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Parse date_to or get latest date
            if date_to_str.lower() == 'latest':
                latest_entry = StockData.objects.aggregate(latest_date=Max('date'))
                if latest_entry['latest_date']:
                    date_to = latest_entry['latest_date']
                    logger.info(f"Using latest date from database: {date_to}")
                else:
                    return Response(
                        {"error": "No data in database to determine latest date. Please provide a specific date_to."},
                        status=status.HTTP_400_BAD_REQUEST
                    )
            else:
                try:
                    date_to = datetime.strptime(date_to_str, DATE_FORMAT).date()
                except ValueError:
                    return Response(
                        {"error": f"Invalid date_to format: {date_to_str}. Use YYYY-MM-DD or 'latest'."},
                        status=status.HTTP_400_BAD_REQUEST
                    )
            
            # Validate date range
            if date_from > date_to:
                return Response(
                    {"error": "date_from cannot be greater than date_to"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            scraper = NepalStockScraper(headless=bool(headless))
            print(
                f"Fetch request: {date_from} to {date_to} "
                f"(headless={bool(headless)}, save_to_db={bool(save_to_db)})"
            )
            scraper.load_page(NEPAL_STOCK_BASE_URL)
            stats = scraper.loop_through_date_range(
                Stock, StockData, date_from, date_to, save_to_db=bool(save_to_db)
            )
            
            logger.info(
                f"Successfully processed stock data from {date_from} to {date_to}. "
                f"Processed: {stats['dates_processed']}, "
                f"Skipped: {stats['dates_skipped']}, "
                f"Failed: {stats['dates_failed']}"
            )
            
            return Response(
                {
                    "message": "Data loading completed",
                    "date_from": str(date_from),
                    "date_to": str(date_to),
                    "statistics": stats,
                    "unresolved_symbols": stats.get("unresolved_symbols", []),
                },
                status=status.HTTP_200_OK
            )
        except Exception as e:
            logger.error(f"Error loading stock data: {str(e)}", exc_info=True)
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        finally:
            if scraper:
                scraper.close()


class StructuredDataView(APIView):
    """
    API view for retrieving structured stock data for model training.
    
    Returns stock data in a format suitable for machine learning models.
    
    Note: This endpoint returns all data without pagination as it's designed
    for ML model training which typically needs the full dataset.
    """

    def get(self, request):
        """
        Get structured stock data.
        
        Query Parameters:
            stock__symbol: Filter by specific stock symbol
            date__gte: Filter data from this date onwards
            date__lte: Filter data up to this date
        
        Returns:
            Response with structured stock data as JSON
        """
        try:
            # Apply basic filters if provided
            queryset = StockData.objects.select_related('stock').all()
            
            stock_symbol = request.query_params.get('stock__symbol')
            date_gte = request.query_params.get('date__gte')
            date_lte = request.query_params.get('date__lte')
            
            if stock_symbol:
                queryset = queryset.filter(stock__symbol=stock_symbol)
            if date_gte:
                try:
                    date_obj = datetime.strptime(date_gte, DATE_FORMAT).date()
                    queryset = queryset.filter(date__gte=date_obj)
                except ValueError:
                    pass
            if date_lte:
                try:
                    date_obj = datetime.strptime(date_lte, DATE_FORMAT).date()
                    queryset = queryset.filter(date__lte=date_obj)
                except ValueError:
                    pass

            # This view loads everything into pandas and returns it unpaginated.
            # Require a filter and cap the row count so one request cannot try to
            # materialise the whole StockData table.
            if not stock_symbol and not date_gte and not date_lte:
                return Response(
                    {'error': 'Provide stock__symbol or a date range '
                              '(date__gte / date__lte)'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            max_rows = 20000
            if queryset.count() > max_rows:
                return Response(
                    {'error': f'Result exceeds {max_rows} rows; narrow the filters'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            sequence_generator = StockSequenceGenerator()
            stock_dataframe = sequence_generator.fetch_data_from_queryset(queryset)
            json_data = stock_dataframe.to_dict(orient="records")
            
            return Response(
                {'data': json_data, 'count': len(json_data)},
                status=status.HTTP_200_OK
            )
        except Exception as e:
            logger.error(f"Error generating structured data: {str(e)}", exc_info=True)
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class LatestStockDataViewSet(viewsets.ViewSet):
    """
    ViewSet for retrieving latest stock data with filtering and pagination.
    """
    pagination_class = StockDataPagination

    def list(self, request):
        """
        List latest stock data with optional filtering.
        
        Query Parameters:
            search: Search by symbol or security name
            gainer: Filter by gainers (true/false)
            date: Specific date (YYYY-MM-DD format)
            stock_type: Filter by stock type (stock, mutual_fund, debenture, etc.)
                        Default: 'stock' (regular stocks only)
                        Use 'all' to show all types
            page: Page number
            page_size: Items per page
        
        Returns:
            Paginated response with stock data
        """
        search_query = request.query_params.get(SEARCH_PARAM)
        is_gainer = request.query_params.get(GAINER_PARAM)
        target_date_str = request.query_params.get(DATE_PARAM)
        stock_type = request.query_params.get(STOCK_TYPE_PARAM, DEFAULT_STOCK_TYPE)

        target_date = self._get_target_date(target_date_str)
        if not target_date:
            return Response(
                {'error': 'No data available for the specified or latest date.'},
                status=status.HTTP_404_NOT_FOUND
            )

        queryset = StockData.objects.filter(
            date=target_date
        ).select_related('stock')
        
        # Apply stock_type filter (default: only regular stocks)
        if stock_type.lower() != ALL_STOCK_TYPES:
            queryset = queryset.filter(stock__stock_type=stock_type)
        
        queryset = self._apply_filters(queryset, search_query, is_gainer)

        stock_data_by_symbol = self._build_stock_data_dict(queryset)
        response_data = list(stock_data_by_symbol.values())
        
        # Sort by percentage change if filtering by gainers/losers
        if is_gainer in GAINER_TRUE_VALUES:
            # Sort gainers by percentage change descending (highest gain first)
            response_data.sort(
                key=lambda x: x.get('percentage_change', 0) or 0,
                reverse=True
            )
        elif is_gainer in GAINER_FALSE_VALUES:
            # Sort losers by percentage change ascending (biggest loss first, most negative)
            response_data.sort(
                key=lambda x: x.get('percentage_change', 0) or 0,
                reverse=False
            )

        paginator = self.pagination_class()
        paginated_data = paginator.paginate_queryset(response_data, request)

        return paginator.get_paginated_response(paginated_data)

    def _get_target_date(self, date_str):
        """
        Get target date from string or return latest available date.
        
        Args:
            date_str: Date string in YYYY-MM-DD format
        
        Returns:
            Date object or None
        """
        if date_str:
            try:
                return datetime.strptime(date_str, DATE_FORMAT).date()
            except ValueError:
                logger.warning(f"Invalid date format: {date_str}")
                return None
        else:
            latest_entry = StockData.objects.aggregate(latest_date=Max('date'))
            return latest_entry['latest_date']

    def _apply_filters(self, queryset, search_query, is_gainer):
        """
        Apply search and gainer filters to queryset.
        
        Args:
            queryset: Base queryset
            search_query: Search term for symbol or security name
            is_gainer: Filter by gainers (true/false)
        
        Returns:
            Filtered queryset
        """
        if search_query:
            queryset = queryset.filter(
                Q(stock__symbol__icontains=search_query) |
                Q(stock__security_name__icontains=search_query)
            )

        if is_gainer in GAINER_TRUE_VALUES:
            queryset = queryset.filter(close_price__gt=F('open_price'))
        elif is_gainer in GAINER_FALSE_VALUES:
            queryset = queryset.filter(close_price__lte=F('open_price'))

        return queryset

    def _build_stock_data_dict(self, queryset):
        """
        Build dictionary of stock data grouped by stock.
        
        Args:
            queryset: Filtered stock data queryset
        
        Returns:
            Dictionary with stock as key and data list as value
        """
        stock_data_by_symbol = {}
        for stock_data_entry in queryset:
            stock = stock_data_entry.stock
            
            # Calculate percentage change
            # Formula: (today's close - previous day's close) / previous day's close * 100
            percentage_change = None
            if stock_data_entry.previous_day_close_price and stock_data_entry.previous_day_close_price > 0:
                percentage_change = float(
                    (stock_data_entry.close_price - stock_data_entry.previous_day_close_price) 
                    / stock_data_entry.previous_day_close_price * 100
                )
            if stock not in stock_data_by_symbol:
                stock_data_by_symbol[stock] = {
                    'id': stock.id,
                    'symbol': stock.symbol,
                    'security_id': stock.security_id,
                    'security_name': stock.security_name,
                    'stock_type': stock.stock_type,
                    'fifty_two_weeks_high': stock.fifty_two_weeks_high,
                    'fifty_two_weeks_low': stock.fifty_two_weeks_low,
                    'percentage_change': percentage_change,
                    'data': []
                }
            else:
                # Update percentage_change if not set (use latest entry)
                if stock_data_by_symbol[stock]['percentage_change'] is None:
                    stock_data_by_symbol[stock]['percentage_change'] = percentage_change
                    
            stock_data_by_symbol[stock]['data'].append({
                'date': stock_data_entry.date,
                'open_price': stock_data_entry.open_price,
                'high_price': stock_data_entry.high_price,
                'low_price': stock_data_entry.low_price,
                'close_price': stock_data_entry.close_price,
                'total_traded_quantity': stock_data_entry.total_traded_quantity,
                'total_traded_value': stock_data_entry.total_traded_value,
                'previous_day_close_price': stock_data_entry.previous_day_close_price,
                'last_updated_price': stock_data_entry.last_updated_price,
                'total_trades': stock_data_entry.total_trades,
                'average_traded_price': stock_data_entry.average_traded_price,
                'market_capitalization': stock_data_entry.market_capitalization,
                'percentage_change': percentage_change,
            })
        return stock_data_by_symbol
