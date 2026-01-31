"""
Views for stock data management.
"""
import logging
from rest_framework import viewsets, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import AllowAny
from django.db.models import Max, Q, F
from django.shortcuts import get_object_or_404
from datetime import datetime

from .models import StockData, Stock
from .serializers import StockDataSerializer, StockSerializer, StockListSerializer
from .utils import NepalStockScraper
from .structure_data import StockSequenceGenerator
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

logger = logging.getLogger(__name__)


class StockDataViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing stock data entries.
    
    Provides CRUD operations for stock data.
    """
    queryset = StockData.objects.select_related('stock').all()
    serializer_class = StockDataSerializer
    permission_classes = [AllowAny]


class StockViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing stocks.
    
    Provides CRUD operations for stocks.
    """
    queryset = Stock.objects.all()
    serializer_class = StockSerializer
    permission_classes = [AllowAny]

    def get_serializer_class(self):
        """Return appropriate serializer based on action."""
        if self.action in ['list', 'retrieve']:
            return StockListSerializer
        return StockSerializer


class LoadStockDataView(APIView):
    """
    API view for fetching and loading stock data from Nepal Stock Exchange.
    
    Requires admin or manager permissions.
    """
    permission_classes = [IsAdminOrManager]

    def post(self, request, format=None):
        """
        Fetch stock data from Nepal Stock Exchange.
        
        Args:
            request.data['date']: Number of days back to fetch (default: 0)
        
        Returns:
            Response with success message or error
        """
        days_back = request.data.get("date", 0)
        scraper = None

        try:
            scraper = NepalStockScraper()
            scraper.load_page(NEPAL_STOCK_BASE_URL)
            scraper.loop_through_dates(Stock, StockData, days_back)
            
            logger.info(f"Successfully loaded stock data for {days_back} days back")
            return Response(
                {"message": "Data has been loaded successfully"},
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
    """
    permission_classes = [AllowAny]

    def get(self, request):
        """
        Get structured stock data.
        
        Returns:
            Response with structured stock data as JSON
        """
        try:
            sequence_generator = StockSequenceGenerator()
            stock_dataframe = sequence_generator.fetch_data(StockData)
            json_data = stock_dataframe.to_dict(orient="records")
            
            return Response(
                {'data': json_data},
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
    permission_classes = [AllowAny]

    def list(self, request):
        """
        List latest stock data with optional filtering.
        
        Query Parameters:
            search: Search by symbol or security name
            gainer: Filter by gainers (true/false)
            date: Specific date (YYYY-MM-DD format)
        
        Returns:
            Paginated response with stock data
        """
        search_query = request.query_params.get(SEARCH_PARAM)
        is_gainer = request.query_params.get(GAINER_PARAM)
        target_date_str = request.query_params.get(DATE_PARAM)

        target_date = self._get_target_date(target_date_str)
        if not target_date:
            return Response(
                {'error': 'No data available for the specified or latest date.'},
                status=status.HTTP_404_NOT_FOUND
            )

        queryset = StockData.objects.filter(
            date=target_date
        ).select_related('stock')
        queryset = self._apply_filters(queryset, search_query, is_gainer)

        stock_data_by_symbol = self._build_stock_data_dict(queryset)
        response_data = list(stock_data_by_symbol.values())

        paginator = PageNumberPagination()
        paginator.page_size = DEFAULT_PAGE_SIZE
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
            if stock not in stock_data_by_symbol:
                stock_data_by_symbol[stock] = {
                    'id': stock.id,
                    'symbol': stock.symbol,
                    'security_id': stock.security_id,
                    'security_name': stock.security_name,
                    'fifty_two_weeks_high': stock.fifty_two_weeks_high,
                    'fifty_two_weeks_low': stock.fifty_two_weeks_low,
                    'data': []
                }
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
            })
        return stock_data_by_symbol
