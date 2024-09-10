from rest_framework import serializers, validators
from .models import RawData

class RawDataSerializer(serializers.ModelSerializer):
    class Meta:
        model = RawData
        fields = '__all__'
        validators = [
            validators.UniqueTogetherValidator(
                queryset=model.objects.all(),
                fields=('date', 'symbol'),
                message=("Data already exists.")
            )
        ]
