"""
Views for detecting unusual stock activity patterns.

These views help identify potential accumulation patterns, unusual volume spikes,
and other anomalies that may precede significant price movements.
"""
import logging
from decimal import Decimal
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import pandas as pd
import numpy as np

from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny

from django.db.models import Avg, Max, Min, F, Q
from django.db.models.functions import TruncDate

from .models import Stock, StockData, NepseIndex, StockAnalyticsCache

logger = logging.getLogger(__name__)

DATE_FORMAT = '%Y-%m-%d'


def save_analytics_cache_safe(stock, analysis_date, cache_type, result, max_retries=3):
    """
    Save analytics result to cache with retry logic to handle SQLite database locking.
    
    This is a helper function that can be used by all analytics views to safely
    write to the cache without blocking requests if the database is locked.
    
    Args:
        stock: Stock instance
        analysis_date: Date for analysis
        cache_type: Type of cache ('top_stocks', 'breakout_watchlist', 'accumulation_alerts')
        result: Analytics result to cache
        max_retries: Maximum number of retry attempts (default: 3)
    """
    import time
    from django.db import transaction
    
    for attempt in range(max_retries):
        try:
            with transaction.atomic():
                StockAnalyticsCache.objects.update_or_create(
                    stock=stock,
                    analysis_date=analysis_date,
                    cache_type=cache_type,
                    defaults={'analytics_data': result}
                )
            return  # Success, exit retry loop
        except Exception as e:
            if attempt < max_retries - 1:
                # Wait before retrying (exponential backoff)
                wait_time = (2 ** attempt) * 0.1  # 0.1s, 0.2s, 0.4s
                time.sleep(wait_time)
                continue
            else:
                # Last attempt failed, log but don't raise (non-blocking cache)
                logger.warning(
                    f"Failed to cache analytics for {stock.symbol} "
                    f"({cache_type}, {analysis_date}) after {max_retries} attempts: {e}"
                )
                return  # Don't block the request if caching fails


class UnusualActivityDetectorView(APIView):
    """
    API view for detecting unusual stock activity patterns that may indicate
    accumulation before breakouts (potential insider activity).
    
    This view identifies stocks showing:
    - Unusual volume spikes (significantly above average)
    - Volume increasing while price remains relatively stable
    - Large block trades (higher average trade size)
    - Patterns that historically precede major price movements
    
    Query Parameters:
        days_lookback: Number of days to analyze (default: 30)
        volume_threshold: Volume vs average threshold (default: 1.5 = 150% of avg)
        price_threshold: Max price change % during accumulation (default: 4.0)
        min_volume: Minimum absolute volume to consider (default: 10000)
        
    Returns:
        List of stocks with unusual activity patterns sorted by suspicion score
    """
    permission_classes = [AllowAny]

    def get(self, request):
        """Detect unusual activity patterns across all stocks."""
        try:
            # Parse parameters
            days_lookback = int(request.query_params.get('days_lookback', 30))
            volume_threshold = float(request.query_params.get('volume_threshold', 1.5))
            price_threshold = float(request.query_params.get('price_threshold', 4.0))
            min_volume = int(request.query_params.get('min_volume', 10000))
            
            days_lookback = min(max(days_lookback, 7), 90)
            
        except (ValueError, TypeError):
            days_lookback = 30
            volume_threshold = 1.5
            price_threshold = 4.0
            min_volume = 10000
        
        # Get stock_type filter (default: regular stocks only)
        stock_type = request.query_params.get('stock_type', 'stock')
        
        # Get latest date in the system
        latest_date = StockData.objects.aggregate(latest=Max('date'))['latest']
        if not latest_date:
            return Response(
                {'error': 'No stock data available'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        start_date = latest_date - timedelta(days=days_lookback)
        
        unusual_stocks = []
        # Filter by stock_type (default: regular stocks only)
        stocks = Stock.objects.all()
        if stock_type.lower() != 'all':
            stocks = stocks.filter(stock_type=stock_type)
        
        for stock in stocks:
            result = self._analyze_stock(
                stock, start_date, latest_date,
                volume_threshold, price_threshold, min_volume
            )
            if result:
                unusual_stocks.append(result)
        
        # Sort by suspicion score (highest first)
        unusual_stocks.sort(key=lambda x: x['suspicion_score'], reverse=True)
        
        return Response({
            'analysis_date': str(latest_date),
            'lookback_days': days_lookback,
            'parameters': {
                'volume_threshold': volume_threshold,
                'price_threshold': price_threshold,
                'min_volume': min_volume
            },
            'total_unusual_stocks': len(unusual_stocks),
            'stocks': unusual_stocks
        })
    
    def _analyze_stock(
        self, 
        stock: Stock, 
        start_date, 
        end_date,
        volume_threshold: float,
        price_threshold: float,
        min_volume: int
    ) -> Optional[Dict[str, Any]]:
        """Analyze a single stock for unusual patterns."""
        data = list(StockData.objects.filter(
            stock=stock,
            date__gte=start_date,
            date__lte=end_date
        ).order_by('date').values(
            'date', 'open_price', 'high_price', 'low_price', 'close_price',
            'total_traded_quantity', 'total_traded_value', 'total_trades'
        ))
        
        if len(data) < 10:  # Need minimum data
            return None
        
        df = pd.DataFrame(data)
        
        # Convert to numeric
        for col in ['open_price', 'high_price', 'low_price', 'close_price', 
                    'total_traded_quantity', 'total_traded_value']:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        
        # Calculate metrics
        df['change_pct'] = df['close_price'].pct_change() * 100
        df['volume_5d_avg'] = df['total_traded_quantity'].rolling(5).mean()
        df['volume_10d_avg'] = df['total_traded_quantity'].rolling(10).mean()
        df['volume_vs_avg'] = df['total_traded_quantity'] / df['volume_10d_avg']
        df['avg_trade_size'] = df['total_traded_quantity'] / df['total_trades'].replace(0, 1)
        df['avg_trade_size_5d'] = df['avg_trade_size'].rolling(5).mean()
        df['is_green'] = df['close_price'] > df['open_price']
        
        # Find unusual volume days
        unusual_days = df[
            (df['volume_vs_avg'] >= volume_threshold) &
            (df['total_traded_quantity'] >= min_volume) &
            (df['change_pct'].abs() <= price_threshold)
        ].copy()
        
        if unusual_days.empty:
            return None
        
        # Calculate suspicion score
        suspicion_score = self._calculate_suspicion_score(df, unusual_days, volume_threshold)
        
        if suspicion_score < 20:  # Minimum threshold
            return None
        
        # Get recent unusual events
        recent_unusual = unusual_days.tail(5)
        
        # Check for subsequent price movement after unusual activity
        price_movement = self._check_subsequent_movement(df, unusual_days)
        
        # Get pattern details
        patterns = self._identify_patterns(df, unusual_days)
        
        return {
            'symbol': stock.symbol,
            'security_name': stock.security_name,
            'suspicion_score': round(suspicion_score, 2),
            'current_price': float(df.iloc[-1]['close_price']),
            'latest_date': str(df.iloc[-1]['date']),
            'unusual_activity_days': len(unusual_days),
            'patterns_detected': patterns,
            'price_movement_after': price_movement,
            'recent_unusual_events': [
                {
                    'date': str(row['date']),
                    'close_price': float(row['close_price']),
                    'change_pct': round(float(row['change_pct']), 2) if pd.notna(row['change_pct']) else 0,
                    'volume': int(row['total_traded_quantity']),
                    'volume_vs_avg': round(float(row['volume_vs_avg']), 2) if pd.notna(row['volume_vs_avg']) else 0,
                    'avg_trade_size': round(float(row['avg_trade_size']), 0),
                    'is_green': bool(row['is_green'])
                }
                for _, row in recent_unusual.iterrows()
            ],
            'metrics': {
                'avg_daily_volume': round(float(df['total_traded_quantity'].mean()), 0),
                'max_volume_spike': round(float(unusual_days['volume_vs_avg'].max()), 2) if not unusual_days.empty else 0,
                'avg_trade_size_trend': self._get_trade_size_trend(df),
                'consecutive_unusual_days': self._count_consecutive_unusual(df, volume_threshold)
            }
        }
    
    def _calculate_suspicion_score(
        self, 
        df: pd.DataFrame, 
        unusual_days: pd.DataFrame,
        volume_threshold: float
    ) -> float:
        """
        Calculate a suspicion score based on multiple factors.
        Score ranges from 0-100.
        """
        score = 0
        
        # Factor 1: Number of unusual volume days (max 25 points)
        unusual_count = len(unusual_days)
        score += min(unusual_count * 5, 25)
        
        # Factor 2: Magnitude of volume spikes (max 25 points)
        max_spike = unusual_days['volume_vs_avg'].max() if not unusual_days.empty else 0
        if max_spike >= 3.0:
            score += 25
        elif max_spike >= 2.5:
            score += 20
        elif max_spike >= 2.0:
            score += 15
        elif max_spike >= 1.5:
            score += 10
        
        # Factor 3: Volume increasing trend (max 15 points)
        if len(df) >= 10:
            recent_vol = df['total_traded_quantity'].tail(5).mean()
            older_vol = df['total_traded_quantity'].head(5).mean()
            if older_vol > 0:
                vol_increase = (recent_vol - older_vol) / older_vol
                if vol_increase > 1.0:  # 100% increase
                    score += 15
                elif vol_increase > 0.5:  # 50% increase
                    score += 10
                elif vol_increase > 0.25:  # 25% increase
                    score += 5
        
        # Factor 4: Price stability during accumulation (max 15 points)
        # Lower price volatility during high volume = more suspicious
        if not unusual_days.empty:
            avg_price_change = unusual_days['change_pct'].abs().mean()
            if avg_price_change <= 1.0:
                score += 15
            elif avg_price_change <= 2.0:
                score += 10
            elif avg_price_change <= 3.0:
                score += 5
        
        # Factor 5: Consecutive unusual days (max 10 points)
        consecutive = self._count_consecutive_unusual(df, volume_threshold)
        score += min(consecutive * 3, 10)
        
        # Factor 6: Recent activity (max 10 points)
        # More recent = more relevant
        if not unusual_days.empty:
            last_unusual = unusual_days.iloc[-1]['date']
            days_ago = (df.iloc[-1]['date'] - last_unusual).days
            if days_ago <= 2:
                score += 10
            elif days_ago <= 5:
                score += 7
            elif days_ago <= 10:
                score += 4
        
        return min(score, 100)
    
    def _count_consecutive_unusual(self, df: pd.DataFrame, threshold: float) -> int:
        """Count maximum consecutive days of unusual volume."""
        df_copy = df.copy()
        df_copy['is_unusual'] = df_copy['volume_vs_avg'] >= threshold
        
        max_consecutive = 0
        current_consecutive = 0
        
        for is_unusual in df_copy['is_unusual']:
            if pd.notna(is_unusual) and is_unusual:
                current_consecutive += 1
                max_consecutive = max(max_consecutive, current_consecutive)
            else:
                current_consecutive = 0
        
        return max_consecutive
    
    def _get_trade_size_trend(self, df: pd.DataFrame) -> str:
        """Determine if average trade size is increasing."""
        if len(df) < 10:
            return 'insufficient_data'
        
        recent_avg = df['avg_trade_size'].tail(5).mean()
        older_avg = df['avg_trade_size'].head(5).mean()
        
        if pd.isna(recent_avg) or pd.isna(older_avg) or older_avg == 0:
            return 'unknown'
        
        change = (recent_avg - older_avg) / older_avg
        
        if change > 0.3:
            return 'strongly_increasing'
        elif change > 0.1:
            return 'increasing'
        elif change < -0.3:
            return 'strongly_decreasing'
        elif change < -0.1:
            return 'decreasing'
        return 'stable'
    
    def _check_subsequent_movement(
        self, 
        df: pd.DataFrame, 
        unusual_days: pd.DataFrame
    ) -> Dict[str, Any]:
        """Check price movement after unusual activity."""
        if unusual_days.empty or len(df) < 3:
            return {'detected': False}
        
        # Find first unusual day
        first_unusual_idx = df[df['date'] == unusual_days.iloc[0]['date']].index[0]
        
        # Get data after unusual activity
        after_df = df.iloc[first_unusual_idx:]
        
        if len(after_df) < 2:
            return {'detected': False}
        
        start_price = float(after_df.iloc[0]['close_price'])
        end_price = float(after_df.iloc[-1]['close_price'])
        max_price = float(after_df['close_price'].max())
        min_price = float(after_df['close_price'].min())
        
        total_change = ((end_price - start_price) / start_price) * 100
        max_gain = ((max_price - start_price) / start_price) * 100
        max_loss = ((min_price - start_price) / start_price) * 100
        
        return {
            'detected': abs(total_change) > 5 or abs(max_gain) > 10,
            'total_change_pct': round(total_change, 2),
            'max_gain_pct': round(max_gain, 2),
            'max_loss_pct': round(max_loss, 2),
            'days_analyzed': len(after_df),
            'breakout_confirmed': max_gain > 10
        }
    
    def _identify_patterns(
        self, 
        df: pd.DataFrame, 
        unusual_days: pd.DataFrame
    ) -> List[str]:
        """Identify specific accumulation patterns."""
        patterns = []
        
        if unusual_days.empty:
            return patterns
        
        # Pattern 1: Volume surge with price stability
        high_vol_low_price_change = unusual_days[
            (unusual_days['volume_vs_avg'] >= 2.0) &
            (unusual_days['change_pct'].abs() <= 2.0)
        ]
        if len(high_vol_low_price_change) >= 2:
            patterns.append('VOLUME_ACCUMULATION')
        
        # Pattern 2: Increasing volume trend
        if len(df) >= 10:
            vol_trend = df['total_traded_quantity'].tail(5).mean() / df['total_traded_quantity'].head(5).mean()
            if vol_trend > 1.5:
                patterns.append('VOLUME_TREND_UP')
        
        # Pattern 3: Large block trades
        recent_avg_trade = df['avg_trade_size'].tail(5).mean()
        overall_avg_trade = df['avg_trade_size'].mean()
        if pd.notna(recent_avg_trade) and pd.notna(overall_avg_trade) and overall_avg_trade > 0:
            if recent_avg_trade > overall_avg_trade * 1.5:
                patterns.append('LARGE_BLOCK_TRADES')
        
        # Pattern 4: Consecutive unusual days
        consecutive = self._count_consecutive_unusual(df, 1.5)
        if consecutive >= 3:
            patterns.append('CONSECUTIVE_UNUSUAL_ACTIVITY')
        
        # Pattern 5: Recent spike (within last 3 days)
        recent_df = df.tail(3)
        if (recent_df['volume_vs_avg'] >= 1.5).any():
            patterns.append('RECENT_SPIKE')
        
        # Pattern 6: Green candles with high volume
        green_high_vol = df[(df['is_green']) & (df['volume_vs_avg'] >= 1.5)]
        if len(green_high_vol) >= 3:
            patterns.append('BULLISH_ACCUMULATION')
        
        return patterns


class AccumulationAlertView(APIView):
    """
    API view specifically designed to alert on potential accumulation patterns.
    
    This is a simplified version focused on immediate actionable alerts.
    
    Query Parameters:
        symbol: Optional - specific stock to check
        alert_level: 'high', 'medium', 'all' (default: 'high')
    """
    permission_classes = [AllowAny]

    def get(self, request):
        """Get accumulation alerts."""
        symbol = request.query_params.get('symbol')
        alert_level = request.query_params.get('alert_level', 'high')
        
        date_param = request.query_params.get('date', '').strip()
        
        # Determine analysis date
        if date_param:
            try:
                from datetime import datetime
                analysis_date = datetime.strptime(date_param, '%Y-%m-%d').date()
            except ValueError:
                return Response(
                    {'error': 'Invalid date format. Use YYYY-MM-DD'},
                    status=status.HTTP_400_BAD_REQUEST
                )
        else:
            # Use latest available date
            latest_date = StockData.objects.aggregate(latest=Max('date'))['latest']
            if not latest_date:
                return Response({'error': 'No data available'}, status=status.HTTP_404_NOT_FOUND)
            analysis_date = latest_date
        
        # Get cache parameters
        use_cache = request.query_params.get('use_cache', 'true').lower() == 'true'
        force_recompute = request.query_params.get('force_recompute', 'false').lower() == 'false'
        
        if symbol:
            try:
                stock = Stock.objects.get(symbol__iexact=symbol)
                result = self._get_accumulation_analysis(stock, analysis_date, use_cache, force_recompute)
                return Response(result)
            except Stock.DoesNotExist:
                return Response(
                    {'error': f'Stock {symbol} not found'},
                    status=status.HTTP_404_NOT_FOUND
                )
        
        # Get stock_type filter (default: regular stocks only)
        stock_type = request.query_params.get('stock_type', 'stock')
        date_param = request.query_params.get('date', '').strip()
        
        # Determine analysis date
        if date_param:
            try:
                from datetime import datetime
                analysis_date = datetime.strptime(date_param, '%Y-%m-%d').date()
            except ValueError:
                return Response(
                    {'error': 'Invalid date format. Use YYYY-MM-DD'},
                    status=status.HTTP_400_BAD_REQUEST
                )
        else:
            # Use latest available date
            latest_date = StockData.objects.aggregate(latest=Max('date'))['latest']
            if not latest_date:
                return Response({'error': 'No data available'}, status=status.HTTP_404_NOT_FOUND)
            analysis_date = latest_date
        
        alerts = []
        # Filter by stock_type (default: regular stocks only)
        stocks = Stock.objects.all()
        if stock_type.lower() != 'all':
            stocks = stocks.filter(stock_type=stock_type)
        
        # Get cache parameters
        use_cache = request.query_params.get('use_cache', 'true').lower() == 'true'
        force_recompute = request.query_params.get('force_recompute', 'false').lower() == 'true'
        
        for stock in stocks:
            result = self._get_accumulation_analysis(stock, analysis_date, use_cache, force_recompute)
            if result and result.get('alert'):
                if alert_level == 'all' or result['alert_level'] == alert_level or \
                   (alert_level == 'medium' and result['alert_level'] in ['high', 'medium']):
                    alerts.append(result)
        
        # Sort by alert priority
        priority_order = {'high': 0, 'medium': 1, 'low': 2}
        alerts.sort(key=lambda x: (priority_order.get(x['alert_level'], 3), -x.get('score', 0)))
        
        return Response({
            'date': str(analysis_date),
            'total_alerts': len(alerts),
            'high_alerts': len([a for a in alerts if a['alert_level'] == 'high']),
            'medium_alerts': len([a for a in alerts if a['alert_level'] == 'medium']),
            'alerts': alerts
        })
    
    def _get_accumulation_analysis(self, stock: Stock, analysis_date, use_cache=True, force_recompute=False):
        """
        Get accumulation analysis, using cache if available.
        
        Args:
            stock: Stock instance
            analysis_date: Date for analysis
            use_cache: Whether to use cached results
            force_recompute: Whether to force recomputation
            
        Returns:
            Analysis result dictionary or None
        """
        from .models import StockAnalyticsCache
        
        # Check cache first (unless forcing recompute)
        if use_cache and not force_recompute:
            try:
                cache_entry = StockAnalyticsCache.objects.get(
                    stock=stock,
                    analysis_date=analysis_date,
                    cache_type='accumulation_alerts'
                )
                # Return cached data
                return cache_entry.analytics_data
            except StockAnalyticsCache.DoesNotExist:
                pass
        
        # Compute analysis
        result = self._analyze_single_stock(stock, analysis_date)
        
        # Save to cache if result exists (with retry logic for SQLite locking)
        if result and use_cache:
            save_analytics_cache_safe(stock, analysis_date, 'accumulation_alerts', result)
        
        return result
    
    def _analyze_single_stock(self, stock: Stock, analysis_date) -> Optional[Dict[str, Any]]:
        """Analyze a single stock for accumulation patterns."""
        # Get data up to and including analysis_date
        data = list(StockData.objects.filter(
            stock=stock,
            date__lte=analysis_date
        ).order_by('-date')[:20].values(
            'date', 'open_price', 'high_price', 'low_price', 'close_price',
            'total_traded_quantity', 'total_traded_value', 'total_trades'
        ))
        
        if len(data) < 10:
            return None
        
        df = pd.DataFrame(data)
        df = df.sort_values('date').reset_index(drop=True)
        
        # Convert to numeric
        for col in ['open_price', 'high_price', 'low_price', 'close_price', 'total_traded_quantity']:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        
        # Calculate metrics
        df['volume_avg'] = df['total_traded_quantity'].rolling(10).mean()
        df['volume_ratio'] = df['total_traded_quantity'] / df['volume_avg']
        df['price_change'] = df['close_price'].pct_change() * 100
        
        # Check last 5 days for unusual activity
        recent = df.tail(5)
        
        unusual_days = recent[
            (recent['volume_ratio'] >= 1.5) &
            (recent['price_change'].abs() <= 4.0)
        ]
        
        if unusual_days.empty:
            return None
        
        # Calculate score
        max_ratio = unusual_days['volume_ratio'].max()
        unusual_count = len(unusual_days)
        avg_price_change = unusual_days['price_change'].abs().mean()
        
        score = 0
        score += min(unusual_count * 15, 45)
        score += min((max_ratio - 1) * 20, 35)
        score += max(0, (4 - avg_price_change) * 5)
        
        # Determine alert level
        if score >= 60 or max_ratio >= 2.5:
            alert_level = 'high'
        elif score >= 35 or max_ratio >= 1.8:
            alert_level = 'medium'
        else:
            alert_level = 'low'
        
        latest = df.iloc[-1]
        
        return {
            'alert': True,
            'alert_level': alert_level,
            'symbol': stock.symbol,
            'security_name': stock.security_name,
            'score': round(score, 1),
            'current_price': float(latest['close_price']),
            'date': str(latest['date']),
            'unusual_days_count': unusual_count,
            'max_volume_ratio': round(float(max_ratio), 2),
            'avg_price_change': round(float(avg_price_change), 2),
            'message': self._generate_alert_message(unusual_count, max_ratio, avg_price_change),
            'recent_activity': [
                {
                    'date': str(row['date']),
                    'price': float(row['close_price']),
                    'volume_ratio': round(float(row['volume_ratio']), 2) if pd.notna(row['volume_ratio']) else None,
                    'change_pct': round(float(row['price_change']), 2) if pd.notna(row['price_change']) else None
                }
                for _, row in unusual_days.iterrows()
            ]
        }
    
    def _generate_alert_message(self, count: int, ratio: float, price_change: float) -> str:
        """Generate human-readable alert message."""
        messages = []
        
        if ratio >= 2.5:
            messages.append(f"Volume {ratio:.1f}x above average")
        elif ratio >= 1.8:
            messages.append(f"Volume {ratio:.1f}x above average")
        
        if count >= 3:
            messages.append(f"{count} unusual volume days in last 5 days")
        
        if price_change <= 1.5:
            messages.append("Price stable during accumulation")
        
        return " | ".join(messages) if messages else "Unusual activity detected"


class TopStocksToWatchView(APIView):
    """
    Combined API that aggregates signals from unusual activity detection,
    accumulation alerts, and breakout analysis to give the best stocks to watch.
    
    This is the PRIMARY endpoint for daily monitoring.
    
    Query Parameters:
        symbol: Optional - specific stock symbol or comma-separated list (e.g., "AKJCL" or "AKJCL,RADHI,RFPL")
        limit: Number of stocks to return (default: 20, max: 100) - ignored if symbol is provided
        min_score: Minimum combined score to include (default: 40) - ignored if symbol is provided
        date: Optional - specific date for analysis (YYYY-MM-DD format). Default: latest available date
        use_cache: Optional - use cached results if available (default: true)
        force_recompute: Optional - force recomputation even if cache exists (default: false)
        
    Returns:
        Top N stocks ranked by combined watchability score, or specific stock(s) analysis
    """
    permission_classes = [AllowAny]

    def get(self, request):
        """Get top stocks to watch based on combined analysis."""
        symbol_param = request.query_params.get('symbol', '').strip()
        date_param = request.query_params.get('date', '').strip()
        use_cache = request.query_params.get('use_cache', 'true').lower() == 'true'
        force_recompute = request.query_params.get('force_recompute', 'false').lower() == 'true'
        
        try:
            limit = int(request.query_params.get('limit', 20))
            limit = min(max(limit, 1), 100)
            min_score = float(request.query_params.get('min_score', 40))
        except (ValueError, TypeError):
            limit = 20
            min_score = 40
        
        # Determine analysis date
        if date_param:
            try:
                from datetime import datetime
                analysis_date = datetime.strptime(date_param, '%Y-%m-%d').date()
            except ValueError:
                return Response(
                    {'error': 'Invalid date format. Use YYYY-MM-DD'},
                    status=status.HTTP_400_BAD_REQUEST
                )
        else:
            # Use latest available date
            latest_date = StockData.objects.aggregate(latest=Max('date'))['latest']
            if not latest_date:
                return Response({'error': 'No data available'}, status=status.HTTP_404_NOT_FOUND)
            analysis_date = latest_date
        
        # Get stock_type filter (default: regular stocks only)
        stock_type = request.query_params.get('stock_type', 'stock')
        
        # If specific symbol(s) requested
        if symbol_param:
            return self._analyze_specific_symbols(symbol_param, analysis_date, use_cache, force_recompute)
        
        # Otherwise, analyze all stocks and return top N
        all_stocks = []
        # Filter by stock_type (default: regular stocks only)
        stocks = Stock.objects.all()
        if stock_type.lower() != 'all':
            stocks = stocks.filter(stock_type=stock_type)
        
        for stock in stocks:
            result = self._get_stock_analysis(stock, analysis_date, use_cache, force_recompute, 'top_stocks')
            if result and result['combined_score'] >= min_score:
                all_stocks.append(result)
        
        # Sort by combined score
        all_stocks.sort(key=lambda x: x['combined_score'], reverse=True)
        
        top_stocks = all_stocks[:limit]
        
        return Response({
            'date': str(analysis_date),
            'total_analyzed': len(stocks),
            'stocks_meeting_criteria': len(all_stocks),
            'returned': len(top_stocks),
            'parameters': {
                'limit': limit,
                'min_score': min_score,
                'use_cache': use_cache,
                'force_recompute': force_recompute
            },
            'stocks': top_stocks
        })
    
    def _get_stock_analysis(self, stock: Stock, analysis_date, use_cache=True, force_recompute=False, cache_type='top_stocks'):
        """
        Get stock analysis, using cache if available.
        
        Args:
            stock: Stock instance
            analysis_date: Date for analysis
            use_cache: Whether to use cached results
            force_recompute: Whether to force recomputation
            cache_type: Type of cache ('top_stocks', 'breakout_watchlist', 'accumulation_alerts')
            
        Returns:
            Analysis result dictionary or None
        """
        from .models import StockAnalyticsCache
        
        # Check cache first (unless forcing recompute)
        if use_cache and not force_recompute:
            try:
                cache_entry = StockAnalyticsCache.objects.get(
                    stock=stock,
                    analysis_date=analysis_date,
                    cache_type=cache_type
                )
                # Return cached data
                return cache_entry.analytics_data
            except StockAnalyticsCache.DoesNotExist:
                pass
        
        # Compute analysis based on cache type
        if cache_type == 'top_stocks':
            result = self._analyze_stock_comprehensive(stock, analysis_date)
        else:
            # For other types, we'll compute them separately
            result = None
        
        # Save to cache if result exists (with retry logic for SQLite locking)
        if result and use_cache:
            save_analytics_cache_safe(stock, analysis_date, cache_type, result)
        
        return result
    
    def _analyze_specific_symbols(self, symbol_param: str, analysis_date, use_cache=True, force_recompute=False):
        """Analyze specific stock symbol(s)."""
        # Parse symbols (comma-separated)
        symbols = [s.strip().upper() for s in symbol_param.split(',') if s.strip()]
        
        if not symbols:
            return Response(
                {'error': 'No valid symbols provided'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        results = []
        not_found = []
        no_data = []
        
        for symbol in symbols:
            try:
                stock = Stock.objects.get(symbol__iexact=symbol)
                result = self._get_stock_analysis(stock, analysis_date, use_cache, force_recompute)
                if result:
                    results.append(result)
                else:
                    no_data.append(symbol)
            except Stock.DoesNotExist:
                not_found.append(symbol)
        
        # Sort by combined score
        results.sort(key=lambda x: x['combined_score'], reverse=True)
        
        # If single symbol requested, return simpler response
        if len(symbols) == 1:
            if not_found:
                return Response(
                    {'error': f'Stock "{symbols[0]}" not found'},
                    status=status.HTTP_404_NOT_FOUND
                )
            if no_data:
                return Response(
                    {'error': f'Insufficient data for stock "{symbols[0]}"'},
                    status=status.HTTP_404_NOT_FOUND
                )
            if results:
                return Response({
                    'date': str(analysis_date),
                    'stock': results[0]
                })
        
        # Multiple symbols response
        response_data = {
            'date': str(analysis_date),
            'requested': len(symbols),
            'returned': len(results),
            'stocks': results
        }
        
        if not_found:
            response_data['not_found'] = not_found
        if no_data:
            response_data['insufficient_data'] = no_data
        
        return Response(response_data)
    
    def _analyze_stock_comprehensive(self, stock: Stock, analysis_date) -> Optional[Dict[str, Any]]:
        """
        Perform comprehensive analysis combining all signals.
        
        Args:
            stock: Stock instance
            analysis_date: Date for which to perform analysis (can be historical)
        """
        # Get data up to and including analysis_date
        data = list(StockData.objects.filter(
            stock=stock,
            date__lte=analysis_date
        ).order_by('-date')[:60].values(
            'date', 'open_price', 'high_price', 'low_price', 'close_price',
            'total_traded_quantity', 'total_traded_value', 'total_trades'
        ))
        
        if len(data) < 20:
            return None
        
        df = pd.DataFrame(data)
        df = df.sort_values('date').reset_index(drop=True)
        
        # Convert to numeric
        for col in ['open_price', 'high_price', 'low_price', 'close_price', 
                    'total_traded_quantity', 'total_traded_value']:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        
        # Calculate all metrics
        df['volume_10d_avg'] = df['total_traded_quantity'].rolling(10).mean()
        df['volume_20d_avg'] = df['total_traded_quantity'].rolling(20).mean()
        df['volume_ratio'] = df['total_traded_quantity'] / df['volume_10d_avg']
        df['price_change'] = df['close_price'].pct_change() * 100
        df['sma_20'] = df['close_price'].rolling(20).mean()
        df['sma_50'] = df['close_price'].rolling(50).mean()
        df['resistance_20'] = df['high_price'].rolling(20).max()
        df['support_20'] = df['low_price'].rolling(20).min()
        df['avg_trade_size'] = df['total_traded_quantity'] / df['total_trades'].replace(0, 1)
        df['is_green'] = df['close_price'] > df['open_price']
        
        latest = df.iloc[-1]
        recent_5 = df.tail(5)
        recent_10 = df.tail(10)
        
        # ============================================
        # SCORE 1: Accumulation Score (0-35 points)
        # ============================================
        accumulation_score = 0
        accumulation_signals = []
        
        # Find unusual volume days in last 10 days
        unusual_days = recent_10[
            (recent_10['volume_ratio'] >= 1.5) &
            (recent_10['price_change'].abs() <= 4.0)
        ]
        
        if len(unusual_days) >= 1:
            max_vol_ratio = unusual_days['volume_ratio'].max()
            avg_price_change = unusual_days['price_change'].abs().mean()
            
            # Volume spike score (0-15)
            if max_vol_ratio >= 2.5:
                accumulation_score += 15
                accumulation_signals.append(f'EXTREME_VOLUME_{max_vol_ratio:.1f}x')
            elif max_vol_ratio >= 2.0:
                accumulation_score += 12
                accumulation_signals.append(f'HIGH_VOLUME_{max_vol_ratio:.1f}x')
            elif max_vol_ratio >= 1.5:
                accumulation_score += 8
                accumulation_signals.append(f'ELEVATED_VOLUME_{max_vol_ratio:.1f}x')
            
            # Price stability score (0-10)
            if avg_price_change <= 1.5:
                accumulation_score += 10
                accumulation_signals.append('VERY_STABLE_PRICE')
            elif avg_price_change <= 2.5:
                accumulation_score += 7
                accumulation_signals.append('STABLE_PRICE')
            elif avg_price_change <= 4.0:
                accumulation_score += 4
                accumulation_signals.append('MODERATE_PRICE_MOVE')
            
            # Multiple unusual days score (0-10)
            if len(unusual_days) >= 3:
                accumulation_score += 10
                accumulation_signals.append(f'SUSTAINED_ACCUMULATION_{len(unusual_days)}_DAYS')
            elif len(unusual_days) >= 2:
                accumulation_score += 6
                accumulation_signals.append(f'ACCUMULATION_{len(unusual_days)}_DAYS')
        
        # ============================================
        # SCORE 2: Breakout Readiness Score (0-35 points)
        # ============================================
        breakout_score = 0
        breakout_signals = []
        
        # Near resistance (0-12)
        if pd.notna(latest['resistance_20']) and latest['resistance_20'] > 0:
            distance_to_resistance = (latest['resistance_20'] - latest['close_price']) / latest['resistance_20']
            if distance_to_resistance <= 0.02:
                breakout_score += 12
                breakout_signals.append('AT_RESISTANCE')
            elif distance_to_resistance <= 0.05:
                breakout_score += 8
                breakout_signals.append('NEAR_RESISTANCE')
            elif distance_to_resistance <= 0.10:
                breakout_score += 4
                breakout_signals.append('APPROACHING_RESISTANCE')
        
        # Above moving averages (0-8)
        if pd.notna(latest['sma_20']) and latest['close_price'] > latest['sma_20']:
            breakout_score += 4
            breakout_signals.append('ABOVE_SMA20')
        if pd.notna(latest['sma_50']) and latest['close_price'] > latest['sma_50']:
            breakout_score += 4
            breakout_signals.append('ABOVE_SMA50')
        
        # Volume trend (0-8)
        if len(df) >= 20:
            recent_vol = df.tail(5)['total_traded_quantity'].mean()
            older_vol = df.iloc[-20:-15]['total_traded_quantity'].mean()
            if older_vol > 0:
                vol_change = (recent_vol - older_vol) / older_vol
                if vol_change > 0.5:
                    breakout_score += 8
                    breakout_signals.append('VOLUME_SURGE')
                elif vol_change > 0.25:
                    breakout_score += 5
                    breakout_signals.append('VOLUME_INCREASING')
        
        # Consolidation pattern (0-7)
        price_range = (recent_10['high_price'].max() - recent_10['low_price'].min()) / recent_10['close_price'].mean()
        if price_range <= 0.08:
            breakout_score += 7
            breakout_signals.append('TIGHT_RANGE')
        elif price_range <= 0.12:
            breakout_score += 4
            breakout_signals.append('CONSOLIDATING')
        
        # ============================================
        # SCORE 3: Momentum/Trend Score (0-30 points)
        # ============================================
        momentum_score = 0
        momentum_signals = []
        
        # Recent price performance (0-10)
        if len(df) >= 10:
            price_5d_change = (latest['close_price'] - df.iloc[-6]['close_price']) / df.iloc[-6]['close_price'] * 100
            if 0 < price_5d_change <= 5:
                momentum_score += 10
                momentum_signals.append(f'POSITIVE_MOMENTUM_{price_5d_change:.1f}%')
            elif 5 < price_5d_change <= 10:
                momentum_score += 7
                momentum_signals.append(f'STRONG_MOMENTUM_{price_5d_change:.1f}%')
            elif -3 <= price_5d_change <= 0:
                momentum_score += 5
                momentum_signals.append('STEADY')
        
        # Green candle ratio (0-10)
        green_ratio = recent_10['is_green'].sum() / len(recent_10)
        if green_ratio >= 0.7:
            momentum_score += 10
            momentum_signals.append('BULLISH_CANDLES')
        elif green_ratio >= 0.5:
            momentum_score += 6
            momentum_signals.append('NEUTRAL_CANDLES')
        
        # Large trade size trend (0-10)
        if len(df) >= 15:
            recent_trade_size = df.tail(5)['avg_trade_size'].mean()
            older_trade_size = df.iloc[-15:-10]['avg_trade_size'].mean()
            if older_trade_size > 0 and pd.notna(recent_trade_size) and pd.notna(older_trade_size):
                size_change = (recent_trade_size - older_trade_size) / older_trade_size
                if size_change > 0.3:
                    momentum_score += 10
                    momentum_signals.append('LARGE_BLOCK_TRADES')
                elif size_change > 0.15:
                    momentum_score += 6
                    momentum_signals.append('INCREASING_TRADE_SIZE')
        
        # ============================================
        # COMBINED SCORE
        # ============================================
        combined_score = accumulation_score + breakout_score + momentum_score
        
        if combined_score < 20:
            return None
        
        # Determine alert level
        if combined_score >= 70:
            alert_level = 'STRONG_BUY_SIGNAL'
        elif combined_score >= 55:
            alert_level = 'BUY_SIGNAL'
        elif combined_score >= 40:
            alert_level = 'WATCH_CLOSELY'
        else:
            alert_level = 'MONITOR'
        
        # Get key unusual event details
        recent_unusual = []
        if not unusual_days.empty:
            for _, row in unusual_days.tail(3).iterrows():
                recent_unusual.append({
                    'date': str(row['date']),
                    'price': float(row['close_price']),
                    'volume_ratio': round(float(row['volume_ratio']), 2) if pd.notna(row['volume_ratio']) else None,
                    'price_change': round(float(row['price_change']), 2) if pd.notna(row['price_change']) else None,
                    'is_green': bool(row['is_green'])
                })
        
        return {
            'symbol': stock.symbol,
            'security_name': stock.security_name,
            'combined_score': round(combined_score, 1),
            'alert_level': alert_level,
            'current_price': float(latest['close_price']),
            'date': str(latest['date']),
            
            # Score breakdown
            'score_breakdown': {
                'accumulation': round(accumulation_score, 1),
                'breakout_readiness': round(breakout_score, 1),
                'momentum': round(momentum_score, 1)
            },
            
            # Key metrics
            'key_metrics': {
                'max_volume_ratio': round(float(unusual_days['volume_ratio'].max()), 2) if not unusual_days.empty else None,
                'unusual_days_count': len(unusual_days),
                'distance_to_resistance': round(float((latest['resistance_20'] - latest['close_price']) / latest['resistance_20'] * 100), 2) if pd.notna(latest['resistance_20']) and latest['resistance_20'] > 0 else None,
                'sma_20': round(float(latest['sma_20']), 2) if pd.notna(latest['sma_20']) else None,
                'resistance': round(float(latest['resistance_20']), 2) if pd.notna(latest['resistance_20']) else None,
                'support': round(float(latest['support_20']), 2) if pd.notna(latest['support_20']) else None,
            },
            
            # All signals
            'signals': {
                'accumulation': accumulation_signals,
                'breakout': breakout_signals,
                'momentum': momentum_signals
            },
            
            # Recent unusual activity
            'recent_unusual_activity': recent_unusual,
            
            # Quick summary
            'summary': self._generate_summary(
                accumulation_signals, breakout_signals, momentum_signals,
                combined_score, unusual_days
            )
        }
    
    def _generate_summary(
        self, 
        acc_signals: List[str], 
        brk_signals: List[str], 
        mom_signals: List[str],
        score: float,
        unusual_days: pd.DataFrame
    ) -> str:
        """Generate a human-readable summary."""
        parts = []
        
        # Volume signal
        vol_signals = [s for s in acc_signals if 'VOLUME' in s]
        if vol_signals:
            parts.append(vol_signals[0].replace('_', ' ').title())
        
        # Accumulation days
        acc_days = [s for s in acc_signals if 'ACCUMULATION' in s or 'SUSTAINED' in s]
        if acc_days:
            parts.append(acc_days[0].replace('_', ' ').title())
        
        # Breakout signal
        if 'AT_RESISTANCE' in brk_signals:
            parts.append('At Resistance Level')
        elif 'NEAR_RESISTANCE' in brk_signals:
            parts.append('Near Resistance')
        
        # Momentum
        if 'LARGE_BLOCK_TRADES' in mom_signals:
            parts.append('Institutional Buying')
        if 'BULLISH_CANDLES' in mom_signals:
            parts.append('Bullish Pattern')
        
        if not parts:
            if score >= 50:
                return 'Showing accumulation signals'
            return 'Moderate activity detected'
        
        return ' | '.join(parts[:3])


class VolumeSpikeDetectorView(APIView):
    """
    API view to detect stocks with significant volume spikes.
    
    This is a focused, volume-only analysis that shows:
    - Which stocks had volume spikes of X times or more
    - How many times the spike occurred
    - Which specific days had spikes
    - What the volume was compared to (baseline average)
    - Ranked by highest volume spike ratio
    
    Query Parameters:
        days: Number of recent days to analyze (default: 10, max: 30)
        threshold: Volume multiplier threshold (default: 2.5 = 250% of average)
        baseline_days: Days used to calculate average volume (default: 20)
        symbol: Optional - specific stock or comma-separated list
        min_spikes: Minimum number of spike days to include (default: 1)
        include_mf: Include mutual funds (default: false)
        include_debentures: Include debentures/bonds (default: false)
        limit: Maximum number of results (default: 50)
        
    Returns:
        Stocks with volume spikes ranked by max spike ratio (highest first)
    """
    permission_classes = [AllowAny]
    
    # Keywords to identify mutual funds and debentures (same as StockRecommendationsView)
    EXCLUDE_KEYWORDS_MF = ['fund', 'yojana', 'scheme', 'growth', 'balanced', 'flexi', 'value fund', 'equity fund', 'promotor share','promoter share']
    EXCLUDE_KEYWORDS_DEBENTURE = ['debenture', 'bond', 'certificate']

    def get(self, request):
        """Detect volume spikes in recent days."""
        # Parse parameters
        try:
            days = int(request.query_params.get('days', 10))
            days = min(max(days, 1), 30)
            threshold = float(request.query_params.get('threshold', 2.5))
            baseline_days = int(request.query_params.get('baseline_days', 20))
            baseline_days = min(max(baseline_days, 10), 60)
            min_spikes = int(request.query_params.get('min_spikes', 1))
            include_mf = request.query_params.get('include_mf', 'false').lower() == 'true'
            include_debentures = request.query_params.get('include_debentures', 'false').lower() == 'true'
            limit = int(request.query_params.get('limit', 50))
            limit = min(max(limit, 1), 200)
        except (ValueError, TypeError):
            days = 10
            threshold = 2.5
            baseline_days = 20
            min_spikes = 1
            include_mf = False
            include_debentures = False
            limit = 50
        
        symbol_param = request.query_params.get('symbol', '').strip()
        is_specific_symbol = bool(symbol_param)
        
        latest_date = StockData.objects.aggregate(latest=Max('date'))['latest']
        if not latest_date:
            return Response({'error': 'No data available'}, status=status.HTTP_404_NOT_FOUND)
        
        # Determine which stocks to analyze
        if symbol_param:
            symbols = [s.strip().upper() for s in symbol_param.split(',') if s.strip()]
            stocks = Stock.objects.filter(symbol__in=symbols)
            if not stocks.exists():
                return Response(
                    {'error': f'No stocks found for symbols: {symbols}'},
                    status=status.HTTP_404_NOT_FOUND
                )
        else:
            stocks = Stock.objects.all()
        
        results = []
        excluded_count = {'mutual_funds': 0, 'debentures': 0}
        
        for stock in stocks:
            # Filter out mutual funds and debentures (unless specific symbols or include flags)
            if not is_specific_symbol:
                name_lower = stock.security_name.lower() if stock.security_name else ''
                symbol = stock.symbol or ''
                
                # Check for mutual fund
                is_mf = any(kw in name_lower for kw in self.EXCLUDE_KEYWORDS_MF)
                if is_mf and not include_mf:
                    excluded_count['mutual_funds'] += 1
                    continue
                
                # Check for debenture/bond
                is_debenture = any(kw in name_lower for kw in self.EXCLUDE_KEYWORDS_DEBENTURE)
                # Also check symbol patterns (often debentures have year numbers at end like XXXD2085)
                if not is_debenture and len(symbol) > 4:
                    if symbol[-2:].isdigit() and symbol[-4:-2].isdigit():
                        is_debenture = True
                
                if is_debenture and not include_debentures:
                    excluded_count['debentures'] += 1
                    continue
            
            result = self._analyze_volume_spikes(stock, days, threshold, baseline_days)
            if result and result['spike_count'] >= min_spikes:
                results.append(result)
        
        # Sort by max spike ratio (highest first)
        results.sort(key=lambda x: x['max_spike_ratio'], reverse=True)
        
        # Add rank to each result
        for rank, result in enumerate(results, 1):
            result['rank'] = rank
        
        # Apply limit
        total_before_limit = len(results)
        results = results[:limit]
        
        return Response({
            'date': str(latest_date),
            'parameters': {
                'analysis_days': days,
                'volume_threshold': f'{threshold}x',
                'baseline_days': baseline_days,
                'min_spikes': min_spikes,
                'include_mutual_funds': include_mf,
                'include_debentures': include_debentures,
                'limit': limit
            },
            'summary': {
                'total_stocks_with_spikes': total_before_limit,
                'showing': len(results),
                'excluded_mutual_funds': excluded_count['mutual_funds'],
                'excluded_debentures': excluded_count['debentures']
            },
            'stocks': results
        })
    
    def _analyze_volume_spikes(
        self, 
        stock: Stock, 
        days: int, 
        threshold: float,
        baseline_days: int
    ) -> Optional[Dict[str, Any]]:
        """Analyze volume spikes for a single stock."""
        # Need enough data for baseline + analysis period
        total_days_needed = days + baseline_days + 5  # Extra buffer
        
        data = list(StockData.objects.filter(
            stock=stock
        ).order_by('-date')[:total_days_needed].values(
            'date', 'open_price', 'close_price', 'total_traded_quantity', 'total_trades'
        ))
        
        if len(data) < days + baseline_days:
            return None
        
        df = pd.DataFrame(data)
        df = df.sort_values('date').reset_index(drop=True)
        df['total_traded_quantity'] = pd.to_numeric(df['total_traded_quantity'], errors='coerce')
        df['close_price'] = pd.to_numeric(df['close_price'], errors='coerce')
        df['open_price'] = pd.to_numeric(df['open_price'], errors='coerce')
        
        # Calculate rolling average volume (baseline)
        df['volume_avg'] = df['total_traded_quantity'].rolling(baseline_days).mean()
        df['volume_ratio'] = df['total_traded_quantity'] / df['volume_avg']
        df['price_change_pct'] = ((df['close_price'] - df['open_price']) / df['open_price'] * 100)
        df['is_green'] = df['close_price'] > df['open_price']
        
        # Get recent N days
        recent_df = df.tail(days).copy()
        
        # Find spike days
        spike_days = recent_df[recent_df['volume_ratio'] >= threshold]
        
        if spike_days.empty:
            return None
        
        # Build spike details
        spike_details = []
        for _, row in spike_days.iterrows():
            spike_details.append({
                'date': str(row['date']),
                'volume': int(row['total_traded_quantity']),
                'baseline_avg': int(row['volume_avg']) if pd.notna(row['volume_avg']) else None,
                'spike_ratio': round(float(row['volume_ratio']), 2) if pd.notna(row['volume_ratio']) else None,
                'price_change_pct': round(float(row['price_change_pct']), 2) if pd.notna(row['price_change_pct']) else None,
                'close_price': float(row['close_price']),
                'is_green': bool(row['is_green'])
            })
        
        # Get current stats
        latest = df.iloc[-1]
        current_avg = df['total_traded_quantity'].tail(baseline_days).mean()
        
        return {
            'symbol': stock.symbol,
            'security_name': stock.security_name,
            'current_price': float(latest['close_price']),
            'spike_count': len(spike_days),
            'max_spike_ratio': round(float(spike_days['volume_ratio'].max()), 2),
            'avg_spike_ratio': round(float(spike_days['volume_ratio'].mean()), 2),
            'baseline_avg_volume': int(current_avg) if pd.notna(current_avg) else None,
            'spike_days': spike_details,
            'summary': self._generate_spike_summary(spike_days, threshold)
        }
    
    def _generate_spike_summary(self, spike_days: pd.DataFrame, threshold: float) -> str:
        """Generate human-readable summary."""
        count = len(spike_days)
        max_ratio = spike_days['volume_ratio'].max()
        
        # Check if spikes are mostly green or red
        green_spikes = spike_days['is_green'].sum()
        
        parts = []
        parts.append(f"{count} spike{'s' if count > 1 else ''} >= {threshold}x")
        parts.append(f"Max {max_ratio:.1f}x")
        
        if green_spikes == count:
            parts.append("All bullish")
        elif green_spikes == 0:
            parts.append("All bearish")
        else:
            parts.append(f"{green_spikes}/{count} bullish")
        
        return " | ".join(parts)


class StockRecommendationsView(APIView):
    """
    API view that analyzes stocks and provides actionable buy recommendations.
    Optimized for Nepal market (no short selling, T+2 settlement).
    
    This endpoint:
    - Analyzes NEPSE Index trend to determine market conditions
    - Can analyze ALL stocks or SPECIFIC stocks by symbol
    - Filters out mutual funds, debentures, and bonds (unless requested)
    - Categorizes stocks into STRONG_BUY, BUY, ACCUMULATE, WATCH
    - Provides extended price targets and stop loss levels
    - Adjusts recommendations based on overall market trend
    - Considers T+2 settlement period in recommendations
    
    Query Parameters:
        symbols: Comma-separated stock symbols to analyze (e.g., "NABIL,SCB,HBL")
                 If not provided, analyzes all stocks
        limit: Number of recommendations per category (default: 20)
        include_mf: Include mutual funds (default: false)
        include_debentures: Include debentures (default: false)
        min_score: Minimum score to consider (default: 40, ignored for specific symbols)
        analysis_days: Days to analyze for market trend (default: 30)
        
    Examples:
        GET /api/stock-data/analysis/recommendations/
        GET /api/stock-data/analysis/recommendations/?symbols=NABIL,SCB,HBL
        GET /api/stock-data/analysis/recommendations/?symbols=USHEC&analysis_days=60
        
    Returns:
        Market analysis + Categorized recommendations with targets
    """
    permission_classes = [AllowAny]
    
    # Keywords to identify mutual funds and debentures
    EXCLUDE_KEYWORDS = [
        'fund', 'yojana', 'debenture', 'bond', 'mutual', 'scheme',
        'growth scheme', 'value fund', 'equity fund', 'balanced',
        'fixed deposit', 'unit', 'certificate', 'flexi cap'
    ]
    
    # NEPSE Index ID
    NEPSE_INDEX_ID = 58

    def get(self, request):
        """Get stock recommendations with market context."""
        try:
            limit = int(request.query_params.get('limit', 20))
            limit = min(max(limit, 1), 100)
            min_score = float(request.query_params.get('min_score', 40))
            include_mf = request.query_params.get('include_mf', 'false').lower() == 'true'
            include_debentures = request.query_params.get('include_debentures', 'false').lower() == 'true'
            analysis_days = int(request.query_params.get('analysis_days', 30))
        except (ValueError, TypeError):
            limit = 20
            min_score = 40
            include_mf = False
            include_debentures = False
            analysis_days = 30
        
        # Get specific symbols if provided
        symbols_param = request.query_params.get('symbols', '').strip()
        requested_symbols = []
        if symbols_param:
            # Parse comma-separated symbols, convert to uppercase
            requested_symbols = [s.strip().upper() for s in symbols_param.split(',') if s.strip()]
        
        latest_date = StockData.objects.aggregate(latest=Max('date'))['latest']
        if not latest_date:
            return Response({'error': 'No data available'}, status=status.HTTP_404_NOT_FOUND)
        
        # Analyze NEPSE Index trend
        market_analysis = self._analyze_market_trend(analysis_days)
        market_trend = market_analysis.get('trend', 'neutral')
        market_sentiment = market_analysis.get('sentiment', 'neutral')
        
        # Get stocks to analyze
        top_stocks_view = TopStocksToWatchView()
        all_analyzed = []
        not_found_symbols = []
        
        if requested_symbols:
            # Analyze only requested symbols
            for symbol in requested_symbols:
                try:
                    stock = Stock.objects.get(symbol=symbol)
                    result = top_stocks_view._analyze_stock_comprehensive(stock, latest_date)
                    if result:
                        # For specific symbol requests, include regardless of score
                        all_analyzed.append(result)
                except Stock.DoesNotExist:
                    not_found_symbols.append(symbol)
        else:
            # Analyze all stocks with score filter
            for stock in Stock.objects.all():
                result = top_stocks_view._analyze_stock_comprehensive(stock, latest_date)
                if result and result['combined_score'] >= min_score:
                    all_analyzed.append(result)
        
        # Filter based on parameters (skip filtering for specific symbol requests)
        if requested_symbols:
            filtered_stocks = all_analyzed  # Don't filter out requested symbols
        else:
            filtered_stocks = self._filter_stocks(all_analyzed, include_mf, include_debentures)
        
        # Categorize and add recommendations (considering market trend)
        # Note: Nepal market - no SELL category (no short selling), ACCUMULATE replaces HOLD
        recommendations = self._categorize_stocks(filtered_stocks, market_trend, market_sentiment)
        
        # Limit results - Nepal market categories: strong_buy, buy, accumulate, watch
        # Don't limit if specific symbols were requested
        if not requested_symbols:
            for category in ['strong_buy', 'buy', 'accumulate', 'watch']:
                if category in recommendations:
                    recommendations[category] = recommendations[category][:limit]
        
        # Get top picks (adjusted for market conditions, filtered by upside potential)
        # For specific symbols, show all as top picks
        if requested_symbols:
            top_picks = self._get_top_picks(filtered_stocks, market_trend, limit=len(filtered_stocks))
        else:
            top_picks = self._get_top_picks(filtered_stocks, market_trend, limit=5)
        
        # Generate market-based suggestion
        market_suggestion = self._generate_market_suggestion(market_analysis)
        
        # Get T+2 settlement info
        settlement_info = self._get_settlement_info()
        
        # Build response
        response_data = {
            'date': str(latest_date),
            'market_analysis': market_analysis,
            'market_suggestion': market_suggestion,
            'settlement_info': settlement_info,
            'summary': {
                'total_analyzed': len(all_analyzed),
                'after_filtering': len(filtered_stocks),
                'strong_buy_count': len(recommendations.get('strong_buy', [])),
                'buy_count': len(recommendations.get('buy', [])),
                'accumulate_count': len(recommendations.get('accumulate', [])),
                'watch_count': len(recommendations.get('watch', [])),
                'note': 'No SELL recommendations - short selling not allowed in Nepal'
            },
            'filters_applied': {
                'exclude_mutual_funds': not include_mf if not requested_symbols else 'N/A (specific symbols)',
                'exclude_debentures': not include_debentures if not requested_symbols else 'N/A (specific symbols)',
                'min_score': min_score if not requested_symbols else 'N/A (specific symbols)',
                'analysis_days': analysis_days,
                'min_upside_for_buy': '5% (to justify T+2 settlement)'
            },
            'top_picks': top_picks,
            'strong_buy': recommendations.get('strong_buy', []),
            'buy': recommendations.get('buy', []),
            'accumulate': recommendations.get('accumulate', []),
            'watch': recommendations.get('watch', []),
            'metrics_explanation': self._get_metrics_explanation()
        }
        
        # Add specific symbols info if requested
        if requested_symbols:
            response_data['requested_symbols'] = {
                'symbols': requested_symbols,
                'found': [s['symbol'] for s in all_analyzed],
                'not_found': not_found_symbols,
                'analysis_mode': 'specific_stocks'
            }
        else:
            response_data['analysis_mode'] = 'all_stocks'
        
        return Response(response_data)
    
    def _analyze_market_trend(self, days: int = 30) -> dict:
        """
        Analyze NEPSE Index trend to determine overall market conditions.
        
        Returns market trend analysis including:
        - Trend direction (strong_uptrend, uptrend, neutral, downtrend, strong_downtrend)
        - Market sentiment (bullish, neutral, bearish)
        - Key statistics
        """
        # Get NEPSE Index data
        index_data = NepseIndex.objects.filter(
            index_id=self.NEPSE_INDEX_ID,
            close__gt=0  # Exclude days with 0 close (market not closed)
        ).order_by('-date')[:days]
        
        if not index_data.exists() or index_data.count() < 5:
            return {
                'trend': 'neutral',
                'sentiment': 'neutral',
                'message': 'Insufficient NEPSE Index data for analysis',
                'data_available': False
            }
        
        # Convert to list for processing
        data = list(index_data.values('date', 'close', 'high', 'low', 'percentage_change',
                                       'turnover_value', 'turnover_volume', 'total_transactions',
                                       'fifty_two_weeks_high', 'fifty_two_weeks_low'))
        
        # Sort by date ascending for analysis
        data = sorted(data, key=lambda x: x['date'])
        
        if len(data) < 2:
            return {
                'trend': 'neutral',
                'sentiment': 'neutral',
                'message': 'Insufficient data points',
                'data_available': False
            }
        
        # Calculate key metrics
        latest = data[-1]
        oldest = data[0]
        
        latest_close = float(latest['close'])
        oldest_close = float(oldest['close'])
        
        # Period return
        period_return = ((latest_close - oldest_close) / oldest_close) * 100 if oldest_close > 0 else 0
        
        # Count positive/negative days
        positive_days = sum(1 for d in data if float(d['percentage_change']) > 0)
        negative_days = sum(1 for d in data if float(d['percentage_change']) < 0)
        unchanged_days = len(data) - positive_days - negative_days
        
        # Calculate average daily change
        avg_daily_change = sum(float(d['percentage_change']) for d in data) / len(data)
        
        # Calculate volatility (standard deviation of daily changes)
        changes = [float(d['percentage_change']) for d in data]
        volatility = np.std(changes) if len(changes) > 1 else 0
        
        # Short-term trend (last 5 days)
        short_term_data = data[-5:] if len(data) >= 5 else data
        short_term_return = 0
        if len(short_term_data) >= 2:
            st_latest = float(short_term_data[-1]['close'])
            st_oldest = float(short_term_data[0]['close'])
            short_term_return = ((st_latest - st_oldest) / st_oldest) * 100 if st_oldest > 0 else 0
        
        # Medium-term trend (last 10 days)
        medium_term_data = data[-10:] if len(data) >= 10 else data
        medium_term_return = 0
        if len(medium_term_data) >= 2:
            mt_latest = float(medium_term_data[-1]['close'])
            mt_oldest = float(medium_term_data[0]['close'])
            medium_term_return = ((mt_latest - mt_oldest) / mt_oldest) * 100 if mt_oldest > 0 else 0
        
        # 52-week position
        fifty_two_high = float(latest['fifty_two_weeks_high']) if latest['fifty_two_weeks_high'] else latest_close
        fifty_two_low = float(latest['fifty_two_weeks_low']) if latest['fifty_two_weeks_low'] else latest_close
        distance_from_high = ((fifty_two_high - latest_close) / fifty_two_high) * 100 if fifty_two_high > 0 else 0
        distance_from_low = ((latest_close - fifty_two_low) / fifty_two_low) * 100 if fifty_two_low > 0 else 0
        
        # Determine trend
        trend_score = 0
        
        # Factor 1: Period return (weight: 30%)
        if period_return > 5:
            trend_score += 30
        elif period_return > 2:
            trend_score += 20
        elif period_return > 0:
            trend_score += 10
        elif period_return > -2:
            trend_score -= 10
        elif period_return > -5:
            trend_score -= 20
        else:
            trend_score -= 30
        
        # Factor 2: Short-term momentum (weight: 25%)
        if short_term_return > 2:
            trend_score += 25
        elif short_term_return > 0.5:
            trend_score += 15
        elif short_term_return > -0.5:
            trend_score += 0
        elif short_term_return > -2:
            trend_score -= 15
        else:
            trend_score -= 25
        
        # Factor 3: Positive/Negative days ratio (weight: 20%)
        if positive_days > negative_days * 1.5:
            trend_score += 20
        elif positive_days > negative_days:
            trend_score += 10
        elif positive_days == negative_days:
            trend_score += 0
        elif negative_days > positive_days * 1.5:
            trend_score -= 20
        else:
            trend_score -= 10
        
        # Factor 4: Position relative to 52-week range (weight: 25%)
        if distance_from_high <= 5:
            trend_score += 25
        elif distance_from_high <= 10:
            trend_score += 15
        elif distance_from_high <= 20:
            trend_score += 5
        elif distance_from_low <= 10:
            trend_score -= 15
        elif distance_from_low <= 5:
            trend_score -= 25
        
        # Determine trend category
        if trend_score >= 60:
            trend = 'strong_uptrend'
            sentiment = 'very_bullish'
        elif trend_score >= 30:
            trend = 'uptrend'
            sentiment = 'bullish'
        elif trend_score >= -30:
            trend = 'neutral'
            sentiment = 'neutral'
        elif trend_score >= -60:
            trend = 'downtrend'
            sentiment = 'bearish'
        else:
            trend = 'strong_downtrend'
            sentiment = 'very_bearish'
        
        # Volume analysis
        avg_volume = sum(int(d['turnover_volume']) for d in data) / len(data)
        avg_turnover = sum(float(d['turnover_value']) for d in data) / len(data)
        
        recent_volume = data[-1]['turnover_volume']
        volume_trend = 'normal'
        if recent_volume > avg_volume * 1.5:
            volume_trend = 'high'
        elif recent_volume < avg_volume * 0.7:
            volume_trend = 'low'
        
        return {
            'data_available': True,
            'trend': trend,
            'sentiment': sentiment,
            'trend_score': round(trend_score, 1),
            'analysis_period_days': len(data),
            'current': {
                'date': str(latest['date']),
                'close': round(latest_close, 2),
                'daily_change_percent': round(float(latest['percentage_change']), 2)
            },
            'period_statistics': {
                'period_return_percent': round(period_return, 2),
                'short_term_return_percent': round(short_term_return, 2),
                'medium_term_return_percent': round(medium_term_return, 2),
                'avg_daily_change_percent': round(avg_daily_change, 3),
                'volatility': round(volatility, 3),
                'positive_days': positive_days,
                'negative_days': negative_days,
                'unchanged_days': unchanged_days,
                'positive_ratio_percent': round(positive_days / len(data) * 100, 1)
            },
            '52_week_analysis': {
                'high': round(fifty_two_high, 2),
                'low': round(fifty_two_low, 2),
                'distance_from_high_percent': round(distance_from_high, 2),
                'distance_from_low_percent': round(distance_from_low, 2),
                'position': 'near_high' if distance_from_high <= 10 else ('near_low' if distance_from_low <= 10 else 'middle')
            },
            'volume_analysis': {
                'avg_daily_volume': int(avg_volume),
                'avg_daily_turnover': round(avg_turnover, 2),
                'recent_volume': int(recent_volume),
                'volume_trend': volume_trend
            }
        }
    
    def _generate_market_suggestion(self, market_analysis: dict) -> dict:
        """Generate actionable market suggestion based on trend analysis."""
        if not market_analysis.get('data_available', False):
            return {
                'overall_advice': 'WAIT',
                'confidence': 'low',
                'reason': 'Insufficient market data for analysis',
                'strategy': 'Wait for more market data before making decisions'
            }
        
        trend = market_analysis.get('trend', 'neutral')
        sentiment = market_analysis.get('sentiment', 'neutral')
        trend_score = market_analysis.get('trend_score', 0)
        period_return = market_analysis.get('period_statistics', {}).get('period_return_percent', 0)
        short_term_return = market_analysis.get('period_statistics', {}).get('short_term_return_percent', 0)
        volatility = market_analysis.get('period_statistics', {}).get('volatility', 0)
        position = market_analysis.get('52_week_analysis', {}).get('position', 'middle')
        
        suggestion = {
            'overall_advice': '',
            'confidence': '',
            'reason': '',
            'strategy': '',
            'risk_level': '',
            'recommended_allocation': {},
            'sector_preference': []
        }
        
        if trend == 'strong_uptrend':
            suggestion['overall_advice'] = 'AGGRESSIVE_BUY'
            suggestion['confidence'] = 'high'
            suggestion['reason'] = f'Market in strong uptrend with {period_return:.1f}% gain. Momentum favors buyers.'
            suggestion['strategy'] = 'Increase equity exposure. Focus on high-beta stocks and growth sectors.'
            suggestion['risk_level'] = 'moderate'
            suggestion['recommended_allocation'] = {'equity': '70-80%', 'cash': '20-30%'}
            suggestion['sector_preference'] = ['Banking', 'Hydropower', 'Finance', 'Microfinance']
            
        elif trend == 'uptrend':
            suggestion['overall_advice'] = 'BUY'
            suggestion['confidence'] = 'medium-high'
            suggestion['reason'] = f'Market trending up with {period_return:.1f}% gain. Generally favorable for buying.'
            suggestion['strategy'] = 'Gradually build positions in quality stocks. Use dips to accumulate.'
            suggestion['risk_level'] = 'moderate'
            suggestion['recommended_allocation'] = {'equity': '60-70%', 'cash': '30-40%'}
            suggestion['sector_preference'] = ['Banking', 'Hydropower', 'Insurance']
            
        elif trend == 'neutral':
            suggestion['overall_advice'] = 'SELECTIVE_BUY'
            suggestion['confidence'] = 'medium'
            suggestion['reason'] = 'Market is range-bound. Be selective with stock picks.'
            suggestion['strategy'] = 'Focus on individual stock fundamentals. Avoid aggressive positions.'
            suggestion['risk_level'] = 'moderate'
            suggestion['recommended_allocation'] = {'equity': '50-60%', 'cash': '40-50%'}
            suggestion['sector_preference'] = ['Defensive sectors', 'Dividend stocks']
            
            if short_term_return > 0:
                suggestion['reason'] += ' Short-term momentum is positive.'
            elif short_term_return < 0:
                suggestion['reason'] += ' Short-term momentum is negative - be cautious.'
            
        elif trend == 'downtrend':
            suggestion['overall_advice'] = 'CAUTIOUS'
            suggestion['confidence'] = 'medium-high'
            suggestion['reason'] = f'Market in downtrend with {period_return:.1f}% decline. Protect capital.'
            suggestion['strategy'] = 'Reduce exposure. Hold quality stocks only. Keep cash for opportunities.'
            suggestion['risk_level'] = 'high'
            suggestion['recommended_allocation'] = {'equity': '30-40%', 'cash': '60-70%'}
            suggestion['sector_preference'] = ['Defensive', 'Low-beta stocks']
            
        else:  # strong_downtrend
            suggestion['overall_advice'] = 'AVOID_BUYING'
            suggestion['confidence'] = 'high'
            suggestion['reason'] = f'Market in strong downtrend with {period_return:.1f}% decline. High risk of further losses.'
            suggestion['strategy'] = 'Minimize exposure. Consider exiting weak positions. Preserve capital.'
            suggestion['risk_level'] = 'very_high'
            suggestion['recommended_allocation'] = {'equity': '20-30%', 'cash': '70-80%'}
            suggestion['sector_preference'] = ['Cash', 'Fixed income']
        
        # Add volatility warning
        if volatility > 2:
            suggestion['volatility_warning'] = 'High market volatility - expect larger price swings. Use smaller position sizes.'
        elif volatility > 1.5:
            suggestion['volatility_warning'] = 'Elevated volatility - be prepared for fluctuations.'
        
        # Add 52-week position context
        if position == 'near_high':
            suggestion['position_context'] = 'Market near 52-week highs. Strong momentum but potential for pullback.'
        elif position == 'near_low':
            suggestion['position_context'] = 'Market near 52-week lows. Could be buying opportunity if trend reverses.'
        
        return suggestion
    
    def _filter_stocks(self, stocks: list, include_mf: bool, include_debentures: bool) -> list:
        """Filter out mutual funds and debentures based on parameters."""
        filtered = []
        
        for stock in stocks:
            name_lower = stock['security_name'].lower()
            symbol = stock['symbol']
            
            # Check for mutual fund
            is_mf = any(kw in name_lower for kw in ['fund', 'yojana', 'scheme', 'growth', 'balanced', 'flexi'])
            
            # Check for debenture/bond
            is_debenture = any(kw in name_lower for kw in ['debenture', 'bond', 'certificate'])
            
            # Also check symbol patterns (often debentures have numbers at end)
            if not is_debenture and len(symbol) > 4:
                # Check if ends with year-like numbers
                if symbol[-2:].isdigit() and symbol[-4:-2].isdigit():
                    is_debenture = True
            
            # Apply filters
            if is_mf and not include_mf:
                continue
            if is_debenture and not include_debentures:
                continue
            
            filtered.append(stock)
        
        return filtered
    
    def _categorize_stocks(self, stocks: list, market_trend: str = 'neutral', market_sentiment: str = 'neutral') -> dict:
        """
        Categorize stocks into STRONG_BUY, BUY, ACCUMULATE, WATCH with recommendations.
        Adjusted for Nepal market (no short selling, T+2 settlement).
        
        Nepal Market Context:
        - No short selling allowed - removed SELL category
        - T+2 settlement: Buy Sunday -> Available Wednesday
        - Focus on meaningful upside (5%+) due to settlement period
        """
        strong_buy = []
        buy = []
        accumulate = []  # Renamed from 'hold' - for gradual position building
        watch = []
        
        # Minimum upside threshold - must justify T+2 wait period
        MIN_UPSIDE_PERCENT = 5.0
        MIN_RISK_REWARD = 1.0  # At least 1:1
        
        # Adjust thresholds based on market trend
        trend_adjustments = {
            'strong_uptrend': {'score_bonus': 10, 'buy_threshold': 70, 'strong_buy_threshold': 80},
            'uptrend': {'score_bonus': 5, 'buy_threshold': 72, 'strong_buy_threshold': 82},
            'neutral': {'score_bonus': 0, 'buy_threshold': 75, 'strong_buy_threshold': 85},
            'downtrend': {'score_bonus': -5, 'buy_threshold': 80, 'strong_buy_threshold': 90},
            'strong_downtrend': {'score_bonus': -10, 'buy_threshold': 85, 'strong_buy_threshold': 95}
        }
        
        adjustment = trend_adjustments.get(market_trend, trend_adjustments['neutral'])
        
        for s in stocks:
            score = s['combined_score']
            km = s['key_metrics']
            vol_ratio = km.get('max_volume_ratio') or 0
            dist_to_res = km.get('distance_to_resistance') or 100
            unusual_days = km.get('unusual_days_count') or 0
            acc_score = s['score_breakdown']['accumulation']
            
            # Adjusted score based on market conditions
            adjusted_score = score + adjustment['score_bonus']
            s['adjusted_score'] = round(adjusted_score, 1)
            s['market_adjustment'] = adjustment['score_bonus']
            
            # Generate recommendation with extended targets for Nepal market
            recommendation = self._generate_recommendation(s, market_trend)
            s['recommendation'] = recommendation
            
            # Get upside from recommendation (uses extended targets)
            upside = recommendation.get('upside_percent') or 0
            risk_reward = recommendation.get('risk_reward_ratio') or 0
            
            # Add market context
            s['market_context'] = {
                'trend': market_trend,
                'sentiment': market_sentiment,
                'recommendation_adjusted': adjustment['score_bonus'] != 0
            }
            
            # Add T+2 settlement context
            s['settlement_info'] = self._get_settlement_info()
            
            # Check if meets minimum upside requirements for Nepal market
            meets_upside_requirement = upside >= MIN_UPSIDE_PERCENT or risk_reward >= MIN_RISK_REWARD
            
            # Categorization logic - No SELL category (no shorting in Nepal)
            if market_trend in ['strong_downtrend']:
                # In strong downtrend, be very conservative - only WATCH or ACCUMULATE
                if score >= 90 and dist_to_res <= 3 and vol_ratio >= 3.0 and meets_upside_requirement:
                    s['category'] = 'ACCUMULATE'
                    s['action'] = 'Strong signals despite market - Small positions only'
                    s['market_warning'] = 'Market in strong downtrend - accumulate slowly, T+2 risk higher'
                    accumulate.append(s)
                else:
                    s['category'] = 'WATCH'
                    s['action'] = 'Wait for market reversal - Do not buy in falling market'
                    s['market_warning'] = 'Avoid new positions until market stabilizes'
                    watch.append(s)
                    
            elif market_trend == 'downtrend':
                # In downtrend, be conservative
                if score >= adjustment['strong_buy_threshold'] and dist_to_res <= 3 and vol_ratio >= 2.5 and meets_upside_requirement:
                    s['category'] = 'ACCUMULATE'
                    s['action'] = 'Accumulate in parts - Market weak but stock strong'
                    s['market_warning'] = 'Buy in 2-3 tranches due to market uncertainty'
                    accumulate.append(s)
                elif score >= adjustment['buy_threshold'] and vol_ratio >= 3.0:
                    s['category'] = 'WATCH'
                    s['action'] = 'Good candidate - Wait for market support'
                    watch.append(s)
                else:
                    s['category'] = 'WATCH'
                    s['action'] = 'Monitor - Avoid new positions in weak market'
                    watch.append(s)
                    
            elif market_trend == 'neutral':
                # Normal categorization with upside filter
                if score >= adjustment['strong_buy_threshold'] and dist_to_res <= 5 and vol_ratio >= 2.0:
                    if meets_upside_requirement:
                        s['category'] = 'STRONG_BUY'
                        s['action'] = 'Buy now - Breakout potential with good upside'
                        strong_buy.append(s)
                    else:
                        s['category'] = 'WATCH'
                        s['action'] = 'Near resistance - Limited upside, wait for breakout'
                        s['skip_reason'] = f'Upside only {upside:.1f}% - need 5%+ for T+2 risk'
                        watch.append(s)
                elif score >= adjustment['buy_threshold'] and (vol_ratio >= 3.0 or unusual_days >= 4):
                    if meets_upside_requirement:
                        s['category'] = 'BUY'
                        s['action'] = 'Good entry - Accumulation with upside potential'
                        buy.append(s)
                    else:
                        s['category'] = 'ACCUMULATE'
                        s['action'] = 'Build position slowly - Limited immediate upside'
                        accumulate.append(s)
                elif score >= 80:
                    if meets_upside_requirement:
                        s['category'] = 'BUY'
                        s['action'] = 'Consider buying - Strong signals'
                        buy.append(s)
                    else:
                        s['category'] = 'WATCH'
                        s['action'] = 'Good stock but wait for better entry'
                        watch.append(s)
                else:
                    s['category'] = 'WATCH'
                    s['action'] = 'Monitor for stronger signals'
                    watch.append(s)
                    
            elif market_trend == 'uptrend':
                # In uptrend, be more aggressive but still filter by upside
                if score >= adjustment['strong_buy_threshold'] and dist_to_res <= 7 and vol_ratio >= 1.5:
                    if meets_upside_requirement:
                        s['category'] = 'STRONG_BUY'
                        s['action'] = 'Buy now - Market momentum supports upside'
                        strong_buy.append(s)
                    else:
                        s['category'] = 'BUY'
                        s['action'] = 'Buy - May break resistance with market support'
                        buy.append(s)
                elif score >= adjustment['buy_threshold'] and (vol_ratio >= 2.0 or unusual_days >= 3):
                    s['category'] = 'BUY'
                    s['action'] = 'Good entry - Market and stock aligned'
                    buy.append(s)
                elif score >= 70:
                    s['category'] = 'BUY'
                    s['action'] = 'Consider buying - Market supportive'
                    buy.append(s)
                else:
                    s['category'] = 'WATCH'
                    s['action'] = 'Monitor - Could rally with market'
                    watch.append(s)
                    
            else:  # strong_uptrend
                # In strong uptrend, be aggressive
                if score >= adjustment['strong_buy_threshold'] and dist_to_res <= 10 and vol_ratio >= 1.5:
                    s['category'] = 'STRONG_BUY'
                    s['action'] = 'Aggressive buy - Strong rally expected'
                    strong_buy.append(s)
                elif score >= adjustment['buy_threshold']:
                    s['category'] = 'STRONG_BUY'
                    s['action'] = 'Buy - Ride the market momentum'
                    strong_buy.append(s)
                elif score >= 65 and vol_ratio >= 1.5:
                    s['category'] = 'BUY'
                    s['action'] = 'Buy - Rising market lifts all stocks'
                    buy.append(s)
                else:
                    s['category'] = 'BUY'
                    s['action'] = 'Consider buying - Very favorable conditions'
                    buy.append(s)
        
        # Sort each category by adjusted score
        strong_buy.sort(key=lambda x: x.get('adjusted_score', x['combined_score']), reverse=True)
        buy.sort(key=lambda x: x.get('adjusted_score', x['combined_score']), reverse=True)
        accumulate.sort(key=lambda x: x.get('adjusted_score', x['combined_score']), reverse=True)
        watch.sort(key=lambda x: x.get('adjusted_score', x['combined_score']), reverse=True)
        
        return {
            'strong_buy': strong_buy,
            'buy': buy,
            'accumulate': accumulate,  # Renamed from 'hold'
            'watch': watch
        }
    
    def _get_settlement_info(self) -> dict:
        """
        Get T+2 settlement information for Nepal market.
        Trading days: Sunday-Thursday (Friday is holiday)
        """
        today = datetime.now()
        day_of_week = today.weekday()  # 0=Monday, 6=Sunday
        
        # Nepal trading days mapping (Sunday=6 is trading, Friday=4 is holiday)
        # weekday(): Mon=0, Tue=1, Wed=2, Thu=3, Fri=4, Sat=5, Sun=6
        
        settlement_map = {
            6: {'buy_day': 'Sunday', 'available_day': 'Wednesday', 'trading_days_wait': 2},
            0: {'buy_day': 'Monday', 'available_day': 'Thursday', 'trading_days_wait': 2},
            1: {'buy_day': 'Tuesday', 'available_day': 'Sunday', 'trading_days_wait': 2},
            2: {'buy_day': 'Wednesday', 'available_day': 'Monday', 'trading_days_wait': 2},
            3: {'buy_day': 'Thursday', 'available_day': 'Tuesday', 'trading_days_wait': 3},  # Friday gap
        }
        
        info = settlement_map.get(day_of_week, {'buy_day': 'N/A', 'available_day': 'T+2', 'trading_days_wait': 2})
        
        return {
            'rule': 'T+2 Settlement',
            'explanation': 'Shares bought today will be available for trading after 2 trading days',
            'current_day': today.strftime('%A'),
            **info,
            'implication': 'Price may move during settlement period - factor this into entry decision'
        }
    
    def _generate_recommendation(self, stock: dict, market_trend: str = 'neutral') -> dict:
        """
        Generate detailed recommendation for a stock with market context.
        Optimized for Nepal market with extended targets and T+2 settlement consideration.
        """
        km = stock['key_metrics']
        price = stock['current_price']
        resistance_20d = km.get('resistance')  # 20-day high
        support_20d = km.get('support')  # 20-day low
        vol_ratio = km.get('max_volume_ratio') or 0
        unusual_days = km.get('unusual_days_count') or 0
        
        # Calculate extended targets for meaningful upside (Nepal market needs 5%+ to justify T+2)
        targets = self._calculate_extended_targets(price, resistance_20d, support_20d, market_trend)
        
        rec = {
            'entry_price': price,
            # Use extended target instead of just 20-day resistance
            'target_price': targets['primary_target'],
            'extended_target': targets['extended_target'],
            'conservative_target': targets['conservative_target'],
            'stop_loss': targets['stop_loss'],
            'trailing_stop': targets['trailing_stop'],
            'upside_percent': targets['upside_percent'],
            'extended_upside_percent': targets['extended_upside_percent'],
            'downside_percent': targets['downside_percent'],
            'risk_reward_ratio': targets['risk_reward_ratio'],
            'position_size': 'normal',
            'entry_strategy': '',
            'reasons': [],
            'warnings': [],
            'market_considerations': [],
            't2_consideration': ''
        }
        
        # T+2 Settlement consideration
        rec['t2_consideration'] = self._get_t2_advice(targets['upside_percent'], market_trend)
        
        # Adjust position size based on market trend
        if market_trend == 'strong_uptrend':
            rec['position_size'] = 'full'
            rec['entry_strategy'] = 'Buy full position - momentum strong'
            rec['market_considerations'].append('Strong market momentum - full position justified')
        elif market_trend == 'uptrend':
            rec['position_size'] = 'normal'
            rec['entry_strategy'] = 'Buy normal position'
            rec['market_considerations'].append('Market favorable - standard position size')
        elif market_trend == 'neutral':
            rec['position_size'] = 'normal'
            rec['entry_strategy'] = 'Buy in 2 parts - 60% now, 40% on confirmation'
            rec['market_considerations'].append('Market neutral - consider splitting entry')
        elif market_trend == 'downtrend':
            rec['position_size'] = 'half'
            rec['entry_strategy'] = 'Buy in 3 parts - 33% each on dips'
            rec['market_considerations'].append('Market weak - accumulate in parts')
            rec['warnings'].append('Market weakness - use strict stop loss')
        else:  # strong_downtrend
            rec['position_size'] = 'quarter'
            rec['entry_strategy'] = 'Small test position only - wait for reversal'
            rec['market_considerations'].append('Very weak market - minimal exposure only')
            rec['warnings'].append('High risk - wait for market stabilization preferred')
        
        # Generate reasons
        if vol_ratio >= 4:
            rec['reasons'].append(f'Extreme volume spike ({vol_ratio:.1f}x) indicates strong institutional accumulation')
        elif vol_ratio >= 2.5:
            rec['reasons'].append(f'High volume ({vol_ratio:.1f}x) suggests smart money entering')
        elif vol_ratio >= 1.5:
            rec['reasons'].append(f'Above average volume ({vol_ratio:.1f}x) shows increasing interest')
        
        if unusual_days >= 5:
            rec['reasons'].append(f'Sustained accumulation for {unusual_days} days - strong conviction buying')
        elif unusual_days >= 3:
            rec['reasons'].append(f'Multiple days ({unusual_days}) of unusual activity - pattern forming')
        
        dist_to_res = km.get('distance_to_resistance')
        if dist_to_res is not None:
            if dist_to_res <= 2:
                rec['reasons'].append('At breakout level - potential for extended rally')
            elif dist_to_res <= 5:
                rec['reasons'].append('Near resistance - breakout could trigger momentum buying')
        
        if stock['score_breakdown']['accumulation'] >= 30:
            rec['reasons'].append('Strong accumulation pattern - big players building position')
        
        if 'LARGE_BLOCK_TRADES' in stock['signals'].get('momentum', []):
            rec['reasons'].append('Large block trades indicate institutional buying')
        
        if 'BULLISH_CANDLES' in stock['signals'].get('momentum', []):
            rec['reasons'].append('Bullish candle pattern supports upside')
        
        # Add breakout potential reason if near resistance with volume
        if dist_to_res is not None and dist_to_res <= 5 and vol_ratio >= 2.0:
            rec['reasons'].append(f'Breakout setup: Near resistance with {vol_ratio:.1f}x volume - extended target {targets["extended_target"]:.0f} possible')
        
        # Generate warnings
        if vol_ratio >= 8:
            rec['warnings'].append('Extremely high volume - verify news, could be operator activity')
        
        if unusual_days == 1 and vol_ratio >= 5:
            rec['warnings'].append('Single day spike - wait for 1-2 days confirmation')
        
        recent_activity = stock.get('recent_unusual_activity', [])
        red_days = sum(1 for a in recent_activity if not a.get('is_green', True))
        if red_days > len(recent_activity) / 2:
            rec['warnings'].append('Recent activity shows distribution - be cautious')
        
        # T+2 specific warnings
        if targets['upside_percent'] < 5:
            rec['warnings'].append(f"Limited upside ({targets['upside_percent']:.1f}%) - may not justify T+2 wait period")
        
        # Market-specific warnings
        if market_trend in ['downtrend', 'strong_downtrend']:
            if vol_ratio >= 3 and red_days > 0:
                rec['warnings'].append('High volume in weak market could signal distribution')
        
        return rec
    
    def _calculate_extended_targets(self, price: float, resistance_20d: float, support_20d: float, market_trend: str) -> dict:
        """
        Calculate extended price targets for Nepal market.
        Since T+2 settlement requires 2 days wait, we need meaningful upside (5%+).
        Uses Fibonacci extensions and percentage-based targets.
        """
        if not price or price <= 0:
            return {
                'primary_target': None, 'extended_target': None, 'conservative_target': None,
                'stop_loss': None, 'trailing_stop': None, 'upside_percent': 0,
                'extended_upside_percent': 0, 'downside_percent': 0, 'risk_reward_ratio': 0
            }
        
        # Calculate range
        if resistance_20d and support_20d:
            range_size = resistance_20d - support_20d
        else:
            range_size = price * 0.10  # Assume 10% range if not available
        
        # Conservative target: 20-day resistance (immediate target)
        conservative_target = resistance_20d if resistance_20d else price * 1.03
        
        # Primary target: For breakout stocks, use Fibonacci extension or percentage
        # If price is near resistance (within 3%), primary target is extended
        if resistance_20d and price >= resistance_20d * 0.97:
            # Near/at resistance - use Fibonacci 1.618 extension
            primary_target = support_20d + (range_size * 1.618) if support_20d else price * 1.10
        else:
            # Below resistance - target is resistance + buffer for momentum
            primary_target = resistance_20d * 1.05 if resistance_20d else price * 1.08
        
        # Extended target: For strong momentum, use Fibonacci 2.618 or 15% above current
        if market_trend in ['strong_uptrend', 'uptrend']:
            extended_target = support_20d + (range_size * 2.618) if support_20d else price * 1.15
        else:
            extended_target = support_20d + (range_size * 2.0) if support_20d else price * 1.12
        
        # Stop loss: Tighter in weak markets
        if market_trend in ['downtrend', 'strong_downtrend']:
            stop_loss = price * 0.95  # 5% stop
        else:
            stop_loss = support_20d if support_20d else price * 0.93  # 7% stop
        
        # Trailing stop: Lock profits as price moves up
        trailing_stop = price * 0.97  # Move up with price, 3% trail
        
        # Calculate percentages
        upside_percent = round(((primary_target - price) / price) * 100, 2)
        extended_upside_percent = round(((extended_target - price) / price) * 100, 2)
        downside_percent = round(((price - stop_loss) / price) * 100, 2)
        
        # Risk/Reward ratio using primary target
        risk_reward = round(upside_percent / downside_percent, 2) if downside_percent > 0 else 0
        
        return {
            'primary_target': round(primary_target, 2),
            'extended_target': round(extended_target, 2),
            'conservative_target': round(conservative_target, 2),
            'stop_loss': round(stop_loss, 2),
            'trailing_stop': round(trailing_stop, 2),
            'upside_percent': upside_percent,
            'extended_upside_percent': extended_upside_percent,
            'downside_percent': downside_percent,
            'risk_reward_ratio': risk_reward
        }
    
    def _get_t2_advice(self, upside_percent: float, market_trend: str) -> str:
        """Generate T+2 settlement specific advice."""
        if upside_percent >= 10:
            return "Strong upside potential - T+2 wait period well justified"
        elif upside_percent >= 7:
            return "Good upside - T+2 wait acceptable for this opportunity"
        elif upside_percent >= 5:
            return "Moderate upside - T+2 wait reasonable in current market"
        elif upside_percent >= 3:
            if market_trend in ['strong_uptrend', 'uptrend']:
                return "Limited upside but market momentum may help - proceed with caution"
            else:
                return "Limited upside for T+2 wait - consider waiting for better entry"
        else:
            return "Low upside does not justify T+2 settlement risk - wait for pullback or better setup"
    
    def _get_top_picks(self, stocks: list, market_trend: str = 'neutral', limit: int = 5) -> list:
        """
        Get top picks with highest conviction, adjusted for market conditions.
        Optimized for Nepal market with T+2 settlement and no short selling.
        """
        # Market trend multipliers for conviction calculation
        trend_multipliers = {
            'strong_uptrend': 1.2,
            'uptrend': 1.1,
            'neutral': 1.0,
            'downtrend': 0.9,
            'strong_downtrend': 0.8
        }
        multiplier = trend_multipliers.get(market_trend, 1.0)
        
        # Filter stocks with meaningful upside (5%+) for Nepal market T+2 requirement
        viable_stocks = []
        for s in stocks:
            km = s['key_metrics']
            rec = s.get('recommendation', {})
            upside = rec.get('upside_percent', 0)
            risk_reward = rec.get('risk_reward_ratio', 0)
            
            # Only include stocks with good upside potential
            if upside >= 5 or risk_reward >= 1.0:
                # Conviction = score + volume bonus + proximity bonus + upside bonus
                vol_bonus = min((km.get('max_volume_ratio') or 0) * 5, 25)
                prox_bonus = max(0, (10 - (km.get('distance_to_resistance') or 10))) * 2
                days_bonus = min((km.get('unusual_days_count') or 0) * 2, 10)
                
                # NEW: Add upside bonus - reward stocks with better upside potential
                upside_bonus = min(upside * 2, 20)  # Up to 20 points for 10%+ upside
                rr_bonus = min(risk_reward * 5, 15)  # Up to 15 points for good R/R
                
                base_conviction = s['combined_score'] + vol_bonus + prox_bonus + days_bonus + upside_bonus + rr_bonus
                
                # Apply market multiplier
                s['conviction_score'] = base_conviction * multiplier
                viable_stocks.append(s)
        
        # Sort by conviction
        sorted_stocks = sorted(viable_stocks, key=lambda x: x['conviction_score'], reverse=True)
        
        # In bearish markets, only show stocks with very high conviction AND good upside
        if market_trend in ['downtrend', 'strong_downtrend']:
            min_conviction = 100 if market_trend == 'strong_downtrend' else 90
            sorted_stocks = [s for s in sorted_stocks if s['conviction_score'] >= min_conviction]
        
        top_picks = []
        for i, s in enumerate(sorted_stocks[:limit], 1):
            km = s['key_metrics']
            rec = s.get('recommendation', {})
            
            pick = {
                'rank': i,
                'symbol': s['symbol'],
                'security_name': s['security_name'],
                'current_price': s['current_price'],
                'combined_score': s['combined_score'],
                'conviction_score': round(s['conviction_score'], 1),
                'market_adjusted': market_trend != 'neutral',
                
                # Volume and pattern metrics
                'volume_ratio': round(km.get('max_volume_ratio') or 0, 2),
                'unusual_days': km.get('unusual_days_count'),
                'distance_to_resistance': km.get('distance_to_resistance'),
                
                # Extended targets for Nepal market
                'targets': {
                    'conservative': rec.get('conservative_target'),
                    'primary': rec.get('target_price'),
                    'extended': rec.get('extended_target')
                },
                'stop_loss': rec.get('stop_loss'),
                'trailing_stop': rec.get('trailing_stop'),
                
                # Upside/Downside with extended targets
                'upside_percent': rec.get('upside_percent'),
                'extended_upside_percent': rec.get('extended_upside_percent'),
                'downside_percent': rec.get('downside_percent'),
                'risk_reward_ratio': rec.get('risk_reward_ratio'),
                
                # Summary and reasons
                'summary': s['summary'],
                'key_reasons': rec.get('reasons', [])[:3],
                
                # Entry guidance
                'position_size': rec.get('position_size', 'normal'),
                'entry_strategy': rec.get('entry_strategy', ''),
                't2_advice': rec.get('t2_consideration', '')
            }
            
            # Add market-specific note
            if market_trend == 'strong_uptrend':
                pick['market_note'] = 'Strong momentum - aggressive entry justified'
            elif market_trend == 'uptrend':
                pick['market_note'] = 'Favorable conditions - normal position'
            elif market_trend == 'neutral':
                pick['market_note'] = 'Selective buying - focus on high conviction setups'
            elif market_trend == 'downtrend':
                pick['market_note'] = 'Accumulate in parts - use tight stops'
            elif market_trend == 'strong_downtrend':
                pick['market_note'] = 'High risk - small position, wait for reversal signals'
            
            top_picks.append(pick)
        
        # Add guidance if no picks meet criteria
        if not top_picks:
            if market_trend in ['downtrend', 'strong_downtrend']:
                return [{
                    'message': 'No high-conviction picks with adequate upside in weak market',
                    'market_trend': market_trend,
                    'recommendation': 'Preserve capital - wait for market stabilization',
                    't2_note': 'T+2 settlement adds risk in falling markets'
                }]
            else:
                return [{
                    'message': 'No stocks meeting upside criteria (5%+) currently',
                    'market_trend': market_trend,
                    'recommendation': 'Wait for better setups with meaningful upside potential',
                    't2_note': 'Need 5%+ upside to justify T+2 settlement period'
                }]
        
        return top_picks
    
    def _get_metrics_explanation(self) -> dict:
        """Return explanation of all metrics including market trend analysis - Nepal market optimized."""
        return {
            'nepal_market_context': {
                'description': 'Recommendations optimized for Nepal Stock Exchange (NEPSE)',
                'key_rules': {
                    'no_short_selling': 'Short selling is not allowed - only buy recommendations provided',
                    't2_settlement': 'T+2 settlement means shares are available 2 trading days after purchase',
                    'trading_days': 'Market open Sunday-Thursday, Friday is closed',
                    'minimum_upside': '5% upside required to justify T+2 wait period'
                },
                'settlement_examples': {
                    'sunday_buy': 'Available Wednesday',
                    'monday_buy': 'Available Thursday',
                    'tuesday_buy': 'Available Sunday',
                    'wednesday_buy': 'Available Monday',
                    'thursday_buy': 'Available Tuesday (3 calendar days due to Friday holiday)'
                }
            },
            'market_analysis': {
                'description': 'NEPSE Index trend analysis to determine market conditions',
                'trends': {
                    'strong_uptrend': 'Market rallying strongly - Aggressive buying recommended',
                    'uptrend': 'Market moving up - Standard buying conditions',
                    'neutral': 'Market range-bound - Be selective with good upside stocks',
                    'downtrend': 'Market falling - Accumulate best stocks in parts',
                    'strong_downtrend': 'Market correction - Preserve capital, minimal buying'
                },
                'factors': {
                    'period_return': 'Overall return during analysis period (30%)',
                    'short_term_momentum': 'Last 5 days performance (25%)',
                    'positive_negative_ratio': 'Ratio of up days to down days (20%)',
                    '52_week_position': 'Position relative to yearly high/low (25%)'
                }
            },
            'target_calculation': {
                'description': 'Extended targets calculated for meaningful upside',
                'conservative_target': '20-day high - Immediate resistance level',
                'primary_target': 'Fibonacci 1.618 extension or 5-10% above entry for breakout stocks',
                'extended_target': 'Fibonacci 2.618 extension or 12-15% above entry for momentum stocks',
                'why_extended': 'T+2 settlement requires 5%+ upside to justify the wait period'
            },
            'combined_score': {
                'description': 'Overall signal strength (0-100), adjusted for market conditions',
                'ranges': {
                    '85-100': 'STRONG_BUY - Highest conviction with good upside',
                    '70-84': 'BUY - Strong accumulation, adequate upside',
                    '55-69': 'WATCH/ACCUMULATE - Build position slowly',
                    '40-54': 'WATCH - Monitor for better entry'
                },
                'market_adjustments': {
                    'strong_uptrend': '+10 points (more aggressive)',
                    'uptrend': '+5 points',
                    'neutral': 'No adjustment',
                    'downtrend': '-5 points (more conservative)',
                    'strong_downtrend': '-10 points (very conservative)'
                }
            },
            'score_breakdown': {
                'accumulation': 'Volume spikes + Price stability + Duration (max 35)',
                'breakout_readiness': 'Near resistance + Above SMAs + Consolidation (max 35)',
                'momentum': 'Price trend + Candle patterns + Block trades (max 30)'
            },
            'key_metrics': {
                'max_volume_ratio': 'Volume vs 10-day average. >= 2.5x indicates institutional accumulation',
                'unusual_days_count': 'Days with volume spike + stable price. >= 3 shows sustained buying',
                'distance_to_resistance': 'Distance to 20-day high. <= 5% means breakout potential',
                'upside_percent': 'Expected gain to primary target. Need 5%+ for T+2 justification',
                'risk_reward_ratio': 'Upside vs Downside. Prefer >= 1.5 for good trades'
            },
            'recommendation_categories': {
                'STRONG_BUY': 'High conviction + Good upside (8%+) - Full position justified',
                'BUY': 'Good signals + Adequate upside (5%+) - Normal position',
                'ACCUMULATE': 'Good stock, limited upside - Build position in parts over time',
                'WATCH': 'Monitor for better entry or upside expansion'
            },
            'position_sizing': {
                'full': 'Strong uptrend - Take full planned position',
                'normal': 'Standard conditions - Normal position size',
                'half': 'Weak market - 50% position, rest on confirmation',
                'quarter': 'Very weak market - 25% test position only'
            },
            'entry_strategies': {
                'strong_uptrend': 'Buy full position at market open',
                'uptrend': 'Buy normal position, can add on dips',
                'neutral': 'Buy 60% now, 40% on breakout confirmation',
                'downtrend': 'Accumulate in 3 parts on red days',
                'strong_downtrend': 'Small test position, wait for reversal'
            }
        }


class BreakoutWatchlistView(APIView):
    """
    API view to get stocks that show accumulation patterns and may be
    ready for a breakout.
    
    This combines multiple signals:
    1. Recent unusual volume activity
    2. Price consolidation near resistance
    3. Technical breakout signals
    """
    permission_classes = [AllowAny]

    def get(self, request):
        """Get potential breakout candidates."""
        # Get stock_type filter (default: regular stocks only)
        stock_type = request.query_params.get('stock_type', 'stock')
        date_param = request.query_params.get('date', '').strip()
        
        # Determine analysis date
        if date_param:
            try:
                from datetime import datetime
                analysis_date = datetime.strptime(date_param, '%Y-%m-%d').date()
            except ValueError:
                return Response(
                    {'error': 'Invalid date format. Use YYYY-MM-DD'},
                    status=status.HTTP_400_BAD_REQUEST
                )
        else:
            # Use latest available date
            latest_date = StockData.objects.aggregate(latest=Max('date'))['latest']
            if not latest_date:
                return Response({'error': 'No data available'}, status=status.HTTP_404_NOT_FOUND)
            analysis_date = latest_date
        
        watchlist = []
        # Filter by stock_type (default: regular stocks only)
        stocks = Stock.objects.all()
        if stock_type.lower() != 'all':
            stocks = stocks.filter(stock_type=stock_type)
        
        # Get cache parameters
        use_cache = request.query_params.get('use_cache', 'true').lower() == 'true'
        force_recompute = request.query_params.get('force_recompute', 'false').lower() == 'true'
        
        for stock in stocks:
            result = self._get_breakout_analysis(stock, analysis_date, use_cache, force_recompute)
            if result:
                watchlist.append(result)
        
        # Sort by breakout score
        watchlist.sort(key=lambda x: x['breakout_score'], reverse=True)
        
        return Response({
            'date': str(analysis_date),
            'total_candidates': len(watchlist),
            'watchlist': watchlist[:30]  # Top 30
        })
    
    def _get_breakout_analysis(self, stock: Stock, analysis_date, use_cache=True, force_recompute=False):
        """
        Get breakout analysis, using cache if available.
        
        Args:
            stock: Stock instance
            analysis_date: Date for analysis
            use_cache: Whether to use cached results
            force_recompute: Whether to force recomputation
            
        Returns:
            Analysis result dictionary or None
        """
        from .models import StockAnalyticsCache
        
        # Check cache first (unless forcing recompute)
        if use_cache and not force_recompute:
            try:
                cache_entry = StockAnalyticsCache.objects.get(
                    stock=stock,
                    analysis_date=analysis_date,
                    cache_type='breakout_watchlist'
                )
                # Return cached data
                return cache_entry.analytics_data
            except StockAnalyticsCache.DoesNotExist:
                pass
        
        # Compute analysis
        result = self._analyze_breakout_potential(stock, analysis_date)
        
        # Save to cache if result exists (with retry logic for SQLite locking)
        if result and use_cache:
            save_analytics_cache_safe(stock, analysis_date, 'breakout_watchlist', result)
        
        return result
    
    def _analyze_breakout_potential(self, stock: Stock, analysis_date) -> Optional[Dict[str, Any]]:
        """Analyze breakout potential for a stock."""
        data = list(StockData.objects.filter(
            stock=stock,
            date__lte=analysis_date
        ).order_by('-date')[:60].values(
            'date', 'open_price', 'high_price', 'low_price', 'close_price',
            'total_traded_quantity', 'total_traded_value', 'total_trades'
        ))
        
        if len(data) < 30:
            return None
        
        df = pd.DataFrame(data)
        df = df.sort_values('date').reset_index(drop=True)
        
        for col in ['open_price', 'high_price', 'low_price', 'close_price', 'total_traded_quantity']:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        
        # Calculate indicators
        df['sma_20'] = df['close_price'].rolling(20).mean()
        df['volume_avg'] = df['total_traded_quantity'].rolling(20).mean()
        df['volume_ratio'] = df['total_traded_quantity'] / df['volume_avg']
        df['resistance_20'] = df['high_price'].rolling(20).max()
        df['support_20'] = df['low_price'].rolling(20).min()
        
        latest = df.iloc[-1]
        
        # Score calculation
        score = 0
        signals = []
        
        # Signal 1: Recent volume spike (last 5 days)
        recent_max_vol_ratio = df.tail(5)['volume_ratio'].max()
        if recent_max_vol_ratio >= 2.0:
            score += 30
            signals.append('HIGH_VOLUME_SPIKE')
        elif recent_max_vol_ratio >= 1.5:
            score += 20
            signals.append('VOLUME_ABOVE_AVERAGE')
        
        # Signal 2: Price near resistance
        if pd.notna(latest['resistance_20']) and latest['resistance_20'] > 0:
            distance_to_resistance = (latest['resistance_20'] - latest['close_price']) / latest['resistance_20']
            if distance_to_resistance <= 0.02:  # Within 2% of resistance
                score += 25
                signals.append('NEAR_RESISTANCE')
            elif distance_to_resistance <= 0.05:  # Within 5%
                score += 15
                signals.append('APPROACHING_RESISTANCE')
        
        # Signal 3: Price above SMA
        if pd.notna(latest['sma_20']) and latest['close_price'] > latest['sma_20']:
            score += 15
            signals.append('ABOVE_SMA_20')
        
        # Signal 4: Increasing volume trend
        if len(df) >= 20:
            recent_vol = df.tail(5)['total_traded_quantity'].mean()
            older_vol = df.iloc[-20:-15]['total_traded_quantity'].mean()
            if older_vol > 0 and recent_vol > older_vol * 1.3:
                score += 15
                signals.append('VOLUME_TREND_UP')
        
        # Signal 5: Consolidation pattern
        recent_range = df.tail(10)
        price_range = (recent_range['high_price'].max() - recent_range['low_price'].min()) / recent_range['close_price'].mean()
        if price_range <= 0.10:  # 10% range
            score += 15
            signals.append('TIGHT_CONSOLIDATION')
        
        if score < 30:  # Minimum threshold
            return None
        
        return {
            'symbol': stock.symbol,
            'security_name': stock.security_name,
            'breakout_score': round(score, 1),
            'current_price': float(latest['close_price']),
            'resistance': float(latest['resistance_20']) if pd.notna(latest['resistance_20']) else None,
            'support': float(latest['support_20']) if pd.notna(latest['support_20']) else None,
            'sma_20': float(latest['sma_20']) if pd.notna(latest['sma_20']) else None,
            'volume_ratio': round(float(recent_max_vol_ratio), 2) if pd.notna(recent_max_vol_ratio) else None,
            'signals': signals,
            'date': str(latest['date'])
        }
