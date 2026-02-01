"""
Serializers for stock data models.
"""
from rest_framework import serializers, validators
from .models import StockData, Stock


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
