"""
Views for technical analysis, trading signals, backtesting, and portfolio management.
"""
import logging
from decimal import Decimal
from datetime import datetime, timedelta
import pandas as pd
import numpy as np

from rest_framework import viewsets, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from django.shortcuts import get_object_or_404
from django.db.models import Max, Avg, F, Q

from .models import Stock, StockData, Portfolio, PortfolioHolding, Trade, BacktestResult
from .technical_indicators import calculate_all_indicators, generate_trading_signals
from .serializers import (
    PortfolioSerializer,
    PortfolioHoldingSerializer,
    TradeSerializer,
    BacktestResultSerializer,
)

logger = logging.getLogger(__name__)

DATE_FORMAT = '%Y-%m-%d'


class TechnicalIndicatorsView(APIView):
    """
    API view for calculating technical indicators for a stock.
    
    Query Parameters:
        symbol: Stock symbol (required)
        days: Number of days of historical data (default: 100, max: 500)
        indicators: Comma-separated list of specific indicators (optional)
    
    Returns all standard technical indicators including:
        - Moving Averages (SMA, EMA)
        - RSI
        - MACD
        - Bollinger Bands
        - ATR
        - Stochastic Oscillator
        - OBV
        - VWAP
        - Support/Resistance levels
        - Volume indicators
    """
    permission_classes = [AllowAny]

    def get(self, request):
        """Get technical indicators for a stock."""
        symbol = request.query_params.get('symbol')
        
        if not symbol:
            return Response(
                {'error': 'symbol parameter is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            days = int(request.query_params.get('days', 100))
            days = min(max(days, 10), 500)  # Clamp between 10 and 500
        except (ValueError, TypeError):
            days = 100
        
        try:
            stock = Stock.objects.get(symbol__iexact=symbol)
        except Stock.DoesNotExist:
            return Response(
                {'error': f'Stock with symbol "{symbol}" not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Fetch historical data
        data = StockData.objects.filter(
            stock=stock
        ).order_by('-date')[:days].values(
            'date', 'open_price', 'high_price',
            'low_price', 'close_price', 'total_traded_quantity'
        )
        
        if not data:
            return Response(
                {'error': f'No data available for stock {symbol}'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        df = pd.DataFrame(list(data))
        df = df.sort_values('date').reset_index(drop=True)
        
        # Calculate all indicators
        df = calculate_all_indicators(df)
        
        # Convert date to string for JSON serialization
        df['date'] = df['date'].astype(str)
        
        # Replace NaN with None for JSON
        df = df.replace({np.nan: None})
        
        result = df.to_dict('records')
        
        return Response({
            'symbol': symbol,
            'security_name': stock.security_name,
            'days': len(result),
            'data': result
        })


class TradingSignalsView(APIView):
    """
    API view for generating trading signals based on technical analysis.
    
    Query Parameters:
        symbol: Stock symbol (required)
    
    Returns:
        - List of current signals (bullish/bearish/neutral)
        - Overall signal strength (-100 to +100)
        - Recommendation (STRONG_BUY, BUY, HOLD, SELL, STRONG_SELL)
    """
    permission_classes = [AllowAny]

    def get(self, request):
        """Generate trading signals for a stock."""
        symbol = request.query_params.get('symbol')
        
        if not symbol:
            return Response(
                {'error': 'symbol parameter is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            stock = Stock.objects.get(symbol__iexact=symbol)
        except Stock.DoesNotExist:
            return Response(
                {'error': f'Stock with symbol "{symbol}" not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Fetch enough data for indicator calculation
        data = StockData.objects.filter(
            stock=stock
        ).order_by('-date')[:100].values(
            'date', 'open_price', 'high_price',
            'low_price', 'close_price', 'total_traded_quantity'
        )
        
        if not data or len(data) < 20:
            return Response(
                {'error': f'Insufficient data for stock {symbol}. Need at least 20 days.'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        df = pd.DataFrame(list(data))
        df = df.sort_values('date').reset_index(drop=True)
        
        # Calculate indicators
        df = calculate_all_indicators(df)
        
        # Generate signals
        signals_result = generate_trading_signals(df)
        
        # Get latest price info
        latest = df.iloc[-1]
        
        return Response({
            'symbol': symbol,
            'security_name': stock.security_name,
            'last_price': float(latest['close_price']),
            'last_date': str(latest['date']),
            'signals': signals_result['signals'],
            'strength': signals_result['strength'],
            'recommendation': signals_result['recommendation'],
            'signal_count': signals_result['signal_count'],
            'key_levels': {
                'support': float(latest['Support']) if pd.notna(latest.get('Support')) else None,
                'resistance': float(latest['Resistance']) if pd.notna(latest.get('Resistance')) else None,
                'sma_20': float(latest['SMA_20']) if pd.notna(latest.get('SMA_20')) else None,
                'sma_50': float(latest['SMA_50']) if pd.notna(latest.get('SMA_50')) else None,
            }
        })


class StockScreenerView(APIView):
    """
    API view for screening stocks based on technical criteria.
    
    Query Parameters:
        type: Screener type (momentum, oversold, overbought, volume_breakout, trend_following)
        min_price: Minimum close price filter
        max_price: Maximum close price filter
        limit: Number of results (default: 20, max: 100)
    
    Screener Types:
        - momentum: Stocks with price above moving averages and rising volume
        - oversold: Stocks with RSI < 30 and price near support
        - overbought: Stocks with RSI > 70 and price near resistance
        - volume_breakout: Stocks with volume significantly above average
        - trend_following: Stocks in clear uptrend (price > SMA20 > SMA50)
    """
    permission_classes = [AllowAny]

    def get(self, request):
        """Screen stocks based on criteria."""
        screener_type = request.query_params.get('type', 'momentum')
        
        try:
            limit = int(request.query_params.get('limit', 20))
            limit = min(max(limit, 1), 100)
        except (ValueError, TypeError):
            limit = 20
        
        try:
            min_price = float(request.query_params.get('min_price', 0))
        except (ValueError, TypeError):
            min_price = 0
        
        try:
            max_price = float(request.query_params.get('max_price', float('inf')))
        except (ValueError, TypeError):
            max_price = float('inf')
        
        # Get latest date
        latest_date = StockData.objects.aggregate(latest=Max('date'))['latest']
        if not latest_date:
            return Response(
                {'error': 'No stock data available'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Get all stocks with recent data
        stocks = Stock.objects.all()
        
        results = []
        for stock in stocks:
            # Get recent data for each stock
            data = list(StockData.objects.filter(
                stock=stock
            ).order_by('-date')[:60].values(
                'date', 'open_price', 'high_price',
                'low_price', 'close_price', 'total_traded_quantity'
            ))
            
            if len(data) < 30:  # Need minimum data for calculations
                continue
            
            df = pd.DataFrame(data)
            df = df.sort_values('date').reset_index(drop=True)
            
            # Apply price filters
            latest_close = float(df.iloc[-1]['close_price'])
            if latest_close < min_price or latest_close > max_price:
                continue
            
            # Calculate indicators
            df = calculate_all_indicators(df)
            latest = df.iloc[-1]
            
            # Screen based on type
            if screener_type == 'momentum':
                if self._check_momentum(latest):
                    results.append(self._build_result(stock, latest, 'momentum'))
            
            elif screener_type == 'oversold':
                if self._check_oversold(latest):
                    results.append(self._build_result(stock, latest, 'oversold'))
            
            elif screener_type == 'overbought':
                if self._check_overbought(latest):
                    results.append(self._build_result(stock, latest, 'overbought'))
            
            elif screener_type == 'volume_breakout':
                if self._check_volume_breakout(latest):
                    results.append(self._build_result(stock, latest, 'volume_breakout'))
            
            elif screener_type == 'trend_following':
                if self._check_trend_following(latest):
                    results.append(self._build_result(stock, latest, 'trend_following'))
        
        # Sort results by relevance score
        results.sort(key=lambda x: x.get('score', 0), reverse=True)
        
        return Response({
            'screener_type': screener_type,
            'count': len(results[:limit]),
            'total_matched': len(results),
            'date': str(latest_date),
            'results': results[:limit]
        })
    
    def _check_momentum(self, latest) -> bool:
        """Check if stock meets momentum criteria."""
        if pd.isna(latest.get('SMA_20')) or pd.isna(latest.get('SMA_50')):
            return False
        
        price_above_sma = latest['close_price'] > latest['SMA_20']
        volume_above_avg = latest.get('Volume_Ratio', 0) > 1.2 if pd.notna(latest.get('Volume_Ratio')) else False
        
        return price_above_sma and volume_above_avg
    
    def _check_oversold(self, latest) -> bool:
        """Check if stock is oversold."""
        rsi_oversold = latest.get('RSI', 50) < 30 if pd.notna(latest.get('RSI')) else False
        stoch_oversold = latest.get('Stoch_K', 50) < 20 if pd.notna(latest.get('Stoch_K')) else False
        
        return rsi_oversold or stoch_oversold
    
    def _check_overbought(self, latest) -> bool:
        """Check if stock is overbought."""
        rsi_overbought = latest.get('RSI', 50) > 70 if pd.notna(latest.get('RSI')) else False
        stoch_overbought = latest.get('Stoch_K', 50) > 80 if pd.notna(latest.get('Stoch_K')) else False
        
        return rsi_overbought or stoch_overbought
    
    def _check_volume_breakout(self, latest) -> bool:
        """Check if stock has volume breakout."""
        volume_ratio = latest.get('Volume_Ratio', 0)
        return pd.notna(volume_ratio) and volume_ratio > 2.0
    
    def _check_trend_following(self, latest) -> bool:
        """Check if stock is in uptrend."""
        if pd.isna(latest.get('SMA_20')) or pd.isna(latest.get('SMA_50')):
            return False
        
        return latest['close_price'] > latest['SMA_20'] > latest['SMA_50']
    
    def _build_result(self, stock, latest, screener_type: str) -> dict:
        """Build result dictionary for a matched stock."""
        score = 0
        
        # Calculate score based on type
        if screener_type == 'momentum':
            score = float(latest.get('Volume_Ratio', 1) * 10) if pd.notna(latest.get('Volume_Ratio')) else 0
        elif screener_type == 'oversold':
            score = 100 - float(latest.get('RSI', 50)) if pd.notna(latest.get('RSI')) else 0
        elif screener_type == 'overbought':
            score = float(latest.get('RSI', 50)) if pd.notna(latest.get('RSI')) else 0
        elif screener_type == 'volume_breakout':
            score = float(latest.get('Volume_Ratio', 1) * 10) if pd.notna(latest.get('Volume_Ratio')) else 0
        elif screener_type == 'trend_following':
            if pd.notna(latest.get('SMA_20')):
                score = ((float(latest['close_price']) - float(latest['SMA_20'])) / float(latest['SMA_20'])) * 100
        
        return {
            'symbol': stock.symbol,
            'security_name': stock.security_name,
            'close_price': float(latest['close_price']),
            'change_percent': float(latest['Daily_Return'] * 100) if pd.notna(latest.get('Daily_Return')) else None,
            'volume': int(latest['total_traded_quantity']),
            'volume_ratio': float(latest['Volume_Ratio']) if pd.notna(latest.get('Volume_Ratio')) else None,
            'rsi': float(latest['RSI']) if pd.notna(latest.get('RSI')) else None,
            'sma_20': float(latest['SMA_20']) if pd.notna(latest.get('SMA_20')) else None,
            'sma_50': float(latest['SMA_50']) if pd.notna(latest.get('SMA_50')) else None,
            'score': round(score, 2)
        }


class BacktestStrategyView(APIView):
    """
    API view for backtesting trading strategies.
    
    Supports strategies:
        - sma_crossover: Buy when short SMA crosses above long SMA
        - rsi_reversal: Buy when RSI < 30, sell when RSI > 70
        - macd_crossover: Buy/sell on MACD signal crossovers
        - bollinger_bounce: Buy at lower band, sell at upper band
    
    Request Body:
        {
            "strategy": "sma_crossover",
            "symbol": "NABIL",
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
            "capital": 100000,
            "parameters": {
                "short_period": 20,
                "long_period": 50
            }
        }
    """
    permission_classes = [AllowAny]

    def post(self, request):
        """Run backtest for a strategy."""
        strategy = request.data.get('strategy', 'sma_crossover')
        symbol = request.data.get('symbol')
        start_date_str = request.data.get('start_date')
        end_date_str = request.data.get('end_date')
        initial_capital = float(request.data.get('capital', 100000))
        parameters = request.data.get('parameters', {})
        
        # Validation
        if not symbol:
            return Response(
                {'error': 'symbol is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            stock = Stock.objects.get(symbol__iexact=symbol)
        except Stock.DoesNotExist:
            return Response(
                {'error': f'Stock with symbol "{symbol}" not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Parse dates
        try:
            start_date = datetime.strptime(start_date_str, DATE_FORMAT).date() if start_date_str else None
            end_date = datetime.strptime(end_date_str, DATE_FORMAT).date() if end_date_str else None
        except ValueError:
            return Response(
                {'error': f'Invalid date format. Use {DATE_FORMAT}'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Fetch data
        queryset = StockData.objects.filter(stock=stock).order_by('date')
        if start_date:
            queryset = queryset.filter(date__gte=start_date)
        if end_date:
            queryset = queryset.filter(date__lte=end_date)
        
        data = list(queryset.values(
            'date', 'open_price', 'high_price',
            'low_price', 'close_price', 'total_traded_quantity'
        ))
        
        if len(data) < 60:
            return Response(
                {'error': 'Insufficient data for backtesting. Need at least 60 data points.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        df = pd.DataFrame(data)
        df = calculate_all_indicators(df)
        
        # Run backtest
        if strategy == 'sma_crossover':
            results = self._backtest_sma_crossover(df, initial_capital, parameters)
        elif strategy == 'rsi_reversal':
            results = self._backtest_rsi_reversal(df, initial_capital, parameters)
        elif strategy == 'macd_crossover':
            results = self._backtest_macd_crossover(df, initial_capital, parameters)
        elif strategy == 'bollinger_bounce':
            results = self._backtest_bollinger_bounce(df, initial_capital, parameters)
        else:
            return Response(
                {'error': f'Unknown strategy: {strategy}. Supported: sma_crossover, rsi_reversal, macd_crossover, bollinger_bounce'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Save result if user is authenticated
        if request.user.is_authenticated:
            BacktestResult.objects.create(
                user=request.user,
                stock=stock,
                strategy_name=strategy,
                start_date=df.iloc[0]['date'],
                end_date=df.iloc[-1]['date'],
                initial_capital=Decimal(str(initial_capital)),
                final_value=Decimal(str(results['final_value'])),
                total_return=Decimal(str(results['total_return'])),
                win_rate=Decimal(str(results['win_rate'])) if results['win_rate'] else None,
                max_drawdown=Decimal(str(results['max_drawdown'])) if results['max_drawdown'] else None,
                sharpe_ratio=Decimal(str(results['sharpe_ratio'])) if results['sharpe_ratio'] else None,
                total_trades=results['total_trades'],
                winning_trades=results['winning_trades'],
                losing_trades=results['losing_trades'],
                parameters=parameters
            )
        
        return Response({
            'strategy': strategy,
            'symbol': symbol,
            'start_date': str(df.iloc[0]['date']),
            'end_date': str(df.iloc[-1]['date']),
            'initial_capital': initial_capital,
            **results
        })
    
    def _backtest_sma_crossover(self, df: pd.DataFrame, capital: float, params: dict) -> dict:
        """Backtest SMA crossover strategy."""
        short_period = params.get('short_period', 20)
        long_period = params.get('long_period', 50)
        
        df['short_sma'] = df['close_price'].rolling(window=short_period).mean()
        df['long_sma'] = df['close_price'].rolling(window=long_period).mean()
        
        return self._run_crossover_backtest(df, capital, 'short_sma', 'long_sma')
    
    def _backtest_rsi_reversal(self, df: pd.DataFrame, capital: float, params: dict) -> dict:
        """Backtest RSI reversal strategy."""
        oversold = params.get('oversold', 30)
        overbought = params.get('overbought', 70)
        
        position = 0
        cash = capital
        shares = 0
        trades = []
        entry_price = 0
        portfolio_values = []
        
        for i in range(len(df)):
            row = df.iloc[i]
            current_price = float(row['close_price'])
            
            portfolio_value = cash + (shares * current_price)
            portfolio_values.append(portfolio_value)
            
            if pd.isna(row['RSI']):
                continue
            
            rsi = row['RSI']
            
            # Buy signal
            if rsi < oversold and position == 0:
                shares = int(cash / current_price)
                if shares > 0:
                    cash -= shares * current_price
                    position = 1
                    entry_price = current_price
            
            # Sell signal
            elif rsi > overbought and position == 1:
                cash += shares * current_price
                trade_return = (current_price - entry_price) / entry_price
                trades.append({
                    'entry_price': entry_price,
                    'exit_price': current_price,
                    'return': trade_return
                })
                shares = 0
                position = 0
        
        # Close any open position
        if shares > 0:
            final_price = float(df.iloc[-1]['close_price'])
            cash += shares * final_price
        
        return self._calculate_backtest_metrics(capital, cash, trades, portfolio_values)
    
    def _backtest_macd_crossover(self, df: pd.DataFrame, capital: float, params: dict) -> dict:
        """Backtest MACD crossover strategy."""
        return self._run_crossover_backtest(df, capital, 'MACD', 'MACD_Signal')
    
    def _backtest_bollinger_bounce(self, df: pd.DataFrame, capital: float, params: dict) -> dict:
        """Backtest Bollinger Band bounce strategy."""
        position = 0
        cash = capital
        shares = 0
        trades = []
        entry_price = 0
        portfolio_values = []
        
        for i in range(len(df)):
            row = df.iloc[i]
            current_price = float(row['close_price'])
            
            portfolio_value = cash + (shares * current_price)
            portfolio_values.append(portfolio_value)
            
            if pd.isna(row['BB_Lower']) or pd.isna(row['BB_Upper']):
                continue
            
            # Buy at lower band
            if current_price <= float(row['BB_Lower']) and position == 0:
                shares = int(cash / current_price)
                if shares > 0:
                    cash -= shares * current_price
                    position = 1
                    entry_price = current_price
            
            # Sell at upper band or middle band
            elif current_price >= float(row['BB_Upper']) and position == 1:
                cash += shares * current_price
                trade_return = (current_price - entry_price) / entry_price
                trades.append({
                    'entry_price': entry_price,
                    'exit_price': current_price,
                    'return': trade_return
                })
                shares = 0
                position = 0
        
        # Close any open position
        if shares > 0:
            final_price = float(df.iloc[-1]['close_price'])
            cash += shares * final_price
        
        return self._calculate_backtest_metrics(capital, cash, trades, portfolio_values)
    
    def _run_crossover_backtest(self, df: pd.DataFrame, capital: float, fast_col: str, slow_col: str) -> dict:
        """Generic crossover backtest."""
        position = 0
        cash = capital
        shares = 0
        trades = []
        entry_price = 0
        portfolio_values = []
        
        for i in range(1, len(df)):
            row = df.iloc[i]
            prev_row = df.iloc[i-1]
            current_price = float(row['close_price'])
            
            portfolio_value = cash + (shares * current_price)
            portfolio_values.append(portfolio_value)
            
            if pd.isna(row[fast_col]) or pd.isna(row[slow_col]):
                continue
            if pd.isna(prev_row[fast_col]) or pd.isna(prev_row[slow_col]):
                continue
            
            # Bullish crossover - buy
            if prev_row[fast_col] <= prev_row[slow_col] and row[fast_col] > row[slow_col] and position == 0:
                shares = int(cash / current_price)
                if shares > 0:
                    cash -= shares * current_price
                    position = 1
                    entry_price = current_price
            
            # Bearish crossover - sell
            elif prev_row[fast_col] >= prev_row[slow_col] and row[fast_col] < row[slow_col] and position == 1:
                cash += shares * current_price
                trade_return = (current_price - entry_price) / entry_price
                trades.append({
                    'entry_price': entry_price,
                    'exit_price': current_price,
                    'return': trade_return
                })
                shares = 0
                position = 0
        
        # Close any open position
        if shares > 0:
            final_price = float(df.iloc[-1]['close_price'])
            cash += shares * final_price
        
        return self._calculate_backtest_metrics(capital, cash, trades, portfolio_values)
    
    def _calculate_backtest_metrics(self, initial_capital: float, final_value: float, trades: list, portfolio_values: list) -> dict:
        """Calculate backtest performance metrics."""
        total_return = ((final_value - initial_capital) / initial_capital) * 100
        
        winning_trades = len([t for t in trades if t['return'] > 0])
        losing_trades = len([t for t in trades if t['return'] <= 0])
        total_trades = len(trades)
        
        win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
        
        # Calculate max drawdown
        max_drawdown = 0
        peak = portfolio_values[0] if portfolio_values else initial_capital
        for value in portfolio_values:
            if value > peak:
                peak = value
            drawdown = (peak - value) / peak * 100
            if drawdown > max_drawdown:
                max_drawdown = drawdown
        
        # Calculate Sharpe Ratio (simplified)
        if len(portfolio_values) > 1:
            returns = pd.Series(portfolio_values).pct_change().dropna()
            if len(returns) > 0 and returns.std() > 0:
                sharpe_ratio = (returns.mean() / returns.std()) * np.sqrt(252)  # Annualized
            else:
                sharpe_ratio = 0
        else:
            sharpe_ratio = 0
        
        return {
            'final_value': round(final_value, 2),
            'total_return': round(total_return, 2),
            'win_rate': round(win_rate, 2),
            'max_drawdown': round(max_drawdown, 2),
            'sharpe_ratio': round(sharpe_ratio, 4),
            'total_trades': total_trades,
            'winning_trades': winning_trades,
            'losing_trades': losing_trades,
            'trades': trades
        }


class PortfolioViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing user portfolios.
    
    Requires authentication.
    """
    serializer_class = PortfolioSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """Return portfolios for the current user."""
        return Portfolio.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        """Set the user when creating a portfolio."""
        serializer.save(user=self.request.user)


class PortfolioHoldingViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing portfolio holdings.
    
    Requires authentication. Users can only access holdings in their own portfolios.
    """
    serializer_class = PortfolioHoldingSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """Return holdings for the current user's portfolios."""
        return PortfolioHolding.objects.filter(
            portfolio__user=self.request.user
        ).select_related('stock', 'portfolio')


class TradeViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing trades.
    
    Requires authentication. Users can only access their own trades.
    """
    serializer_class = TradeSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """Return trades for the current user's portfolios."""
        return Trade.objects.filter(
            portfolio__user=self.request.user
        ).select_related('stock', 'portfolio')


class PortfolioPerformanceView(APIView):
    """
    API view for calculating portfolio performance metrics.
    
    Can work with:
    1. Existing portfolio (GET with portfolio_id)
    2. Ad-hoc trades list (POST with trades array)
    """
    permission_classes = [AllowAny]

    def get(self, request):
        """Get performance for an existing portfolio."""
        portfolio_id = request.query_params.get('portfolio_id')
        
        if not portfolio_id:
            return Response(
                {'error': 'portfolio_id is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            portfolio = Portfolio.objects.get(id=portfolio_id)
        except Portfolio.DoesNotExist:
            return Response(
                {'error': 'Portfolio not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Check permission
        if request.user.is_authenticated and portfolio.user != request.user:
            return Response(
                {'error': 'Access denied'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        holdings = portfolio.holdings.select_related('stock').all()
        trades = portfolio.trades.select_related('stock').all()
        
        # Calculate metrics
        total_invested = sum(h.average_buy_price * h.quantity for h in holdings)
        current_value = sum(h.market_value for h in holdings)
        total_profit_loss = current_value - float(total_invested)
        
        # Calculate from trades
        completed_trades = [t for t in trades if t.exit_price]
        winning_trades = len([t for t in completed_trades if t.return_amount and t.return_amount > 0])
        
        return Response({
            'portfolio_id': portfolio.id,
            'portfolio_name': portfolio.name,
            'initial_capital': float(portfolio.initial_capital),
            'total_invested': float(total_invested),
            'current_value': float(current_value),
            'total_profit_loss': float(total_profit_loss),
            'total_return': float(portfolio.total_return),
            'holdings_count': holdings.count(),
            'total_trades': trades.count(),
            'completed_trades': len(completed_trades),
            'win_rate': (winning_trades / len(completed_trades) * 100) if completed_trades else 0,
        })

    def post(self, request):
        """Calculate performance for ad-hoc trades list."""
        trades = request.data.get('trades', [])
        
        if not trades:
            return Response(
                {'error': 'trades array is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        total_return = 0
        winning_trades = 0
        losing_trades = 0
        returns = []
        
        for trade in trades:
            entry_price = float(trade.get('entry_price', 0))
            exit_price = float(trade.get('exit_price', 0))
            quantity = int(trade.get('quantity', 1))
            
            if entry_price <= 0:
                continue
            
            if exit_price > 0:
                trade_return = (exit_price - entry_price) / entry_price
                total_return += trade_return * quantity
                returns.append(trade_return)
                
                if trade_return > 0:
                    winning_trades += 1
                else:
                    losing_trades += 1
        
        total_trades = winning_trades + losing_trades
        
        # Calculate Sharpe ratio
        if returns and len(returns) > 1:
            returns_series = pd.Series(returns)
            sharpe_ratio = (returns_series.mean() / returns_series.std()) * np.sqrt(252) if returns_series.std() > 0 else 0
        else:
            sharpe_ratio = 0
        
        # Calculate max drawdown from cumulative returns
        if returns:
            cumulative = np.cumprod([1 + r for r in returns])
            peak = np.maximum.accumulate(cumulative)
            drawdown = (peak - cumulative) / peak
            max_drawdown = np.max(drawdown) * 100
        else:
            max_drawdown = 0
        
        return Response({
            'total_return': round(total_return * 100, 2),
            'win_rate': round(winning_trades / total_trades * 100, 2) if total_trades > 0 else 0,
            'sharpe_ratio': round(sharpe_ratio, 4),
            'max_drawdown': round(max_drawdown, 2),
            'total_trades': total_trades,
            'winning_trades': winning_trades,
            'losing_trades': losing_trades,
        })


class BacktestResultViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for viewing backtest results.
    
    Read-only. Users can only view their own backtest results.
    """
    serializer_class = BacktestResultSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """Return backtest results for the current user."""
        return BacktestResult.objects.filter(
            user=self.request.user
        ).select_related('stock')
