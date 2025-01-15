from rest_framework import viewsets
from .models import StockData, Stock
from .serializers import StockDataSerializer, StockSerializer, StockListSerializer
from rest_framework.views import APIView
from rest_framework.response import Response
from StockData.utils import NepalStockScraper
from StockData.structure_data import StockSequenceGenerator
from rest_framework import status
from django.db.models import Max
from rest_framework.pagination import PageNumberPagination
from django.db.models import Max, Q, F
from StockData.predict_stock import StockPrediction
from rest_framework.permissions import IsAuthenticated

class StockDataViewSet(viewsets.ModelViewSet):
    # permission_classes = [IsAuthenticated]
    queryset = StockData.objects.all()
    serializer_class = StockDataSerializer
    
class StockViewSet(viewsets.ModelViewSet):
    # permission_classes = [IsAuthenticated]
    queryset = Stock.objects.all()
    serializer_class = StockSerializer
    def get_serializer_class(self):
        if self.action == 'list' or self.action == 'retrieve':
            return StockListSerializer
        return StockSerializer
 
# view to load the database     
class LoadStockData(APIView):
    # permission_classes = [IsAuthenticated]
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
            
# view to provide data for model trainging
class StructStockData(APIView):
    # permission_classes = [IsAuthenticated]
    def get(self, request):
        generator = StockSequenceGenerator()
        df = generator.fetch_data(StockData)
        return Response({'data':df}, status=status.HTTP_200_OK)
            

class LatestStockDataViewSet(viewsets.ViewSet):
    def list(self, request):
        # Get filter parameters
        search = request.query_params.get('search', None)
        gainer = request.query_params.get('gainer', None)

        # Get the latest date from StockData
        latest_entry = StockData.objects.aggregate(latest_date=Max('date'))
        latest_date = latest_entry['latest_date']
        
        # Start with filtering StockData for the latest date
        queryset = StockData.objects.filter(date=latest_date).select_related('stock')
        
         # Apply combined filter for symbol and security name
        if search:
            queryset = queryset.filter(
                Q(stock__symbol__icontains=search) |
                Q(stock__security_name__icontains=search)
            )

        # Apply filters based on query parameters
        if gainer in ['true', 'True', '1']:
            queryset = queryset.filter(close_price__gt=F('open_price'))
        elif gainer in ['false', 'False', '0']:
            queryset = queryset.filter(close_price__lte=F('open_price'))

        # Prepare data for the response
        stock_data_dict = {}
        for stock_data in queryset:
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

        # Apply pagination
        paginator = PageNumberPagination()
        paginator.page_size = 10  # Customize the page size if needed
        paginated_data = paginator.paginate_queryset(response_data, request)

        return paginator.get_paginated_response(paginated_data)
    
class GetPredicitons(APIView):
    def get(self, request):
        # Initialize prediction class
        predictor = StockPrediction()
        
        # Get predictions using your class
        df = predictor.getPrediction(StockData)

        # Return predictions as JSON response
        return Response(df, status=status.HTTP_200_OK)
