from rest_framework import viewsets
from .models import StockData
from .serializers import StockDataSerializer
from rest_framework.views import APIView
from rest_framework.response import Response
from StockData.utils import NepalStockScraper
from rest_framework import status

class StockDataViewSet(viewsets.ModelViewSet):
    queryset = StockData.objects.all()
    serializer_class = StockDataSerializer
    
class LoadStockData(APIView):
    def get(self, request, format=None):
        scraper = NepalStockScraper()
        try:
            scraper.load_page("https://www.nepalstock.com/today-price")
            scraper.loop_through_dates(StockData)
            return Response("Data has been loaded successfully", status=status.HTTP_200_OK)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        finally:
            scraper.close()
            
        
        
