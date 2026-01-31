"""
Models for stock data management.
"""
from django.db import models
from django.core.validators import MinValueValidator


class Stock(models.Model):
    """
    Represents a stock/security in the Nepal Stock Exchange.
    """
    symbol = models.CharField(max_length=100, unique=True, db_index=True)
    security_id = models.IntegerField(unique=True, db_index=True)
    security_name = models.CharField(max_length=200)
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
        ]

    def __str__(self):
        return f"{self.stock.symbol} - {self.date}"
