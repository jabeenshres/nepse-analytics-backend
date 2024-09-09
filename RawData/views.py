from rest_framework import viewsets
from .models import RawData
from .serializers import RawDataSerializer

class RawDataViewSet(viewsets.ModelViewSet):
    queryset = RawData.objects.all()
    serializer_class = RawDataSerializer
