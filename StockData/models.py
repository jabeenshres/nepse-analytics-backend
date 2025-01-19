from django.db import models


# model for stock data in each date 
class StockData(models.Model):
    stock = models.ForeignKey('Stock', on_delete=models.CASCADE, related_name="data")
    date = models.DateField()
    open_price = models.DecimalField(max_digits=10, decimal_places=2)
    high_price = models.DecimalField(max_digits=10, decimal_places=2)
    low_price = models.DecimalField(max_digits=10, decimal_places=2)
    close_price = models.DecimalField(max_digits=10, decimal_places=2)
    total_traded_quantity = models.IntegerField()
    total_traded_value = models.DecimalField(max_digits=15, decimal_places=2)
    previous_day_close_price = models.DecimalField(max_digits=10, decimal_places=2)
    last_updated_price = models.DecimalField(max_digits=10, decimal_places=2)
    total_trades = models.IntegerField()
    average_traded_price = models.DecimalField(max_digits=10, decimal_places=2)
    market_capitalization = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    LTSM_predicted_close_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True) 
    RF_predicted_close_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True) 

    def __str__(self):
        return f"{self.stock.symbol} - {self.date}"

# model for stock 
class Stock(models.Model):
    symbol = models.CharField(max_length=100, unique=True)
    security_id = models.IntegerField(unique=True)
    security_name = models.CharField(max_length=200)
    fifty_two_weeks_high = models.DecimalField(max_digits=10, decimal_places=2)
    fifty_two_weeks_low = models.DecimalField(max_digits=10, decimal_places=2)
    LTSM_Mean_Absolute_Error = models.DecimalField(max_digits=10, decimal_places=5, null=True, blank=True)
    Overall_LTSM_Mean_Absolute_Error = models.DecimalField(max_digits=10, decimal_places=5, null=True, blank=True)
    LTSM_R_Square = models.DecimalField(max_digits=10, decimal_places=5, null=True, blank=True)
    Overall_LTSM_R_Square = models.DecimalField(max_digits=10, decimal_places=5, null=True, blank=True)
    RF_Mean_Absolute_Error = models.DecimalField(max_digits=10, decimal_places=5, null=True, blank=True)
    Overall_RF_Mean_Absolute_Error = models.DecimalField(max_digits=10, decimal_places=5, null=True, blank=True)
    RF_R_Square = models.DecimalField(max_digits=10, decimal_places=5, null=True, blank=True)
    Overall_RF_R_Square = models.DecimalField(max_digits=10, decimal_places=5, null=True, blank=True)

    def __str__(self):
        return self.symbol