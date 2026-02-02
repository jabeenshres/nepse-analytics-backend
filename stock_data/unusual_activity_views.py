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

from .models import Stock, StockData

logger = logging.getLogger(__name__)

DATE_FORMAT = '%Y-%m-%d'


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
        
        # Get latest date in the system
        latest_date = StockData.objects.aggregate(latest=Max('date'))['latest']
        if not latest_date:
            return Response(
                {'error': 'No stock data available'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        start_date = latest_date - timedelta(days=days_lookback)
        
        unusual_stocks = []
        stocks = Stock.objects.all()
        
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
        
        if symbol:
            try:
                stock = Stock.objects.get(symbol__iexact=symbol)
                result = self._analyze_single_stock(stock)
                return Response(result)
            except Stock.DoesNotExist:
                return Response(
                    {'error': f'Stock {symbol} not found'},
                    status=status.HTTP_404_NOT_FOUND
                )
        
        # Analyze all stocks
        latest_date = StockData.objects.aggregate(latest=Max('date'))['latest']
        if not latest_date:
            return Response({'error': 'No data available'}, status=status.HTTP_404_NOT_FOUND)
        
        alerts = []
        stocks = Stock.objects.all()
        
        for stock in stocks:
            result = self._analyze_single_stock(stock)
            if result and result.get('alert'):
                if alert_level == 'all' or result['alert_level'] == alert_level or \
                   (alert_level == 'medium' and result['alert_level'] in ['high', 'medium']):
                    alerts.append(result)
        
        # Sort by alert priority
        priority_order = {'high': 0, 'medium': 1, 'low': 2}
        alerts.sort(key=lambda x: (priority_order.get(x['alert_level'], 3), -x.get('score', 0)))
        
        return Response({
            'date': str(latest_date),
            'total_alerts': len(alerts),
            'high_alerts': len([a for a in alerts if a['alert_level'] == 'high']),
            'medium_alerts': len([a for a in alerts if a['alert_level'] == 'medium']),
            'alerts': alerts
        })
    
    def _analyze_single_stock(self, stock: Stock) -> Optional[Dict[str, Any]]:
        """Analyze a single stock for accumulation patterns."""
        # Get last 20 days of data
        data = list(StockData.objects.filter(
            stock=stock
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
        
    Returns:
        Top N stocks ranked by combined watchability score, or specific stock(s) analysis
    """
    permission_classes = [AllowAny]

    def get(self, request):
        """Get top stocks to watch based on combined analysis."""
        symbol_param = request.query_params.get('symbol', '').strip()
        
        try:
            limit = int(request.query_params.get('limit', 20))
            limit = min(max(limit, 1), 100)
            min_score = float(request.query_params.get('min_score', 40))
        except (ValueError, TypeError):
            limit = 20
            min_score = 40
        
        latest_date = StockData.objects.aggregate(latest=Max('date'))['latest']
        if not latest_date:
            return Response({'error': 'No data available'}, status=status.HTTP_404_NOT_FOUND)
        
        # If specific symbol(s) requested
        if symbol_param:
            return self._analyze_specific_symbols(symbol_param, latest_date)
        
        # Otherwise, analyze all stocks and return top N
        all_stocks = []
        stocks = Stock.objects.all()
        
        for stock in stocks:
            result = self._analyze_stock_comprehensive(stock, latest_date)
            if result and result['combined_score'] >= min_score:
                all_stocks.append(result)
        
        # Sort by combined score
        all_stocks.sort(key=lambda x: x['combined_score'], reverse=True)
        
        top_stocks = all_stocks[:limit]
        
        return Response({
            'date': str(latest_date),
            'total_analyzed': len(stocks),
            'stocks_meeting_criteria': len(all_stocks),
            'returned': len(top_stocks),
            'parameters': {
                'limit': limit,
                'min_score': min_score
            },
            'stocks': top_stocks
        })
    
    def _analyze_specific_symbols(self, symbol_param: str, latest_date):
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
                result = self._analyze_stock_comprehensive(stock, latest_date)
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
                    'date': str(latest_date),
                    'stock': results[0]
                })
        
        # Multiple symbols response
        response_data = {
            'date': str(latest_date),
            'requested': len(symbols),
            'returned': len(results),
            'stocks': results
        }
        
        if not_found:
            response_data['not_found'] = not_found
        if no_data:
            response_data['insufficient_data'] = no_data
        
        return Response(response_data)
    
    def _analyze_stock_comprehensive(self, stock: Stock, latest_date) -> Optional[Dict[str, Any]]:
        """Perform comprehensive analysis combining all signals."""
        # Get last 30 days of data
        data = list(StockData.objects.filter(
            stock=stock
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
    
    Query Parameters:
        days: Number of recent days to analyze (default: 10, max: 30)
        threshold: Volume multiplier threshold (default: 2.5 = 250% of average)
        baseline_days: Days used to calculate average volume (default: 20)
        symbol: Optional - specific stock or comma-separated list
        min_spikes: Minimum number of spike days to include (default: 1)
        
    Returns:
        Stocks with volume spikes sorted by max spike ratio
    """
    permission_classes = [AllowAny]

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
        except (ValueError, TypeError):
            days = 10
            threshold = 2.5
            baseline_days = 20
            min_spikes = 1
        
        symbol_param = request.query_params.get('symbol', '').strip()
        
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
        
        for stock in stocks:
            result = self._analyze_volume_spikes(stock, days, threshold, baseline_days)
            if result and result['spike_count'] >= min_spikes:
                results.append(result)
        
        # Sort by max spike ratio (highest first)
        results.sort(key=lambda x: x['max_spike_ratio'], reverse=True)
        
        return Response({
            'date': str(latest_date),
            'parameters': {
                'analysis_days': days,
                'volume_threshold': f'{threshold}x',
                'baseline_days': baseline_days,
                'min_spikes': min_spikes
            },
            'total_stocks_with_spikes': len(results),
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
    API view that analyzes top stocks and provides actionable buy/sell recommendations.
    
    This endpoint:
    - Filters out mutual funds, debentures, and bonds
    - Categorizes stocks into STRONG_BUY, BUY, WATCH
    - Provides price targets and stop loss levels
    - Ranks by conviction score
    
    Query Parameters:
        limit: Number of recommendations to return (default: 20)
        include_mf: Include mutual funds (default: false)
        include_debentures: Include debentures (default: false)
        min_score: Minimum score to consider (default: 40)
        
    Returns:
        Categorized recommendations with targets
    """
    permission_classes = [AllowAny]
    
    # Keywords to identify mutual funds and debentures
    EXCLUDE_KEYWORDS = [
        'fund', 'yojana', 'debenture', 'bond', 'mutual', 'scheme',
        'growth scheme', 'value fund', 'equity fund', 'balanced',
        'fixed deposit', 'unit', 'certificate', 'flexi cap'
    ]

    def get(self, request):
        """Get stock recommendations."""
        try:
            limit = int(request.query_params.get('limit', 20))
            limit = min(max(limit, 1), 100)
            min_score = float(request.query_params.get('min_score', 40))
            include_mf = request.query_params.get('include_mf', 'false').lower() == 'true'
            include_debentures = request.query_params.get('include_debentures', 'false').lower() == 'true'
        except (ValueError, TypeError):
            limit = 20
            min_score = 40
            include_mf = False
            include_debentures = False
        
        latest_date = StockData.objects.aggregate(latest=Max('date'))['latest']
        if not latest_date:
            return Response({'error': 'No data available'}, status=status.HTTP_404_NOT_FOUND)
        
        # Get all stocks analysis
        top_stocks_view = TopStocksToWatchView()
        all_analyzed = []
        
        for stock in Stock.objects.all():
            result = top_stocks_view._analyze_stock_comprehensive(stock, latest_date)
            if result and result['combined_score'] >= min_score:
                all_analyzed.append(result)
        
        # Filter based on parameters
        filtered_stocks = self._filter_stocks(all_analyzed, include_mf, include_debentures)
        
        # Categorize and add recommendations
        recommendations = self._categorize_stocks(filtered_stocks)
        
        # Limit results
        for category in ['strong_buy', 'buy', 'watch']:
            recommendations[category] = recommendations[category][:limit]
        
        # Get top picks
        top_picks = self._get_top_picks(filtered_stocks, limit=5)
        
        return Response({
            'date': str(latest_date),
            'summary': {
                'total_analyzed': len(all_analyzed),
                'after_filtering': len(filtered_stocks),
                'strong_buy_count': len(recommendations['strong_buy']),
                'buy_count': len(recommendations['buy']),
                'watch_count': len(recommendations['watch'])
            },
            'filters_applied': {
                'exclude_mutual_funds': not include_mf,
                'exclude_debentures': not include_debentures,
                'min_score': min_score
            },
            'top_picks': top_picks,
            'strong_buy': recommendations['strong_buy'],
            'buy': recommendations['buy'],
            'watch': recommendations['watch'],
            'metrics_explanation': self._get_metrics_explanation()
        })
    
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
    
    def _categorize_stocks(self, stocks: list) -> dict:
        """Categorize stocks into STRONG_BUY, BUY, WATCH with recommendations."""
        strong_buy = []
        buy = []
        watch = []
        
        for s in stocks:
            score = s['combined_score']
            km = s['key_metrics']
            vol_ratio = km.get('max_volume_ratio') or 0
            dist_to_res = km.get('distance_to_resistance') or 100
            unusual_days = km.get('unusual_days_count') or 0
            acc_score = s['score_breakdown']['accumulation']
            
            # Add recommendation details
            recommendation = self._generate_recommendation(s)
            s['recommendation'] = recommendation
            
            # Categorize
            # STRONG BUY: High score + Near resistance + Good volume
            if score >= 85 and dist_to_res <= 5 and vol_ratio >= 2.0:
                s['category'] = 'STRONG_BUY'
                s['action'] = 'Buy now - Breakout imminent'
                strong_buy.append(s)
            # BUY: Good score + Either high volume OR sustained activity
            elif score >= 75 and (vol_ratio >= 3.0 or unusual_days >= 4):
                s['category'] = 'BUY'
                s['action'] = 'Good entry point - Accumulation in progress'
                buy.append(s)
            # Also BUY if very high score
            elif score >= 80:
                s['category'] = 'BUY'
                s['action'] = 'Consider buying - Strong signals'
                buy.append(s)
            # WATCH: Others
            else:
                s['category'] = 'WATCH'
                s['action'] = 'Monitor for stronger signals'
                watch.append(s)
        
        # Sort each category by score
        strong_buy.sort(key=lambda x: x['combined_score'], reverse=True)
        buy.sort(key=lambda x: x['combined_score'], reverse=True)
        watch.sort(key=lambda x: x['combined_score'], reverse=True)
        
        return {
            'strong_buy': strong_buy,
            'buy': buy,
            'watch': watch
        }
    
    def _generate_recommendation(self, stock: dict) -> dict:
        """Generate detailed recommendation for a stock."""
        km = stock['key_metrics']
        price = stock['current_price']
        resistance = km.get('resistance')
        support = km.get('support')
        vol_ratio = km.get('max_volume_ratio') or 0
        unusual_days = km.get('unusual_days_count') or 0
        
        rec = {
            'entry_price': price,
            'target_price': resistance,
            'stop_loss': support,
            'upside_percent': None,
            'downside_percent': None,
            'risk_reward_ratio': None,
            'reasons': [],
            'warnings': []
        }
        
        # Calculate percentages
        if resistance and price:
            rec['upside_percent'] = round(((resistance - price) / price) * 100, 2)
        if support and price:
            rec['downside_percent'] = round(((price - support) / price) * 100, 2)
        
        # Risk/Reward ratio
        if rec['upside_percent'] and rec['downside_percent'] and rec['downside_percent'] > 0:
            rec['risk_reward_ratio'] = round(rec['upside_percent'] / rec['downside_percent'], 2)
        
        # Generate reasons
        if vol_ratio >= 4:
            rec['reasons'].append(f'Extreme volume spike ({vol_ratio}x) indicates strong accumulation')
        elif vol_ratio >= 2.5:
            rec['reasons'].append(f'High volume ({vol_ratio}x) suggests institutional interest')
        elif vol_ratio >= 1.5:
            rec['reasons'].append(f'Above average volume ({vol_ratio}x)')
        
        if unusual_days >= 5:
            rec['reasons'].append(f'Sustained accumulation for {unusual_days} days')
        elif unusual_days >= 3:
            rec['reasons'].append(f'Multiple days ({unusual_days}) of unusual activity')
        
        dist_to_res = km.get('distance_to_resistance')
        if dist_to_res is not None:
            if dist_to_res <= 2:
                rec['reasons'].append('At resistance level - breakout imminent')
            elif dist_to_res <= 5:
                rec['reasons'].append('Near resistance - watch for breakout')
        
        if stock['score_breakdown']['accumulation'] >= 30:
            rec['reasons'].append('Strong accumulation pattern detected')
        
        if 'LARGE_BLOCK_TRADES' in stock['signals'].get('momentum', []):
            rec['reasons'].append('Large block trades indicate institutional buying')
        
        if 'BULLISH_CANDLES' in stock['signals'].get('momentum', []):
            rec['reasons'].append('Bullish candle pattern')
        
        # Generate warnings
        if vol_ratio >= 8:
            rec['warnings'].append('Extremely high volume - could be manipulation, verify news')
        
        if unusual_days == 1 and vol_ratio >= 5:
            rec['warnings'].append('Single day spike - wait for confirmation')
        
        recent_activity = stock.get('recent_unusual_activity', [])
        red_days = sum(1 for a in recent_activity if not a.get('is_green', True))
        if red_days > len(recent_activity) / 2:
            rec['warnings'].append('Recent activity shows more selling pressure')
        
        return rec
    
    def _get_top_picks(self, stocks: list, limit: int = 5) -> list:
        """Get top picks with highest conviction."""
        for s in stocks:
            km = s['key_metrics']
            # Conviction = score + volume bonus + proximity bonus
            vol_bonus = min((km.get('max_volume_ratio') or 0) * 5, 25)
            prox_bonus = max(0, (10 - (km.get('distance_to_resistance') or 10))) * 2
            days_bonus = min((km.get('unusual_days_count') or 0) * 2, 10)
            s['conviction_score'] = s['combined_score'] + vol_bonus + prox_bonus + days_bonus
        
        # Sort by conviction
        sorted_stocks = sorted(stocks, key=lambda x: x['conviction_score'], reverse=True)
        
        top_picks = []
        for i, s in enumerate(sorted_stocks[:limit], 1):
            km = s['key_metrics']
            pick = {
                'rank': i,
                'symbol': s['symbol'],
                'security_name': s['security_name'],
                'current_price': s['current_price'],
                'combined_score': s['combined_score'],
                'conviction_score': round(s['conviction_score'], 1),
                'volume_ratio': km.get('max_volume_ratio'),
                'unusual_days': km.get('unusual_days_count'),
                'distance_to_resistance': km.get('distance_to_resistance'),
                'target_price': km.get('resistance'),
                'stop_loss': km.get('support'),
                'summary': s['summary'],
                'key_reasons': s.get('recommendation', {}).get('reasons', [])[:3]
            }
            
            # Add percentage calculations
            if pick['target_price'] and pick['current_price']:
                pick['upside_percent'] = round(((pick['target_price'] - pick['current_price']) / pick['current_price']) * 100, 2)
            if pick['stop_loss'] and pick['current_price']:
                pick['downside_percent'] = round(((pick['current_price'] - pick['stop_loss']) / pick['current_price']) * 100, 2)
            
            top_picks.append(pick)
        
        return top_picks
    
    def _get_metrics_explanation(self) -> dict:
        """Return explanation of all metrics."""
        return {
            'combined_score': {
                'description': 'Overall signal strength (0-100)',
                'ranges': {
                    '85-100': 'STRONG_BUY - Highest conviction',
                    '70-84': 'BUY - Strong accumulation detected',
                    '55-69': 'WATCH - Developing pattern',
                    '40-54': 'MONITOR - Weak signals'
                }
            },
            'score_breakdown': {
                'accumulation': 'Volume spikes + Price stability + Duration (max 35)',
                'breakout_readiness': 'Near resistance + Above SMAs + Consolidation (max 35)',
                'momentum': 'Price trend + Candle patterns + Block trades (max 30)'
            },
            'key_metrics': {
                'max_volume_ratio': 'Volume vs 10-day average. >= 2.5x indicates accumulation',
                'unusual_days_count': 'Days with volume spike + stable price. >= 3 is sustained',
                'distance_to_resistance': 'Distance to 20-day high. <= 5% means ready to break',
                'sma_20': '20-day moving average. Price > SMA = bullish',
                'resistance': '20-day high - Use as target price',
                'support': '20-day low - Use as stop loss'
            },
            'recommendation_categories': {
                'STRONG_BUY': 'Score >= 85, Near resistance (<=5%), Volume >= 2x',
                'BUY': 'Score >= 75 with high volume (3x+) or sustained activity (4+ days)',
                'WATCH': 'Good signals but needs confirmation'
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
        latest_date = StockData.objects.aggregate(latest=Max('date'))['latest']
        if not latest_date:
            return Response({'error': 'No data available'}, status=status.HTTP_404_NOT_FOUND)
        
        watchlist = []
        stocks = Stock.objects.all()
        
        for stock in stocks:
            result = self._analyze_breakout_potential(stock)
            if result:
                watchlist.append(result)
        
        # Sort by breakout score
        watchlist.sort(key=lambda x: x['breakout_score'], reverse=True)
        
        return Response({
            'date': str(latest_date),
            'total_candidates': len(watchlist),
            'watchlist': watchlist[:30]  # Top 30
        })
    
    def _analyze_breakout_potential(self, stock: Stock) -> Optional[Dict[str, Any]]:
        """Analyze breakout potential for a stock."""
        data = list(StockData.objects.filter(
            stock=stock
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
