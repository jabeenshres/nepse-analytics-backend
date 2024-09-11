from rest_framework import serializers, validators
from .models import StockData

class StockDataSerializer(serializers.ModelSerializer):
    class Meta:
        model = StockData
        fields = '__all__'
        validators = [
            validators.UniqueTogetherValidator(
                queryset=model.objects.all(),
                fields=('date', 'symbol'),
                message=("Data already exists.")
            )
        ]
