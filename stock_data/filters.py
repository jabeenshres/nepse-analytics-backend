"""
Filter classes for stock_data app.
"""
import django_filters
from django.db import models
from .models import StockData, Stock


class StockDataFilter(django_filters.FilterSet):
    """
    Filter class for StockData model.
    """
    # Date range filtering
    date = django_filters.DateFilter(field_name='date', lookup_expr='exact')
    date__gte = django_filters.DateFilter(field_name='date', lookup_expr='gte')
    date__lte = django_filters.DateFilter(field_name='date', lookup_expr='lte')
    
    # Stock symbol filtering
    stock__symbol = django_filters.CharFilter(
        field_name='stock__symbol',
        lookup_expr='iexact'
    )
    stock__symbol__icontains = django_filters.CharFilter(
        field_name='stock__symbol',
        lookup_expr='icontains'
    )
    
    # Stock name filtering
    stock__security_name__icontains = django_filters.CharFilter(
        field_name='stock__security_name',
        lookup_expr='icontains'
    )
    
    # Price filtering
    close_price__gte = django_filters.NumberFilter(
        field_name='close_price',
        lookup_expr='gte'
    )
    close_price__lte = django_filters.NumberFilter(
        field_name='close_price',
        lookup_expr='lte'
    )
    
    # Gainer/Loser filtering
    is_gainer = django_filters.BooleanFilter(
        method='filter_gainer',
        label='Is Gainer (close_price > open_price)'
    )
    
    # Has predictions
    has_lstm_prediction = django_filters.BooleanFilter(
        field_name='LSTM_predicted_close_price',
        lookup_expr='isnull',
        exclude=True
    )
    has_rf_prediction = django_filters.BooleanFilter(
        field_name='RF_predicted_close_price',
        lookup_expr='isnull',
        exclude=True
    )
    
    # Ordering
    ordering = django_filters.OrderingFilter(
        fields=(
            ('date', 'date'),
            ('close_price', 'close_price'),
            ('total_traded_quantity', 'volume'),
            ('total_traded_value', 'value'),
        ),
        field_labels={
            'date': 'Date',
            'close_price': 'Close Price',
            'total_traded_quantity': 'Volume',
            'total_traded_value': 'Traded Value',
        }
    )

    def filter_gainer(self, queryset, name, value):
        """
        Filter by gainers (close_price > open_price) or losers.
        """
        if value is True:
            return queryset.filter(close_price__gt=models.F('open_price'))
        elif value is False:
            return queryset.filter(close_price__lte=models.F('open_price'))
        return queryset

    class Meta:
        model = StockData
        fields = [
            'date',
            'stock__symbol',
            'close_price',
            'is_gainer',
        ]


class StockFilter(django_filters.FilterSet):
    """
    Filter class for Stock model.
    """
    # Symbol filtering
    symbol = django_filters.CharFilter(lookup_expr='iexact')
    symbol__icontains = django_filters.CharFilter(
        field_name='symbol',
        lookup_expr='icontains'
    )
    
    # Security name filtering
    security_name__icontains = django_filters.CharFilter(
        field_name='security_name',
        lookup_expr='icontains'
    )
    
    # Security ID filtering
    security_id = django_filters.NumberFilter(lookup_expr='exact')
    
    # Has ML metrics
    has_lstm_metrics = django_filters.BooleanFilter(
        method='filter_has_lstm_metrics'
    )
    has_rf_metrics = django_filters.BooleanFilter(
        method='filter_has_rf_metrics'
    )
    
    # Ordering
    ordering = django_filters.OrderingFilter(
        fields=(
            ('symbol', 'symbol'),
            ('security_name', 'security_name'),
            ('security_id', 'security_id'),
        ),
        field_labels={
            'symbol': 'Symbol',
            'security_name': 'Security Name',
            'security_id': 'Security ID',
        }
    )

    def filter_has_lstm_metrics(self, queryset, name, value):
        """Filter stocks that have LSTM metrics."""
        if value is True:
            return queryset.exclude(LSTM_Mean_Absolute_Error__isnull=True)
        elif value is False:
            return queryset.filter(LSTM_Mean_Absolute_Error__isnull=True)
        return queryset

    def filter_has_rf_metrics(self, queryset, name, value):
        """Filter stocks that have RF metrics."""
        if value is True:
            return queryset.exclude(RF_Mean_Absolute_Error__isnull=True)
        elif value is False:
            return queryset.filter(RF_Mean_Absolute_Error__isnull=True)
        return queryset

    class Meta:
        model = Stock
        fields = [
            'symbol',
            'security_id',
            'security_name',
        ]
