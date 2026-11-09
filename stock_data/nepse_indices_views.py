"""
NEPSE Indices API Views
Provides endpoints for scraping and retrieving NEPSE indices data.
"""

from datetime import datetime, timedelta
from decimal import Decimal
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny
from django.db.models import Avg, Max, Min, Sum, Count
from django.db.models.functions import TruncMonth, TruncWeek

from .models import NepseIndex
from .nepse_indices_scraper import (
    NepseIndicesScraper,
    save_indices_to_db,
    INDEX_MAPPING
)


class NepseIndicesScrapeView(APIView):
    """
    Scrape NEPSE indices data from nepalstock.com.
    
    POST /api/stock-data/indices/scrape/
    
    Request Body:
    {
        "index_ids": [58, 51, 54],  // Optional: List of index IDs to scrape. If not provided, scrapes all.
        "max_pages": 5,  // Optional: Max pages per index (default: all)
        "target_date": "2026-02-01",  // Optional: Only get data for this specific date (YYYY-MM-DD)
        "save_to_db": true,  // Optional: Save to database (default: true)
        "skip_existing": true  // Optional: Skip existing dates (default: true)
    }
    
    Available Index IDs:
    - 51: Banking SubIndex
    - 52: Hotels And Tourism Index
    - 53: Others Index
    - 54: HydroPower Index
    - 55: Development Bank Index
    - 56: Manufacturing And Processing
    - 57: Sensitive Index
    - 58: NEPSE Index (Main)
    - 59: Non Life Insurance
    - 60: Finance Index
    - 61: Trading Index
    - 62: Float Index
    - 63: Sensitive Float Index
    - 64: Microfinance Index
    - 65: Life Insurance
    - 66: Mutual Fund
    - 67: Investment Index
    
    Example - Scrape only today's data for all indices:
    {
        "target_date": "2026-02-02"
    }
    
    Example - Scrape specific date for specific indices:
    {
        "index_ids": [58, 51],
        "target_date": "2026-02-01"
    }
    """

    def get(self, request):
        """Return available indices information."""
        return Response({
            'available_indices': [
                {'id': id_val, 'name': name}
                for id_val, name in INDEX_MAPPING.items()
            ],
            'usage': {
                'method': 'POST',
                'body': {
                    'index_ids': 'Optional list of index IDs (scrapes all if not provided)',
                    'max_pages': 'Optional max pages per index',
                    'target_date': 'Optional date (YYYY-MM-DD) to get data for specific date only',
                    'save_to_db': 'Optional boolean to save to database (default: true)',
                    'skip_existing': 'Optional boolean to skip existing dates (default: true)'
                },
                'examples': {
                    'scrape_all': {},
                    'scrape_specific_indices': {'index_ids': [58, 51, 54]},
                    'scrape_specific_date': {'target_date': '2026-02-01'},
                    'scrape_specific_date_for_indices': {
                        'index_ids': [58, 51],
                        'target_date': '2026-02-01'
                    }
                }
            }
        })

    def post(self, request):
        """Scrape NEPSE indices data."""
        data = request.data
        
        # Get parameters
        index_ids = data.get('index_ids', None)
        max_pages = data.get('max_pages', None)
        target_date = data.get('target_date', None)
        save_to_db = data.get('save_to_db', True)
        skip_existing = data.get('skip_existing', True)
        
        # Validate target_date format
        if target_date:
            try:
                datetime.strptime(target_date, '%Y-%m-%d')
            except ValueError:
                return Response(
                    {'error': 'Invalid target_date format. Use YYYY-MM-DD (e.g., 2026-02-01)'},
                    status=status.HTTP_400_BAD_REQUEST
                )
        
        # Validate index_ids
        if index_ids:
            if not isinstance(index_ids, list):
                return Response(
                    {'error': 'index_ids must be a list'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            invalid_ids = [id_val for id_val in index_ids if id_val not in INDEX_MAPPING]
            if invalid_ids:
                return Response(
                    {
                        'error': f'Invalid index IDs: {invalid_ids}',
                        'valid_ids': list(INDEX_MAPPING.keys())
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )
        
        try:
            scraper = NepseIndicesScraper()
            results = {}
            db_results = {}
            
            if index_ids and len(index_ids) == 1:
                # Scrape single index
                records = scraper.scrape_single_index(index_ids[0], max_pages, target_date)
                results[index_ids[0]] = records
                
                if save_to_db and records:
                    db_results[index_ids[0]] = save_indices_to_db(records, skip_existing)
            else:
                # Scrape multiple indices
                results = scraper.scrape_all_indices(index_ids, max_pages, target_date)
                
                if save_to_db:
                    for index_id, records in results.items():
                        if records:
                            db_results[index_id] = save_indices_to_db(records, skip_existing)
            
            # Prepare response
            response_data = {
                'success': True,
                'target_date': target_date,
                'summary': {}
            }
            
            total_records = 0
            for index_id, records in results.items():
                index_name = INDEX_MAPPING.get(index_id, f'Index {index_id}')
                record_count = len(records)
                total_records += record_count
                
                response_data['summary'][index_name] = {
                    'index_id': index_id,
                    'records_scraped': record_count,
                    'date_range': {
                        'from': str(min(r['date'] for r in records)) if records else None,
                        'to': str(max(r['date'] for r in records)) if records else None
                    }
                }
                
                if index_id in db_results:
                    response_data['summary'][index_name]['db_stats'] = db_results[index_id]
            
            response_data['total_records_scraped'] = total_records
            
            return Response(response_data, status=status.HTTP_200_OK)
            
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class NepseIndicesDataView(APIView):
    """
    Get NEPSE indices data from database.
    
    GET /api/stock-data/indices/data/
    
    Query Parameters:
    - index_id: Filter by index ID (e.g., 58 for NEPSE Index)
    - index_name: Filter by index name (partial match)
    - date_from: Start date (YYYY-MM-DD)
    - date_to: End date (YYYY-MM-DD)
    - days: Get last N days of data (default: 30)
    - limit: Max records to return (default: 100)
    - offset: Pagination offset
    """

    def get(self, request):
        index_id = request.query_params.get('index_id')
        index_name = request.query_params.get('index_name')
        date_from = request.query_params.get('date_from')
        date_to = request.query_params.get('date_to')
        days = request.query_params.get('days')
        limit = int(request.query_params.get('limit', 100))
        offset = int(request.query_params.get('offset', 0))
        
        queryset = NepseIndex.objects.all()
        
        # Filter by index_id
        if index_id:
            queryset = queryset.filter(index_id=int(index_id))
        
        # Filter by index_name
        if index_name:
            queryset = queryset.filter(index_name__icontains=index_name)
        
        # Date range filter
        if date_from:
            try:
                date_from_obj = datetime.strptime(date_from, '%Y-%m-%d').date()
                queryset = queryset.filter(date__gte=date_from_obj)
            except ValueError:
                return Response(
                    {'error': 'Invalid date_from format. Use YYYY-MM-DD'},
                    status=status.HTTP_400_BAD_REQUEST
                )
        
        if date_to:
            try:
                date_to_obj = datetime.strptime(date_to, '%Y-%m-%d').date()
                queryset = queryset.filter(date__lte=date_to_obj)
            except ValueError:
                return Response(
                    {'error': 'Invalid date_to format. Use YYYY-MM-DD'},
                    status=status.HTTP_400_BAD_REQUEST
                )
        
        # Days filter (if no date range specified)
        if days and not (date_from or date_to):
            days_ago = datetime.now().date() - timedelta(days=int(days))
            queryset = queryset.filter(date__gte=days_ago)
        
        # Order by date descending
        queryset = queryset.order_by('-date', 'index_id')
        
        # Get total count before pagination
        total_count = queryset.count()
        
        # Apply pagination
        records = queryset[offset:offset + limit]
        
        # Serialize data
        data = []
        for record in records:
            data.append({
                'id': record.id,
                'index_id': record.index_id,
                'index_name': record.index_name,
                'date': str(record.date),
                'close': float(record.close),
                'high': float(record.high),
                'low': float(record.low),
                'absolute_change': float(record.absolute_change),
                'percentage_change': float(record.percentage_change),
                'fifty_two_weeks_high': float(record.fifty_two_weeks_high),
                'fifty_two_weeks_low': float(record.fifty_two_weeks_low),
                'turnover_value': float(record.turnover_value),
                'turnover_volume': record.turnover_volume,
                'total_transactions': record.total_transactions,
            })
        
        return Response({
            'total_count': total_count,
            'limit': limit,
            'offset': offset,
            'data': data
        })


class NepseIndicesAnalysisView(APIView):
    """
    Analyze NEPSE indices data.
    
    GET /api/stock-data/indices/analysis/
    
    Query Parameters:
    - index_id: Index ID to analyze (required)
    - days: Analysis period in days (default: 30)
    - period: 'daily', 'weekly', 'monthly' aggregation
    """

    def get(self, request):
        index_id = request.query_params.get('index_id')
        days = int(request.query_params.get('days', 30))
        period = request.query_params.get('period', 'daily')
        
        if not index_id:
            return Response(
                {'error': 'index_id is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        index_id = int(index_id)
        
        if index_id not in INDEX_MAPPING:
            return Response(
                {
                    'error': f'Invalid index_id: {index_id}',
                    'valid_ids': list(INDEX_MAPPING.keys())
                },
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Get data for the period
        date_from = datetime.now().date() - timedelta(days=days)
        queryset = NepseIndex.objects.filter(
            index_id=index_id,
            date__gte=date_from
        ).order_by('-date')
        
        if not queryset.exists():
            return Response({
                'index_id': index_id,
                'index_name': INDEX_MAPPING.get(index_id),
                'message': 'No data available for this period'
            })
        
        # Calculate basic statistics
        stats = queryset.aggregate(
            avg_close=Avg('close'),
            max_close=Max('close'),
            min_close=Min('close'),
            avg_volume=Avg('turnover_volume'),
            total_volume=Sum('turnover_volume'),
            avg_turnover=Avg('turnover_value'),
            total_turnover=Sum('turnover_value'),
            avg_transactions=Avg('total_transactions'),
            total_transactions=Sum('total_transactions'),
            max_percentage_change=Max('percentage_change'),
            min_percentage_change=Min('percentage_change'),
            trading_days=Count('id'),
        )
        
        # Get latest and oldest records
        latest = queryset.first()
        oldest = queryset.last()
        
        # Calculate period return
        period_return = None
        if latest and oldest and oldest.close > 0:
            period_return = ((latest.close - oldest.close) / oldest.close) * 100
        
        # Get positive and negative days
        positive_days = queryset.filter(percentage_change__gt=0).count()
        negative_days = queryset.filter(percentage_change__lt=0).count()
        unchanged_days = queryset.filter(percentage_change=0).count()
        
        # 52-week high/low analysis
        distance_from_high = None
        distance_from_low = None
        if latest:
            if latest.fifty_two_weeks_high > 0:
                distance_from_high = ((latest.close - latest.fifty_two_weeks_high) / latest.fifty_two_weeks_high) * 100
            if latest.fifty_two_weeks_low > 0:
                distance_from_low = ((latest.close - latest.fifty_two_weeks_low) / latest.fifty_two_weeks_low) * 100
        
        # Trend analysis (simple)
        trend = 'neutral'
        if latest and oldest:
            if latest.close > oldest.close:
                trend = 'uptrend'
            elif latest.close < oldest.close:
                trend = 'downtrend'
        
        response_data = {
            'index_id': index_id,
            'index_name': INDEX_MAPPING.get(index_id),
            'analysis_period': {
                'days': days,
                'date_from': str(oldest.date) if oldest else None,
                'date_to': str(latest.date) if latest else None,
                'trading_days': stats['trading_days'],
            },
            'current': {
                'date': str(latest.date) if latest else None,
                'close': float(latest.close) if latest else None,
                'daily_change': float(latest.absolute_change) if latest else None,
                'daily_change_percent': float(latest.percentage_change) if latest else None,
            },
            'statistics': {
                'avg_close': round(float(stats['avg_close']), 2) if stats['avg_close'] else None,
                'max_close': round(float(stats['max_close']), 2) if stats['max_close'] else None,
                'min_close': round(float(stats['min_close']), 2) if stats['min_close'] else None,
                'period_return_percent': round(float(period_return), 2) if period_return else None,
                'max_daily_gain_percent': round(float(stats['max_percentage_change']), 2) if stats['max_percentage_change'] else None,
                'max_daily_loss_percent': round(float(stats['min_percentage_change']), 2) if stats['min_percentage_change'] else None,
            },
            'volume_analysis': {
                'avg_daily_volume': int(stats['avg_volume']) if stats['avg_volume'] else 0,
                'total_volume': int(stats['total_volume']) if stats['total_volume'] else 0,
                'avg_daily_turnover': round(float(stats['avg_turnover']), 2) if stats['avg_turnover'] else 0,
                'total_turnover': round(float(stats['total_turnover']), 2) if stats['total_turnover'] else 0,
                'avg_daily_transactions': int(stats['avg_transactions']) if stats['avg_transactions'] else 0,
                'total_transactions': int(stats['total_transactions']) if stats['total_transactions'] else 0,
            },
            'market_sentiment': {
                'positive_days': positive_days,
                'negative_days': negative_days,
                'unchanged_days': unchanged_days,
                'positive_ratio': round(positive_days / stats['trading_days'] * 100, 1) if stats['trading_days'] else 0,
                'trend': trend,
            },
            'fifty_two_weeks': {
                'high': float(latest.fifty_two_weeks_high) if latest else None,
                'low': float(latest.fifty_two_weeks_low) if latest else None,
                'distance_from_high_percent': round(float(distance_from_high), 2) if distance_from_high else None,
                'distance_from_low_percent': round(float(distance_from_low), 2) if distance_from_low else None,
            }
        }
        
        return Response(response_data)


class NepseIndicesCompareView(APIView):
    """
    Compare multiple NEPSE indices.
    
    GET /api/stock-data/indices/compare/
    
    Query Parameters:
    - index_ids: Comma-separated list of index IDs (e.g., 58,51,54)
    - days: Comparison period in days (default: 30)
    """

    def get(self, request):
        index_ids_str = request.query_params.get('index_ids')
        days = int(request.query_params.get('days', 30))
        
        if not index_ids_str:
            return Response(
                {
                    'error': 'index_ids is required (comma-separated)',
                    'example': '58,51,54'
                },
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            index_ids = [int(x.strip()) for x in index_ids_str.split(',')]
        except ValueError:
            return Response(
                {'error': 'Invalid index_ids format. Use comma-separated integers'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Validate index IDs
        invalid_ids = [id_val for id_val in index_ids if id_val not in INDEX_MAPPING]
        if invalid_ids:
            return Response(
                {
                    'error': f'Invalid index IDs: {invalid_ids}',
                    'valid_ids': list(INDEX_MAPPING.keys())
                },
                status=status.HTTP_400_BAD_REQUEST
            )
        
        date_from = datetime.now().date() - timedelta(days=days)
        
        comparison = []
        
        for index_id in index_ids:
            queryset = NepseIndex.objects.filter(
                index_id=index_id,
                date__gte=date_from
            ).order_by('-date')
            
            if not queryset.exists():
                comparison.append({
                    'index_id': index_id,
                    'index_name': INDEX_MAPPING.get(index_id),
                    'message': 'No data available'
                })
                continue
            
            latest = queryset.first()
            oldest = queryset.last()
            
            # Calculate period return
            period_return = None
            if latest and oldest and oldest.close > 0:
                period_return = ((latest.close - oldest.close) / oldest.close) * 100
            
            # Get statistics
            stats = queryset.aggregate(
                avg_volume=Avg('turnover_volume'),
                total_turnover=Sum('turnover_value'),
            )
            
            # Count positive days separately (can't use lambda in aggregate filter)
            positive_days = queryset.filter(percentage_change__gt=0).count()
            total_days = queryset.count()
            
            comparison.append({
                'index_id': index_id,
                'index_name': INDEX_MAPPING.get(index_id),
                'current_close': float(latest.close) if latest else None,
                'start_close': float(oldest.close) if oldest else None,
                'period_return_percent': round(float(period_return), 2) if period_return else None,
                'daily_change_percent': float(latest.percentage_change) if latest else None,
                'avg_daily_volume': int(stats['avg_volume']) if stats['avg_volume'] else 0,
                'total_turnover': float(stats['total_turnover']) if stats['total_turnover'] else 0,
                'positive_days_ratio': round(positive_days / total_days * 100, 1) if total_days else 0,
                '52_week_high': float(latest.fifty_two_weeks_high) if latest else None,
                '52_week_low': float(latest.fifty_two_weeks_low) if latest else None,
            })
        
        # Sort by period return
        comparison.sort(key=lambda x: x.get('period_return_percent') or -999, reverse=True)
        
        return Response({
            'comparison_period_days': days,
            'date_from': str(date_from),
            'indices_count': len(comparison),
            'comparison': comparison
        })


class NepseIndicesListView(APIView):
    """
    List all available NEPSE indices with their latest data.
    
    GET /api/stock-data/indices/list/
    """

    def get(self, request):
        indices_list = []
        
        for index_id, index_name in INDEX_MAPPING.items():
            # Get latest record for each index
            latest = NepseIndex.objects.filter(
                index_id=index_id
            ).order_by('-date').first()
            
            # Get record count
            record_count = NepseIndex.objects.filter(index_id=index_id).count()
            
            indices_list.append({
                'index_id': index_id,
                'index_name': index_name,
                'record_count': record_count,
                'latest_date': str(latest.date) if latest else None,
                'latest_close': float(latest.close) if latest else None,
                'high': float(latest.high) if latest else None,
                'low': float(latest.low) if latest else None,
                'daily_change': float(latest.absolute_change) if latest else None,
                'daily_change_percent': float(latest.percentage_change) if latest else None,
                'fifty_two_weeks_high': float(latest.fifty_two_weeks_high) if latest else None,
                'fifty_two_weeks_low': float(latest.fifty_two_weeks_low) if latest else None,
                'turnover_value': float(latest.turnover_value) if latest else None,
                'turnover_volume': latest.turnover_volume if latest else None,
            })
        
        return Response({
            'total_indices': len(indices_list),
            'indices': indices_list
        })
