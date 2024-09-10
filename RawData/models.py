from django.db import models

class RawData(models.Model):
    date = models.DateField()
    symbol = models.CharField(max_length=10)
    open_price = models.DecimalField(max_digits=10, decimal_places=2)
    high_price = models.DecimalField(max_digits=10, decimal_places=2)
    low_price = models.DecimalField(max_digits=10, decimal_places=2)
    close_price = models.DecimalField(max_digits=10, decimal_places=2)
    total_traded_quantity = models.IntegerField()
    total_traded_value = models.DecimalField(max_digits=15, decimal_places=2)
    previous_day_close_price = models.DecimalField(max_digits=10, decimal_places=2)
    fifty_two_weeks_high = models.DecimalField(max_digits=10, decimal_places=2)
    fifty_two_weeks_low = models.DecimalField(max_digits=10, decimal_places=2)
    last_updated_price = models.DecimalField(max_digits=10, decimal_places=2)
    total_trades = models.IntegerField()
    average_traded_price = models.DecimalField(max_digits=10, decimal_places=2)
    market_capitalization = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)

    

    def __str__(self):
        return f"{self.symbol} - {self.date}"
