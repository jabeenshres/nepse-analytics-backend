from django.db import models

class RawData(models.Model):
    date = models.DateField()
    symbol = models.CharField(max_length=10)
    close_price = models.DecimalField(max_digits=10, decimal_places=2)
    open_price = models.DecimalField(max_digits=10, decimal_places=2)
    high_price = models.DecimalField(max_digits=10, decimal_places=2)
    low_price = models.DecimalField(max_digits=10, decimal_places=2)
    total_traded_quantity = models.BigIntegerField()
    total_traded_value = models.DecimalField(max_digits=20, decimal_places=2)
    total_trades = models.IntegerField()
    ltp = models.DecimalField(max_digits=10, decimal_places=2)
    previous_day_close_price = models.DecimalField(max_digits=10, decimal_places=2)
    average_traded_price = models.DecimalField(max_digits=10, decimal_places=2)
    fifty_two_week_high = models.DecimalField(max_digits=10, decimal_places=2)
    fifty_two_week_low = models.DecimalField(max_digits=10, decimal_places=2)
    market_capitalization = models.DecimalField(max_digits=20, decimal_places=2)
    

    def __str__(self):
        return f"{self.symbol} - {self.date}"
