from rest_framework import viewsets
from .models import StockData, Stock
from .serializers import StockDataSerializer, StockSerializer, StockListSerializer
from rest_framework.views import APIView
from rest_framework.response import Response
from StockData.utils import NepalStockScraper
from rest_framework import status
from django.db.models import Max

class StockDataViewSet(viewsets.ModelViewSet):
    queryset = StockData.objects.all()
    serializer_class = StockDataSerializer
    
class StockViewSet(viewsets.ModelViewSet):
    queryset = Stock.objects.all()
    serializer_class = StockSerializer
    def get_serializer_class(self):
        if self.action == 'list' or self.action == 'retrieve':
            return StockListSerializer
        return StockSerializer
    
class LoadStockData(APIView):
    def post(self, request, format=None):
        date_value = request.data.get("date",0)
        scraper = NepalStockScraper()
        
        try:
            scraper.load_page("https://www.nepalstock.com/today-price")
            scraper.loop_through_dates(Stock,StockData,date_value)
            return Response("Data has been loaded successfully", status=status.HTTP_200_OK)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        finally:
            scraper.close()
            
            


class LatestStockDataViewSet(viewsets.ViewSet):
    def list(self, request):
        # Get the latest date from StockData
        latest_entry = StockData.objects.aggregate(latest_date=Max('date'))
        latest_date = latest_entry['latest_date']
        
        # Get all StockData entries for the latest date
        latest_stock_data = StockData.objects.filter(date=latest_date).select_related('stock')
        
        # Prepare data for the response
        stock_data_dict = {}
        
        for stock_data in latest_stock_data:
            stock = stock_data.stock
            if stock not in stock_data_dict:
                stock_data_dict[stock] = {
                    'id': stock.id,
                    'symbol': stock.symbol,
                    'security_id': stock.security_id,
                    'security_name': stock.security_name,
                    'fifty_two_weeks_high': stock.fifty_two_weeks_high,
                    'fifty_two_weeks_low': stock.fifty_two_weeks_low,
                    'data': []
                }
            stock_data_dict[stock]['data'].append({
                'date': stock_data.date,
                'open_price': stock_data.open_price,
                'high_price': stock_data.high_price,
                'low_price': stock_data.low_price,
                'close_price': stock_data.close_price,
                'total_traded_quantity': stock_data.total_traded_quantity,
                'total_traded_value': stock_data.total_traded_value,
                'previous_day_close_price': stock_data.previous_day_close_price,
                'last_updated_price': stock_data.last_updated_price,
                'total_trades': stock_data.total_trades,
                'average_traded_price': stock_data.average_traded_price,
                'market_capitalization': stock_data.market_capitalization,
            })
        
        # Serialize the data into the required format
        response_data = list(stock_data_dict.values())
        return Response(response_data)
            
        
