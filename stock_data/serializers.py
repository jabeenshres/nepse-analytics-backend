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
    Serializer for Stock model with nested stock data.
    
    Used for listing stocks with their associated data.
    """
    data = StockDataSerializer(many=True, read_only=True)

    class Meta:
        model = Stock
        fields = '__all__'
