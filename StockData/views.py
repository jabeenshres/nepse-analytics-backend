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
from rest_framework.permissions import AllowAny
from django.core.exceptions import ObjectDoesNotExist
from datetime import datetime
from accounts.permissions import IsAdmin


class StockDataViewSet(viewsets.ModelViewSet):
    queryset = StockData.objects.all()
    serializer_class = StockDataSerializer
    
class StockViewSet(viewsets.ModelViewSet):
    permission_classes = [AllowAny]
    queryset = Stock.objects.all()
    serializer_class = StockSerializer
    def get_serializer_class(self):
        if self.action == 'list' or self.action == 'retrieve':
            return StockListSerializer
        return StockSerializer
 
# view to load the database     
class LoadStockData(APIView):
    permission_classes = [AllowAny]
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
    permission_classes = [AllowAny]
    def get(self, request):
        generator = StockSequenceGenerator()
        df = generator.fetch_data(StockData)

        # Convert DataFrame to JSON-safe dictionary
        json_data = df.to_dict(orient="records")

        return Response({'data': json_data}, status=status.HTTP_200_OK)

            

class LatestStockDataViewSet(viewsets.ViewSet):
    permission_classes = [IsAdmin]
    def list(self, request):
        # Get filter parameters
        search = request.query_params.get('search', None)
        gainer = request.query_params.get('gainer', None)
        exact_date = request.query_params.get('date', None)  

        # Determine which date to filter
        if exact_date:
            try:
                # Validate the exact date format
                exact_date = datetime.strptime(exact_date, '%Y-%m-%d').date()
            except ValueError:
                return Response({'error': 'Invalid date format. Use YYYY-MM-DD.'}, status=400)
        else:
            # Fallback to the latest date if no exact date is provided
            latest_entry = StockData.objects.aggregate(latest_date=Max('date'))
            exact_date = latest_entry['latest_date']

        if not exact_date:
            return Response({'error': 'No data available for the specified or latest date.'}, status=404)

        # Filter StockData for the specified date
        queryset = StockData.objects.filter(date=exact_date).select_related('stock')

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
        paginator.page_size = 20  # Customize the page size if needed
        paginated_data = paginator.paginate_queryset(response_data, request)

        return paginator.get_paginated_response(paginated_data)
    
class GetPredicitons(APIView):
    permission_classes = [AllowAny]
    def get(self, request):
        prediction_date = request.query_params.get('date', None)  
        # Initialize prediction class
        predictor = StockPrediction()
        
        # Get predictions using your class
        df = predictor.getPrediction(StockData,prediction_date)

        # Return predictions as JSON response
        return Response(df, status=status.HTTP_200_OK)


class AddLTSMPrediction(APIView):
    permission_classes = [AllowAny]
    def post(self, request, format=None):
        try:
            predictions_data = request.data

            # Validate input format
            if not isinstance(predictions_data, list):
                return Response({"error": "Invalid data format. Expected a list of predictions."},
                                status=status.HTTP_400_BAD_REQUEST)

            skipped_predictions = []  # To track skipped predictions

            for prediction in predictions_data:
                # Required keys for each prediction
                required_keys = ["stock_symbol", "date", "predicted_close_price", "mae", "r_square", "overall_mae", "overall_r_square"]
                missing_keys = [key for key in required_keys if key not in prediction]
                if missing_keys:
                    return Response({"error": f"Missing keys in prediction: {missing_keys}"},
                                    status=status.HTTP_400_BAD_REQUEST)

                stock_symbol = prediction["stock_symbol"]

                # Parse and validate date
                try:
                    date = datetime.strptime(prediction["date"], "%Y-%m-%d").date()
                except ValueError:
                    return Response({"error": f"Invalid date format: {prediction['date']}. Use YYYY-MM-DD."},
                                    status=status.HTTP_400_BAD_REQUEST)

                predicted_close_price = prediction["predicted_close_price"]
                mae = prediction["mae"]
                r_square = prediction["r_square"]
                overall_mae = prediction["overall_mae"]
                overall_r_square = prediction["overall_r_square"]

                # Fetch the Stock object
                try:
                    stock = Stock.objects.get(symbol=stock_symbol)
                except Stock.DoesNotExist:
                    return Response({"error": f"Stock with symbol '{stock_symbol}' does not exist."},
                                    status=status.HTTP_400_BAD_REQUEST)

                # Update StockData for the given date
                try:
                    stock_data = StockData.objects.get(stock=stock, date=date)
                    stock_data.LTSM_predicted_close_price = predicted_close_price
                    stock_data.save()
                except StockData.DoesNotExist:
                    # Log skipped predictions and continue
                    skipped_predictions.append({
                        "stock_symbol": stock_symbol,
                        "date": str(date),
                        "reason": "StockData does not exist for this date"
                    })
                    continue

                # Update the stock's MAE and R_Square fields
                stock.LTSM_Mean_Absolute_Error = mae
                stock.LTSM_R_Square = r_square if r_square is not None else stock.LTSM_R_Square
                stock.Overall_LTSM_Mean_Absolute_Error = overall_mae
                stock.Overall_LTSM_R_Square = overall_r_square if overall_r_square is not None else stock.Overall_LTSM_R_Square
                stock.save()

            response_message = {"message": "Predictions updated successfully"}
            if skipped_predictions:
                response_message["skipped_predictions"] = skipped_predictions

            return Response(response_message, status=status.HTTP_200_OK)

        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

class AddRFPrediction(APIView):
    permission_classes = [AllowAny]
    def post(self, request, format=None):
        try:
            predictions_data = request.data

            # Validate input format
            if not isinstance(predictions_data, list):
                return Response({"error": "Invalid data format. Expected a list of predictions."},
                                status=status.HTTP_400_BAD_REQUEST)

            skipped_predictions = []  # To track skipped predictions

            for prediction in predictions_data:
                # Required keys for each prediction
                required_keys = ["stock_symbol", "date", "predicted_close_price", "mae", "r_square", "overall_mae", "overall_r_square"]
                missing_keys = [key for key in required_keys if key not in prediction]
                if missing_keys:
                    return Response({"error": f"Missing keys in prediction: {missing_keys}"},
                                    status=status.HTTP_400_BAD_REQUEST)

                stock_symbol = prediction["stock_symbol"]

                # Parse and validate date
                try:
                    date = datetime.strptime(prediction["date"], "%Y-%m-%d").date()
                except ValueError:
                    return Response({"error": f"Invalid date format: {prediction['date']}. Use YYYY-MM-DD."},
                                    status=status.HTTP_400_BAD_REQUEST)

                predicted_close_price = prediction["predicted_close_price"]
                mae = prediction["mae"]
                r_square = prediction["r_square"]
                overall_mae = prediction["overall_mae"]
                overall_r_square = prediction["overall_r_square"]

                # Fetch the Stock object
                try:
                    stock = Stock.objects.get(symbol=stock_symbol)
                except Stock.DoesNotExist:
                    return Response({"error": f"Stock with symbol '{stock_symbol}' does not exist."},
                                    status=status.HTTP_400_BAD_REQUEST)

                # Update StockData for the given date
                try:
                    stock_data = StockData.objects.get(stock=stock, date=date)
                    stock_data.RF_predicted_close_price = predicted_close_price
                    stock_data.save()
                except StockData.DoesNotExist:
                    # Log skipped predictions and continue
                    skipped_predictions.append({
                        "stock_symbol": stock_symbol,
                        "date": str(date),
                        "reason": "StockData does not exist for this date"
                    })
                    continue

                # Update the stock's MAE and R_Square fields
                stock.RF_Mean_Absolute_Error = mae
                stock.RF_R_Square = r_square if r_square is not None else stock.RF_R_Square
                stock.Overall_RF_Mean_Absolute_Error = overall_mae
                stock.Overall_RF_R_Square = overall_r_square if overall_r_square is not None else stock.Overall_RF_R_Square
                stock.save()

            response_message = {"message": "Predictions updated successfully"}
            if skipped_predictions:
                response_message["skipped_predictions"] = skipped_predictions

            return Response(response_message, status=status.HTTP_200_OK)

        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)