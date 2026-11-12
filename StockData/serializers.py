from rest_framework import serializers, validators
from .models import StockData, Stock


class StockDataSerializer(serializers.ModelSerializer):
    class Meta:
        model = StockData
        fields = '__all__'
        validators = [
            validators.UniqueTogetherValidator(
                queryset=StockData.objects.all(),
                fields=('date', 'stock'),
                message=("Data already exists.")
            )
        ]


class StockSerializer(serializers.ModelSerializer):
    class Meta:
        model = Stock
        fields = '__all__'


class StockListSerializer(serializers.ModelSerializer):
    data = StockDataSerializer(many=True)

    class Meta:
        model = Stock
        fields = '__all__'
