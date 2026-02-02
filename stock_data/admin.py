from django.contrib import admin
from .models import Stock, StockData, Portfolio, PortfolioHolding, Trade, BacktestResult, FloorsheetData, NepseIndex


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


@admin.register(Portfolio)
class PortfolioAdmin(admin.ModelAdmin):
    list_display = ['name', 'user', 'initial_capital', 'current_value', 'is_active', 'created_at']
    list_filter = ['is_active', 'created_at']
    search_fields = ['name', 'user__username']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(PortfolioHolding)
class PortfolioHoldingAdmin(admin.ModelAdmin):
    list_display = ['portfolio', 'stock', 'quantity', 'average_buy_price', 'current_price']
    list_filter = ['portfolio', 'stock']
    search_fields = ['portfolio__name', 'stock__symbol']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(Trade)
class TradeAdmin(admin.ModelAdmin):
    list_display = ['stock', 'trade_type', 'quantity', 'entry_price', 'exit_price', 'entry_date', 'exit_date']
    list_filter = ['trade_type', 'entry_date', 'stock']
    search_fields = ['stock__symbol', 'portfolio__name']
    date_hierarchy = 'entry_date'
    readonly_fields = ['created_at']


@admin.register(BacktestResult)
class BacktestResultAdmin(admin.ModelAdmin):
    list_display = ['strategy_name', 'stock', 'start_date', 'end_date', 'total_return', 'win_rate', 'created_at']
    list_filter = ['strategy_name', 'created_at']
    search_fields = ['strategy_name', 'stock__symbol', 'user__username']
    readonly_fields = ['created_at']


@admin.register(FloorsheetData)
class FloorsheetDataAdmin(admin.ModelAdmin):
    list_display = [
        'stock', 'transaction_date', 'transaction_no', 
        'buyer_broker', 'seller_broker', 'quantity', 'rate', 'amount'
    ]
    list_filter = ['transaction_date', 'stock', 'buyer_broker', 'seller_broker']
    search_fields = ['stock__symbol', 'transaction_no']
    date_hierarchy = 'transaction_date'
    readonly_fields = ['scraped_at']
    ordering = ['-transaction_date', '-transaction_no']
    
    def get_queryset(self, request):
        """Optimize query by selecting related stock."""
        return super().get_queryset(request).select_related('stock')


@admin.register(NepseIndex)
class NepseIndexAdmin(admin.ModelAdmin):
    list_display = [
        'index_name', 'date', 'close', 'high', 'low',
        'absolute_change', 'percentage_change', 'turnover_value', 'turnover_volume'
    ]
    list_filter = ['index_id', 'index_name', 'date']
    search_fields = ['index_name']
    date_hierarchy = 'date'
    readonly_fields = ['scraped_at']
    ordering = ['-date', 'index_id']
    
    fieldsets = (
        ('Index Information', {
            'fields': ('index_id', 'index_name', 'date')
        }),
        ('Price Data', {
            'fields': ('close', 'high', 'low', 'absolute_change', 'percentage_change')
        }),
        ('52 Week Range', {
            'fields': ('fifty_two_weeks_high', 'fifty_two_weeks_low')
        }),
        ('Volume Data', {
            'fields': ('turnover_value', 'turnover_volume', 'total_transactions')
        }),
        ('Metadata', {
            'fields': ('scraped_at',),
            'classes': ('collapse',)
        }),
    )
