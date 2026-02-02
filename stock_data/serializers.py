"""
Serializers for stock data models.
"""
from rest_framework import serializers, validators
from .models import StockData, Stock, Portfolio, PortfolioHolding, Trade, BacktestResult


class StockDataSerializer(serializers.ModelSerializer):
    """
    Serializer for StockData model.
    
    Provides validation and serialization for stock data entries.
    """
    class Meta:
        model = StockData
        fields = '__all__'
        validators = [
            validators.UniqueTogetherValidator(
                queryset=StockData.objects.all(),
                fields=('date', 'stock'),
                message="Data already exists for this stock and date."
            )
        ]

    def validate(self, attrs):
        """
        Validate stock data fields.
        
        Args:
            attrs: Dictionary of field values
        
        Returns:
            attrs: Validated attributes
        
        Raises:
            serializers.ValidationError: If validation fails
        """
        # Validate price relationships
        if attrs.get('high_price') and attrs.get('low_price'):
            if attrs['high_price'] < attrs['low_price']:
                raise serializers.ValidationError(
                    "High price cannot be less than low price."
                )

        if attrs.get('close_price') and attrs.get('open_price'):
            if attrs['close_price'] < 0 or attrs['open_price'] < 0:
                raise serializers.ValidationError(
                    "Prices cannot be negative."
                )

        return attrs


class StockSerializer(serializers.ModelSerializer):
    """
    Serializer for Stock model.
    
    Provides validation and serialization for stock information.
    """
    class Meta:
        model = Stock
        fields = '__all__'

    def validate(self, attrs):
        """
        Validate stock fields.
        
        Args:
            attrs: Dictionary of field values
        
        Returns:
            attrs: Validated attributes
        
        Raises:
            serializers.ValidationError: If validation fails
        """
        if attrs.get('fifty_two_weeks_high') and attrs.get('fifty_two_weeks_low'):
            if attrs['fifty_two_weeks_high'] < attrs['fifty_two_weeks_low']:
                raise serializers.ValidationError(
                    "52-week high cannot be less than 52-week low."
                )

        return attrs


class StockListSerializer(serializers.ModelSerializer):
    """
    Serializer for Stock model with limited nested stock data.
    
    Used for listing stocks with their most recent data entries only.
    By default, includes only the latest 5 entries to prevent large responses.
    """
    data = serializers.SerializerMethodField()
    data_count = serializers.SerializerMethodField()

    class Meta:
        model = Stock
        fields = '__all__'

    def get_data(self, obj):
        """
        Get limited stock data entries (latest 5 by default).
        
        Can be controlled via context:
        - include_data: bool - Whether to include nested data
        - data_limit: int - Number of entries to include (default: 5)
        """
        include_data = self.context.get('include_data', True)
        data_limit = self.context.get('data_limit', 5)
        
        if not include_data:
            return []
        
        # Get latest entries, limited by data_limit
        stock_data = obj.data.all()[:data_limit]
        return StockDataSerializer(stock_data, many=True).data

    def get_data_count(self, obj):
        """Get total count of stock data entries for this stock."""
        return obj.data.count()


class PortfolioHoldingSerializer(serializers.ModelSerializer):
    """
    Serializer for PortfolioHolding model.
    """
    stock_symbol = serializers.CharField(source='stock.symbol', read_only=True)
    stock_name = serializers.CharField(source='stock.security_name', read_only=True)
    market_value = serializers.DecimalField(
        max_digits=15, decimal_places=2, read_only=True
    )
    profit_loss = serializers.DecimalField(
        max_digits=15, decimal_places=2, read_only=True
    )
    profit_loss_percentage = serializers.DecimalField(
        max_digits=10, decimal_places=2, read_only=True
    )

    class Meta:
        model = PortfolioHolding
        fields = [
            'id', 'portfolio', 'stock', 'stock_symbol', 'stock_name',
            'quantity', 'average_buy_price', 'current_price',
            'market_value', 'profit_loss', 'profit_loss_percentage',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class PortfolioSerializer(serializers.ModelSerializer):
    """
    Serializer for Portfolio model.
    """
    holdings = PortfolioHoldingSerializer(many=True, read_only=True)
    total_return = serializers.DecimalField(
        max_digits=10, decimal_places=2, read_only=True
    )
    holdings_count = serializers.SerializerMethodField()

    class Meta:
        model = Portfolio
        fields = [
            'id', 'name', 'description', 'initial_capital', 'current_value',
            'total_return', 'holdings_count', 'holdings',
            'is_active', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'current_value', 'created_at', 'updated_at']

    def get_holdings_count(self, obj):
        """Get count of holdings in portfolio."""
        return obj.holdings.count()


class TradeSerializer(serializers.ModelSerializer):
    """
    Serializer for Trade model.
    """
    stock_symbol = serializers.CharField(source='stock.symbol', read_only=True)
    stock_name = serializers.CharField(source='stock.security_name', read_only=True)
    return_amount = serializers.DecimalField(
        max_digits=15, decimal_places=2, read_only=True
    )
    return_percentage = serializers.DecimalField(
        max_digits=10, decimal_places=2, read_only=True
    )

    class Meta:
        model = Trade
        fields = [
            'id', 'portfolio', 'stock', 'stock_symbol', 'stock_name',
            'trade_type', 'quantity', 'entry_price', 'exit_price',
            'entry_date', 'exit_date', 'return_amount', 'return_percentage',
            'notes', 'created_at'
        ]
        read_only_fields = ['id', 'created_at']

    def validate(self, attrs):
        """Validate trade data."""
        if attrs.get('exit_price') and attrs.get('entry_price'):
            if attrs['exit_price'] < 0 or attrs['entry_price'] < 0:
                raise serializers.ValidationError("Prices cannot be negative.")
        
        if attrs.get('exit_date') and attrs.get('entry_date'):
            if attrs['exit_date'] < attrs['entry_date']:
                raise serializers.ValidationError(
                    "Exit date cannot be before entry date."
                )
        
        return attrs


class BacktestResultSerializer(serializers.ModelSerializer):
    """
    Serializer for BacktestResult model.
    """
    stock_symbol = serializers.CharField(source='stock.symbol', read_only=True)

    class Meta:
        model = BacktestResult
        fields = [
            'id', 'stock', 'stock_symbol', 'strategy_name',
            'start_date', 'end_date', 'initial_capital', 'final_value',
            'total_return', 'win_rate', 'max_drawdown', 'sharpe_ratio',
            'total_trades', 'winning_trades', 'losing_trades',
            'parameters', 'created_at'
        ]
        read_only_fields = ['id', 'created_at']
