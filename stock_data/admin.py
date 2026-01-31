from django.contrib import admin
from .models import Stock, StockData


@admin.register(Stock)
class StockAdmin(admin.ModelAdmin):
    list_display = ['symbol', 'security_name', 'security_id']
    search_fields = ['symbol', 'security_name']
    list_filter = ['symbol']


@admin.register(StockData)
class StockDataAdmin(admin.ModelAdmin):
    list_display = ['stock', 'date', 'close_price', 'open_price', 'high_price', 'low_price']
    list_filter = ['date', 'stock']
    search_fields = ['stock__symbol', 'stock__security_name']
    date_hierarchy = 'date'
