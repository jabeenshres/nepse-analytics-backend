"""
Models for stock data management.
"""
from django.db import models
from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator


class Stock(models.Model):
    """
    Represents a stock/security in the Nepal Stock Exchange.
    """
    # Stock type choices
    STOCK_TYPE_CHOICES = [
        ('stock', 'Stock'),
        ('mutual_fund', 'Mutual Fund'),
        ('debenture', 'Debenture'),
        ('promoter_share', 'Promoter Share'),
        ('preferred_stock', 'Preferred Stock'),
    ]
    
    symbol = models.CharField(max_length=100, unique=True, db_index=True)
    security_id = models.IntegerField(unique=True, db_index=True)
    security_name = models.CharField(max_length=200)
    stock_type = models.CharField(
        max_length=20,
        choices=STOCK_TYPE_CHOICES,
        default='stock',
        db_index=True,
        help_text="Type of security: stock, mutual_fund, debenture, etc."
    )
    fifty_two_weeks_high = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)]
    )
    fifty_two_weeks_low = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)]
    )
    
    # LSTM Model Metrics
    LSTM_Mean_Absolute_Error = models.DecimalField(
        max_digits=10, decimal_places=5, null=True, blank=True
    )
    Overall_LSTM_Mean_Absolute_Error = models.DecimalField(
        max_digits=10, decimal_places=5, null=True, blank=True
    )
    LSTM_R_Square = models.DecimalField(
        max_digits=10, decimal_places=5, null=True, blank=True
    )
    Overall_LSTM_R_Square = models.DecimalField(
        max_digits=10, decimal_places=5, null=True, blank=True
    )
    
    # Random Forest Model Metrics
    RF_Mean_Absolute_Error = models.DecimalField(
        max_digits=10, decimal_places=5, null=True, blank=True
    )
    Overall_RF_Mean_Absolute_Error = models.DecimalField(
        max_digits=10, decimal_places=5, null=True, blank=True
    )
    RF_R_Square = models.DecimalField(
        max_digits=10, decimal_places=5, null=True, blank=True
    )
    Overall_RF_R_Square = models.DecimalField(
        max_digits=10, decimal_places=5, null=True, blank=True
    )

    class Meta:
        verbose_name = 'Stock'
        verbose_name_plural = 'Stocks'
        ordering = ['symbol']
        indexes = [
            models.Index(fields=['symbol']),
            models.Index(fields=['security_id']),
            models.Index(fields=['stock_type']),
            models.Index(fields=['stock_type', 'symbol']),
        ]

    def __str__(self):
        return self.symbol


class StockData(models.Model):
    """
    Represents daily trading data for a stock.
    """
    stock = models.ForeignKey(
        'Stock',
        on_delete=models.CASCADE,
        related_name="data",
        db_index=True
    )
    date = models.DateField(db_index=True)
    open_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)]
    )
    high_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)]
    )
    low_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)]
    )
    close_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)]
    )
    total_traded_quantity = models.IntegerField(validators=[MinValueValidator(0)])
    total_traded_value = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        validators=[MinValueValidator(0)]
    )
    previous_day_close_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)]
    )
    last_updated_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)]
    )
    total_trades = models.IntegerField(validators=[MinValueValidator(0)])
    average_traded_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)]
    )
    market_capitalization = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)]
    )
    
    # Predicted prices
    LSTM_predicted_close_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)]
    )
    RF_predicted_close_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)]
    )

    class Meta:
        verbose_name = 'Stock Data'
        verbose_name_plural = 'Stock Data'
        ordering = ['-date']
        unique_together = [['stock', 'date']]
        indexes = [
            models.Index(fields=['date']),
            models.Index(fields=['stock', 'date']),
            models.Index(fields=['stock', '-date']),  # Optimized for latest data queries
            models.Index(fields=['close_price']),  # For price-based filtering
        ]

    def __str__(self):
        return f"{self.stock.symbol} - {self.date}"


class Portfolio(models.Model):
    """
    Represents a user's stock portfolio.
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='portfolios'
    )
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True, null=True)
    initial_capital = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        validators=[MinValueValidator(0)]
    )
    current_value = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        validators=[MinValueValidator(0)],
        default=0
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = 'Portfolio'
        verbose_name_plural = 'Portfolios'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', '-created_at']),
        ]

    def __str__(self):
        return f"{self.user.username}'s {self.name}"

    @property
    def total_return(self):
        """Calculate total return percentage."""
        if self.initial_capital and self.initial_capital > 0:
            return ((self.current_value - self.initial_capital) / self.initial_capital) * 100
        return 0


class PortfolioHolding(models.Model):
    """
    Represents a stock holding within a portfolio.
    """
    portfolio = models.ForeignKey(
        Portfolio,
        on_delete=models.CASCADE,
        related_name='holdings'
    )
    stock = models.ForeignKey(
        Stock,
        on_delete=models.CASCADE,
        related_name='holdings'
    )
    quantity = models.IntegerField(validators=[MinValueValidator(1)])
    average_buy_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)]
    )
    current_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)],
        null=True,
        blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Portfolio Holding'
        verbose_name_plural = 'Portfolio Holdings'
        unique_together = [['portfolio', 'stock']]
        indexes = [
            models.Index(fields=['portfolio', 'stock']),
        ]

    def __str__(self):
        return f"{self.portfolio.name} - {self.stock.symbol} ({self.quantity})"

    @property
    def market_value(self):
        """Calculate current market value of holding."""
        if self.current_price:
            return self.quantity * self.current_price
        return self.quantity * self.average_buy_price

    @property
    def profit_loss(self):
        """Calculate profit/loss for this holding."""
        if self.current_price:
            return (self.current_price - self.average_buy_price) * self.quantity
        return 0

    @property
    def profit_loss_percentage(self):
        """Calculate profit/loss percentage."""
        if self.average_buy_price and self.average_buy_price > 0 and self.current_price:
            return ((self.current_price - self.average_buy_price) / self.average_buy_price) * 100
        return 0


class Trade(models.Model):
    """
    Represents a trade transaction for backtesting and portfolio tracking.
    """
    TRADE_TYPE_CHOICES = [
        ('BUY', 'Buy'),
        ('SELL', 'Sell'),
    ]

    portfolio = models.ForeignKey(
        Portfolio,
        on_delete=models.CASCADE,
        related_name='trades',
        null=True,
        blank=True
    )
    stock = models.ForeignKey(
        Stock,
        on_delete=models.CASCADE,
        related_name='trades'
    )
    trade_type = models.CharField(max_length=4, choices=TRADE_TYPE_CHOICES)
    quantity = models.IntegerField(validators=[MinValueValidator(1)])
    entry_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)]
    )
    exit_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)],
        null=True,
        blank=True
    )
    entry_date = models.DateField()
    exit_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Trade'
        verbose_name_plural = 'Trades'
        ordering = ['-entry_date', '-created_at']
        indexes = [
            models.Index(fields=['stock', '-entry_date']),
            models.Index(fields=['portfolio', '-entry_date']),
            models.Index(fields=['trade_type']),
        ]

    def __str__(self):
        return f"{self.trade_type} {self.stock.symbol} @ {self.entry_price}"

    @property
    def return_amount(self):
        """Calculate return amount for completed trades."""
        if self.exit_price and self.trade_type == 'BUY':
            return (self.exit_price - self.entry_price) * self.quantity
        return None

    @property
    def return_percentage(self):
        """Calculate return percentage for completed trades."""
        if self.exit_price and self.entry_price > 0 and self.trade_type == 'BUY':
            return ((self.exit_price - self.entry_price) / self.entry_price) * 100
        return None


class BacktestResult(models.Model):
    """
    Stores results of backtesting strategies.
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='backtest_results',
        null=True,
        blank=True
    )
    stock = models.ForeignKey(
        Stock,
        on_delete=models.CASCADE,
        related_name='backtest_results',
        null=True,
        blank=True
    )
    strategy_name = models.CharField(max_length=100)
    start_date = models.DateField()
    end_date = models.DateField()
    initial_capital = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        validators=[MinValueValidator(0)]
    )
    final_value = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        validators=[MinValueValidator(0)]
    )
    total_return = models.DecimalField(
        max_digits=10,
        decimal_places=4,
        null=True,
        blank=True
    )
    win_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        null=True,
        blank=True
    )
    max_drawdown = models.DecimalField(
        max_digits=10,
        decimal_places=4,
        null=True,
        blank=True
    )
    sharpe_ratio = models.DecimalField(
        max_digits=10,
        decimal_places=4,
        null=True,
        blank=True
    )
    total_trades = models.IntegerField(default=0)
    winning_trades = models.IntegerField(default=0)
    losing_trades = models.IntegerField(default=0)
    parameters = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Backtest Result'
        verbose_name_plural = 'Backtest Results'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['strategy_name']),
        ]

    def __str__(self):
        return f"{self.strategy_name} - {self.stock.symbol if self.stock else 'All'} ({self.start_date} to {self.end_date})"


class FloorsheetData(models.Model):
    """
    Represents individual floor sheet transactions scraped from merolagani.com.
    Each record is a single trade executed on the NEPSE floor.
    """
    stock = models.ForeignKey(
        Stock,
        on_delete=models.CASCADE,
        related_name='floorsheet_data',
        db_index=True
    )
    transaction_date = models.DateField(db_index=True)
    transaction_no = models.BigIntegerField(
        help_text="Unique transaction number from NEPSE"
    )
    buyer_broker = models.IntegerField(
        help_text="Buyer broker number"
    )
    seller_broker = models.IntegerField(
        help_text="Seller broker number"
    )
    quantity = models.IntegerField(
        validators=[MinValueValidator(1)],
        help_text="Number of shares traded"
    )
    rate = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)],
        help_text="Price per share"
    )
    amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        validators=[MinValueValidator(0)],
        help_text="Total transaction amount (quantity * rate)"
    )
    scraped_at = models.DateTimeField(
        auto_now_add=True,
        help_text="Timestamp when this data was scraped"
    )

    class Meta:
        verbose_name = 'Floorsheet Data'
        verbose_name_plural = 'Floorsheet Data'
        ordering = ['-transaction_date', '-transaction_no']
        # Ensure we don't have duplicate transactions for a stock
        unique_together = [['stock', 'transaction_no']]
        indexes = [
            models.Index(fields=['stock', '-transaction_date']),
            models.Index(fields=['transaction_date']),
            models.Index(fields=['buyer_broker']),
            models.Index(fields=['seller_broker']),
            models.Index(fields=['stock', 'buyer_broker']),
            models.Index(fields=['stock', 'seller_broker']),
        ]

    def __str__(self):
        return f"{self.stock.symbol} - TXN#{self.transaction_no} ({self.transaction_date})"

    @property
    def is_same_broker(self):
        """Check if buyer and seller are the same broker (self-trade)."""
        return self.buyer_broker == self.seller_broker


class NepseIndex(models.Model):
    """
    Represents NEPSE market indices and sub-indices data.
    Data scraped from nepalstock.com/indices
    """
    INDEX_CHOICES = [
        (51, 'Banking SubIndex'),
        (52, 'Hotels And Tourism Index'),
        (53, 'Others Index'),
        (54, 'HydroPower Index'),
        (55, 'Development Bank Index'),
        (56, 'Manufacturing And Processing'),
        (57, 'Sensitive Index'),
        (58, 'NEPSE Index'),
        (59, 'Non Life Insurance'),
        (60, 'Finance Index'),
        (61, 'Trading Index'),
        (62, 'Float Index'),
        (63, 'Sensitive Float Index'),
        (64, 'Microfinance Index'),
        (65, 'Life Insurance'),
        (66, 'Mutual Fund'),
        (67, 'Investment Index'),
    ]

    index_id = models.IntegerField(
        choices=INDEX_CHOICES,
        db_index=True,
        help_text="Index identifier from NEPSE"
    )
    index_name = models.CharField(
        max_length=100,
        help_text="Name of the index/sub-index"
    )
    date = models.DateField(db_index=True)
    close = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(0)],
        help_text="Closing value of the index"
    )
    high = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(0)],
        help_text="High value of the index"
    )
    low = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(0)],
        help_text="Low value of the index"
    )
    absolute_change = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        help_text="Absolute change from previous day"
    )
    percentage_change = models.DecimalField(
        max_digits=8,
        decimal_places=4,
        help_text="Percentage change from previous day"
    )
    fifty_two_weeks_high = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(0)],
        help_text="52 weeks high value"
    )
    fifty_two_weeks_low = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(0)],
        help_text="52 weeks low value"
    )
    turnover_value = models.DecimalField(
        max_digits=20,
        decimal_places=2,
        validators=[MinValueValidator(0)],
        help_text="Total turnover value in rupees"
    )
    turnover_volume = models.BigIntegerField(
        validators=[MinValueValidator(0)],
        help_text="Total traded volume/quantity"
    )
    total_transactions = models.IntegerField(
        validators=[MinValueValidator(0)],
        help_text="Total number of transactions"
    )
    scraped_at = models.DateTimeField(
        auto_now_add=True,
        help_text="Timestamp when this data was scraped"
    )

    class Meta:
        verbose_name = 'NEPSE Index'
        verbose_name_plural = 'NEPSE Indices'
        ordering = ['index_id', '-date']
        unique_together = [['index_id', 'date']]
        indexes = [
            models.Index(fields=['index_id', '-date']),
            models.Index(fields=['date']),
            models.Index(fields=['index_name']),
            models.Index(fields=['-date', 'index_id']),
        ]

    def __str__(self):
        return f"{self.index_name} - {self.date} (Close: {self.close})"

    @classmethod
    def get_index_name(cls, index_id):
        """Get index name from index_id."""
        for id_val, name in cls.INDEX_CHOICES:
            if id_val == index_id:
                return name
        return None

    @classmethod
    def get_all_index_ids(cls):
        """Get all available index IDs."""
        return [id_val for id_val, _ in cls.INDEX_CHOICES]


class StockAnalyticsCache(models.Model):
    """
    Cache for computed stock analytics to avoid recomputation.
    Stores the results of comprehensive stock analysis for a specific date.
    Supports multiple analytics types: top_stocks, breakout_watchlist, accumulation_alerts
    """
    CACHE_TYPE_CHOICES = [
        ('top_stocks', 'Top Stocks Analysis'),
        ('breakout_watchlist', 'Breakout Watchlist Analysis'),
        ('accumulation_alerts', 'Accumulation Alerts Analysis'),
    ]
    
    stock = models.ForeignKey(Stock, on_delete=models.CASCADE, related_name='analytics_cache')
    analysis_date = models.DateField(db_index=True, help_text="Date for which analysis was computed")
    cache_type = models.CharField(
        max_length=30,
        choices=CACHE_TYPE_CHOICES,
        default='top_stocks',
        db_index=True,
        help_text="Type of analytics cached"
    )
    computed_at = models.DateTimeField(auto_now_add=True, db_index=True)
    
    # Cached analytics data (stored as JSON)
    analytics_data = models.JSONField(
        help_text="Cached comprehensive analytics results including scores, signals, recommendations"
    )
    
    class Meta:
        db_table = 'stock_data_stockanalyticscache'
        unique_together = [['stock', 'analysis_date', 'cache_type']]
        indexes = [
            models.Index(fields=['analysis_date', 'computed_at']),
            models.Index(fields=['stock', 'analysis_date', 'cache_type']),
            models.Index(fields=['cache_type', 'analysis_date']),
        ]
        verbose_name = 'Stock Analytics Cache'
        verbose_name_plural = 'Stock Analytics Cache'
    
    def __str__(self):
        return f"{self.stock.symbol} - {self.analysis_date} - {self.get_cache_type_display()} (Computed: {self.computed_at})"
