"""
Technical indicators calculation utilities for stock analysis.
"""
import numpy as np
import pandas as pd
from typing import Optional, Tuple, Dict, Any


def calculate_sma(prices: pd.Series, window: int = 20) -> pd.Series:
    """
    Calculate Simple Moving Average.
    
    Args:
        prices: Series of prices
        window: Number of periods for the moving average
    
    Returns:
        Series with SMA values
    """
    return prices.rolling(window=window).mean()


def calculate_ema(prices: pd.Series, span: int = 20) -> pd.Series:
    """
    Calculate Exponential Moving Average.
    
    Args:
        prices: Series of prices
        span: Number of periods for the EMA
    
    Returns:
        Series with EMA values
    """
    return prices.ewm(span=span, adjust=False).mean()


def calculate_rsi(prices: pd.Series, period: int = 14) -> pd.Series:
    """
    Calculate Relative Strength Index.
    
    Args:
        prices: Series of closing prices
        period: RSI period (default 14)
    
    Returns:
        Series with RSI values (0-100)
    """
    delta = prices.diff()
    
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    
    avg_gain = gain.rolling(window=period, min_periods=1).mean()
    avg_loss = loss.rolling(window=period, min_periods=1).mean()
    
    # Avoid division by zero
    rs = avg_gain / avg_loss.replace(0, np.inf)
    rsi = 100 - (100 / (1 + rs))
    
    return rsi


def calculate_macd(
    prices: pd.Series,
    fast_period: int = 12,
    slow_period: int = 26,
    signal_period: int = 9
) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """
    Calculate MACD (Moving Average Convergence Divergence).
    
    Args:
        prices: Series of closing prices
        fast_period: Fast EMA period (default 12)
        slow_period: Slow EMA period (default 26)
        signal_period: Signal line period (default 9)
    
    Returns:
        Tuple of (MACD line, Signal line, Histogram)
    """
    fast_ema = prices.ewm(span=fast_period, adjust=False).mean()
    slow_ema = prices.ewm(span=slow_period, adjust=False).mean()
    
    macd_line = fast_ema - slow_ema
    signal_line = macd_line.ewm(span=signal_period, adjust=False).mean()
    histogram = macd_line - signal_line
    
    return macd_line, signal_line, histogram


def calculate_bollinger_bands(
    prices: pd.Series,
    window: int = 20,
    num_std: float = 2.0
) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """
    Calculate Bollinger Bands.
    
    Args:
        prices: Series of closing prices
        window: Moving average period (default 20)
        num_std: Number of standard deviations (default 2)
    
    Returns:
        Tuple of (Upper band, Middle band/SMA, Lower band)
    """
    middle_band = prices.rolling(window=window).mean()
    std = prices.rolling(window=window).std()
    
    upper_band = middle_band + (std * num_std)
    lower_band = middle_band - (std * num_std)
    
    return upper_band, middle_band, lower_band


def calculate_atr(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 14
) -> pd.Series:
    """
    Calculate Average True Range.
    
    Args:
        high: Series of high prices
        low: Series of low prices
        close: Series of closing prices
        period: ATR period (default 14)
    
    Returns:
        Series with ATR values
    """
    prev_close = close.shift(1)
    
    tr1 = high - low
    tr2 = abs(high - prev_close)
    tr3 = abs(low - prev_close)
    
    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = true_range.rolling(window=period).mean()
    
    return atr


def calculate_stochastic(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    k_period: int = 14,
    d_period: int = 3
) -> Tuple[pd.Series, pd.Series]:
    """
    Calculate Stochastic Oscillator.
    
    Args:
        high: Series of high prices
        low: Series of low prices
        close: Series of closing prices
        k_period: %K period (default 14)
        d_period: %D period (default 3)
    
    Returns:
        Tuple of (%K, %D)
    """
    lowest_low = low.rolling(window=k_period).min()
    highest_high = high.rolling(window=k_period).max()
    
    # Avoid division by zero
    denominator = highest_high - lowest_low
    denominator = denominator.replace(0, np.nan)
    
    stoch_k = ((close - lowest_low) / denominator) * 100
    stoch_d = stoch_k.rolling(window=d_period).mean()
    
    return stoch_k, stoch_d


def calculate_obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    """
    Calculate On-Balance Volume.
    
    Args:
        close: Series of closing prices
        volume: Series of volume
    
    Returns:
        Series with OBV values
    """
    direction = np.where(close > close.shift(1), 1, 
                        np.where(close < close.shift(1), -1, 0))
    obv = (direction * volume).cumsum()
    return pd.Series(obv, index=close.index)


def calculate_vwap(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    volume: pd.Series
) -> pd.Series:
    """
    Calculate Volume Weighted Average Price.
    
    Args:
        high: Series of high prices
        low: Series of low prices
        close: Series of closing prices
        volume: Series of volume
    
    Returns:
        Series with VWAP values
    """
    typical_price = (high + low + close) / 3
    vwap = (typical_price * volume).cumsum() / volume.cumsum()
    return vwap


def calculate_support_resistance(
    low: pd.Series,
    high: pd.Series,
    window: int = 20
) -> Tuple[pd.Series, pd.Series]:
    """
    Calculate simple support and resistance levels.
    
    Args:
        low: Series of low prices
        high: Series of high prices
        window: Lookback period (default 20)
    
    Returns:
        Tuple of (Support level, Resistance level)
    """
    support = low.rolling(window=window).min()
    resistance = high.rolling(window=window).max()
    return support, resistance


def calculate_price_momentum(prices: pd.Series, period: int = 10) -> pd.Series:
    """
    Calculate price momentum.
    
    Args:
        prices: Series of closing prices
        period: Momentum period (default 10)
    
    Returns:
        Series with momentum values
    """
    return prices - prices.shift(period)


def calculate_rate_of_change(prices: pd.Series, period: int = 10) -> pd.Series:
    """
    Calculate Rate of Change (ROC).
    
    Args:
        prices: Series of closing prices
        period: ROC period (default 10)
    
    Returns:
        Series with ROC values (percentage)
    """
    return ((prices - prices.shift(period)) / prices.shift(period)) * 100


def calculate_williams_r(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 14
) -> pd.Series:
    """
    Calculate Williams %R.
    
    Args:
        high: Series of high prices
        low: Series of low prices
        close: Series of closing prices
        period: Williams %R period (default 14)
    
    Returns:
        Series with Williams %R values (-100 to 0)
    """
    highest_high = high.rolling(window=period).max()
    lowest_low = low.rolling(window=period).min()
    
    # Avoid division by zero
    denominator = highest_high - lowest_low
    denominator = denominator.replace(0, np.nan)
    
    williams_r = ((highest_high - close) / denominator) * -100
    return williams_r


def calculate_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calculate all technical indicators for a dataframe.
    
    Expected columns: open_price, high_price, low_price, close_price, total_traded_quantity
    
    Args:
        df: DataFrame with OHLCV data
    
    Returns:
        DataFrame with all technical indicators added
    """
    df = df.copy()
    
    # Ensure numeric types
    for col in ['open_price', 'high_price', 'low_price', 'close_price', 'total_traded_quantity']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')
    
    close = df['close_price']
    high = df['high_price']
    low = df['low_price']
    volume = df['total_traded_quantity']
    
    # Moving Averages
    df['SMA_10'] = calculate_sma(close, 10)
    df['SMA_20'] = calculate_sma(close, 20)
    df['SMA_50'] = calculate_sma(close, 50)
    df['EMA_10'] = calculate_ema(close, 10)
    df['EMA_20'] = calculate_ema(close, 20)
    
    # RSI
    df['RSI'] = calculate_rsi(close)
    
    # MACD
    df['MACD'], df['MACD_Signal'], df['MACD_Histogram'] = calculate_macd(close)
    
    # Bollinger Bands
    df['BB_Upper'], df['BB_Middle'], df['BB_Lower'] = calculate_bollinger_bands(close)
    
    # ATR
    df['ATR'] = calculate_atr(high, low, close)
    
    # Stochastic
    df['Stoch_K'], df['Stoch_D'] = calculate_stochastic(high, low, close)
    
    # OBV
    df['OBV'] = calculate_obv(close, volume)
    
    # VWAP
    df['VWAP'] = calculate_vwap(high, low, close, volume)
    
    # Support/Resistance
    df['Support'], df['Resistance'] = calculate_support_resistance(low, high)
    
    # Momentum
    df['Momentum'] = calculate_price_momentum(close)
    df['ROC'] = calculate_rate_of_change(close)
    
    # Williams %R
    df['Williams_R'] = calculate_williams_r(high, low, close)
    
    # Volume indicators
    df['Volume_SMA'] = calculate_sma(volume, 20)
    df['Volume_Ratio'] = volume / df['Volume_SMA']
    
    # Price position within range
    high_low_diff = high - low
    high_low_diff = high_low_diff.replace(0, np.nan)
    df['Price_Position'] = (close - low) / high_low_diff
    
    # Daily returns
    df['Daily_Return'] = close.pct_change()
    df['Log_Return'] = np.log(close / close.shift(1))
    
    # Spread (volatility indicator)
    df['Spread'] = (high - low) / close
    
    return df


def generate_trading_signals(df: pd.DataFrame) -> Dict[str, Any]:
    """
    Generate trading signals based on technical indicators.
    
    Args:
        df: DataFrame with technical indicators calculated
    
    Returns:
        Dictionary with signals and overall strength
    """
    if df.empty:
        return {'signals': [], 'strength': 0, 'recommendation': 'NEUTRAL'}
    
    latest = df.iloc[-1]
    signals = []
    strength = 0
    
    # Moving Average Signals
    if pd.notna(latest.get('SMA_20')) and pd.notna(latest.get('SMA_50')):
        if latest['close_price'] > latest['SMA_20'] > latest['SMA_50']:
            signals.append({
                'type': 'MA_BULLISH',
                'indicator': 'Moving Average',
                'message': 'Price above 20 & 50 SMA - Strong uptrend',
                'strength': 'BULLISH'
            })
            strength += 20
        elif latest['close_price'] < latest['SMA_20'] < latest['SMA_50']:
            signals.append({
                'type': 'MA_BEARISH',
                'indicator': 'Moving Average',
                'message': 'Price below 20 & 50 SMA - Strong downtrend',
                'strength': 'BEARISH'
            })
            strength -= 20
    
    # RSI Signals
    if pd.notna(latest.get('RSI')):
        if latest['RSI'] < 30:
            signals.append({
                'type': 'RSI_OVERSOLD',
                'indicator': 'RSI',
                'message': f"RSI at {latest['RSI']:.1f} - Oversold, potential bounce",
                'strength': 'BULLISH'
            })
            strength += 15
        elif latest['RSI'] > 70:
            signals.append({
                'type': 'RSI_OVERBOUGHT',
                'indicator': 'RSI',
                'message': f"RSI at {latest['RSI']:.1f} - Overbought, potential pullback",
                'strength': 'BEARISH'
            })
            strength -= 15
    
    # MACD Signals
    if pd.notna(latest.get('MACD')) and pd.notna(latest.get('MACD_Signal')):
        if latest['MACD'] > latest['MACD_Signal']:
            signals.append({
                'type': 'MACD_BULLISH',
                'indicator': 'MACD',
                'message': 'MACD above signal line - Bullish momentum',
                'strength': 'BULLISH'
            })
            strength += 10
        else:
            signals.append({
                'type': 'MACD_BEARISH',
                'indicator': 'MACD',
                'message': 'MACD below signal line - Bearish momentum',
                'strength': 'BEARISH'
            })
            strength -= 10
    
    # Bollinger Band Signals
    if pd.notna(latest.get('BB_Lower')) and pd.notna(latest.get('BB_Upper')):
        if latest['close_price'] <= latest['BB_Lower']:
            signals.append({
                'type': 'BB_OVERSOLD',
                'indicator': 'Bollinger Bands',
                'message': 'Price at lower Bollinger Band - Potential bounce',
                'strength': 'BULLISH'
            })
            strength += 10
        elif latest['close_price'] >= latest['BB_Upper']:
            signals.append({
                'type': 'BB_OVERBOUGHT',
                'indicator': 'Bollinger Bands',
                'message': 'Price at upper Bollinger Band - Potential pullback',
                'strength': 'BEARISH'
            })
            strength -= 10
    
    # Volume Signal
    if pd.notna(latest.get('Volume_Ratio')):
        if latest['Volume_Ratio'] > 1.5:
            signals.append({
                'type': 'HIGH_VOLUME',
                'indicator': 'Volume',
                'message': f"Volume {latest['Volume_Ratio']:.1f}x above average - High interest",
                'strength': 'NEUTRAL'
            })
    
    # Stochastic Signals
    if pd.notna(latest.get('Stoch_K')):
        if latest['Stoch_K'] < 20:
            signals.append({
                'type': 'STOCH_OVERSOLD',
                'indicator': 'Stochastic',
                'message': f"Stochastic at {latest['Stoch_K']:.1f} - Oversold",
                'strength': 'BULLISH'
            })
            strength += 10
        elif latest['Stoch_K'] > 80:
            signals.append({
                'type': 'STOCH_OVERBOUGHT',
                'indicator': 'Stochastic',
                'message': f"Stochastic at {latest['Stoch_K']:.1f} - Overbought",
                'strength': 'BEARISH'
            })
            strength -= 10
    
    # Williams %R Signals
    if pd.notna(latest.get('Williams_R')):
        if latest['Williams_R'] < -80:
            signals.append({
                'type': 'WILLIAMS_OVERSOLD',
                'indicator': 'Williams %R',
                'message': f"Williams %R at {latest['Williams_R']:.1f} - Oversold",
                'strength': 'BULLISH'
            })
            strength += 5
        elif latest['Williams_R'] > -20:
            signals.append({
                'type': 'WILLIAMS_OVERBOUGHT',
                'indicator': 'Williams %R',
                'message': f"Williams %R at {latest['Williams_R']:.1f} - Overbought",
                'strength': 'BEARISH'
            })
            strength -= 5
    
    # Clamp strength to -100 to 100
    strength = max(-100, min(100, strength))
    
    # Determine recommendation
    if strength >= 30:
        recommendation = 'STRONG_BUY'
    elif strength >= 10:
        recommendation = 'BUY'
    elif strength <= -30:
        recommendation = 'STRONG_SELL'
    elif strength <= -10:
        recommendation = 'SELL'
    else:
        recommendation = 'HOLD'
    
    return {
        'signals': signals,
        'strength': strength,
        'recommendation': recommendation,
        'signal_count': len(signals)
    }
