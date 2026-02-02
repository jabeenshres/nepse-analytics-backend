from rest_framework import viewsets, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import AllowAny
from django.db.models import Max, Q, F
from datetime import datetime

from .models import StockData, Stock
from .serializers import StockDataSerializer, StockSerializer, StockListSerializer
from .utils import NepalStockScraper
from .structure_data import StockSequenceGenerator
from .predict_stock import StockPrediction
from accounts.permissions import IsAdminOrManager


class StockDataViewSet(viewsets.ModelViewSet):
    queryset = StockData.objects.all()
    serializer_class = StockDataSerializer


class StockViewSet(viewsets.ModelViewSet):
    queryset = Stock.objects.all()
    serializer_class = StockSerializer

    def get_serializer_class(self):
        if self.action in ['list', 'retrieve']:
            return StockListSerializer
        return StockSerializer


class LoadStockData(APIView):
    permission_classes = [IsAdminOrManager]

    def post(self, request, format=None):
        days_back = request.data.get("date", 0)
        headless = request.data.get("headless", True)  # Default to headless mode
        scraper = NepalStockScraper(headless=headless)

        try:
            scraper.load_page("https://www.nepalstock.com/today-price")
            scraper.loop_through_dates(Stock, StockData, days_back)
            return Response({
                "message": "Data has been loaded successfully",
                "days_back": days_back,
                "headless": headless
            }, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        finally:
            scraper.close()


class StructStockData(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        sequence_generator = StockSequenceGenerator()
        stock_dataframe = sequence_generator.fetch_data(StockData)
        json_data = stock_dataframe.to_dict(orient="records")
        return Response({'data': json_data}, status=status.HTTP_200_OK)


class LatestStockDataViewSet(viewsets.ViewSet):
    permission_classes = [AllowAny]

    def list(self, request):
        search_query = request.query_params.get('search', None)
        is_gainer = request.query_params.get('gainer', None)
        target_date_str = request.query_params.get('date', None)

        target_date = self._get_target_date(target_date_str)
        if not target_date:
            return Response(
                {'error': 'No data available for the specified or latest date.'},
                status=status.HTTP_404_NOT_FOUND
            )

        queryset = StockData.objects.filter(date=target_date).select_related('stock')
        queryset = self._apply_filters(queryset, search_query, is_gainer)

        stock_data_by_symbol = self._build_stock_data_dict(queryset)
        response_data = list(stock_data_by_symbol.values())

        paginator = PageNumberPagination()
        paginator.page_size = 20
        paginated_data = paginator.paginate_queryset(response_data, request)

        return paginator.get_paginated_response(paginated_data)

    def _get_target_date(self, date_str):
        if date_str:
            try:
                return datetime.strptime(date_str, '%Y-%m-%d').date()
            except ValueError:
                return None
        else:
            latest_entry = StockData.objects.aggregate(latest_date=Max('date'))
            return latest_entry['latest_date']

    def _apply_filters(self, queryset, search_query, is_gainer):
        if search_query:
            queryset = queryset.filter(
                Q(stock__symbol__icontains=search_query) |
                Q(stock__security_name__icontains=search_query)
            )

        if is_gainer in ['true', 'True', '1']:
            queryset = queryset.filter(close_price__gt=F('open_price'))
        elif is_gainer in ['false', 'False', '0']:
            queryset = queryset.filter(close_price__lte=F('open_price'))

        return queryset

    def _build_stock_data_dict(self, queryset):
        stock_data_by_symbol = {}
        for stock_data_entry in queryset:
            stock = stock_data_entry.stock
            if stock not in stock_data_by_symbol:
                stock_data_by_symbol[stock] = {
                    'id': stock.id,
                    'symbol': stock.symbol,
                    'security_id': stock.security_id,
                    'security_name': stock.security_name,
                    'fifty_two_weeks_high': stock.fifty_two_weeks_high,
                    'fifty_two_weeks_low': stock.fifty_two_weeks_low,
                    'data': []
                }
            stock_data_by_symbol[stock]['data'].append({
                'date': stock_data_entry.date,
                'open_price': stock_data_entry.open_price,
                'high_price': stock_data_entry.high_price,
                'low_price': stock_data_entry.low_price,
                'close_price': stock_data_entry.close_price,
                'total_traded_quantity': stock_data_entry.total_traded_quantity,
                'total_traded_value': stock_data_entry.total_traded_value,
                'previous_day_close_price': stock_data_entry.previous_day_close_price,
                'last_updated_price': stock_data_entry.last_updated_price,
                'total_trades': stock_data_entry.total_trades,
                'average_traded_price': stock_data_entry.average_traded_price,
                'market_capitalization': stock_data_entry.market_capitalization,
            })
        return stock_data_by_symbol


class GetPredictions(APIView):
    permission_classes = [IsAdminOrManager]

    def get(self, request):
        prediction_date = request.query_params.get('date', None)
        stock_predictor = StockPrediction()
        predictions_result = stock_predictor.get_prediction(StockData, prediction_date)
        return Response(predictions_result, status=status.HTTP_200_OK)


class AddLSTMPrediction(APIView):
    permission_classes = [AllowAny]

    def post(self, request, format=None):
        return self._process_predictions(request.data, prediction_type='LSTM')

    def _process_predictions(self, predictions_list, prediction_type):
        try:
            if not isinstance(predictions_list, list):
                return Response(
                    {"error": "Invalid data format. Expected a list of predictions."},
                    status=status.HTTP_400_BAD_REQUEST
                )

            skipped_predictions = []

            for prediction in predictions_list:
                validation_error = self._validate_prediction(prediction)
                if validation_error:
                    return validation_error

                stock_symbol = prediction["stock_symbol"]
                target_date = self._parse_date(prediction["date"])
                if not target_date:
                    return Response(
                        {"error": f"Invalid date format: {prediction['date']}. Use YYYY-MM-DD."},
                        status=status.HTTP_400_BAD_REQUEST
                    )

                predicted_close_price = prediction["predicted_close_price"]
                mae = prediction["mae"]
                r_square = prediction["r_square"]
                overall_mae = prediction["overall_mae"]
                overall_r_square = prediction["overall_r_square"]

                try:
                    stock = Stock.objects.get(symbol=stock_symbol)
                except Stock.DoesNotExist:
                    return Response(
                        {"error": f"Stock with symbol '{stock_symbol}' does not exist."},
                        status=status.HTTP_400_BAD_REQUEST
                    )

                skip_reason = self._update_stock_data(
                    stock, target_date, predicted_close_price, prediction_type
                )
                if skip_reason:
                    skipped_predictions.append({
                        "stock_symbol": stock_symbol,
                        "date": str(target_date),
                        "reason": skip_reason
                    })
                    continue

                self._update_stock_metrics(
                    stock, mae, r_square, overall_mae, overall_r_square, prediction_type
                )

            response_message = {"message": "Predictions updated successfully"}
            if skipped_predictions:
                response_message["skipped_predictions"] = skipped_predictions

            return Response(response_message, status=status.HTTP_200_OK)

        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    def _validate_prediction(self, prediction):
        required_keys = [
            "stock_symbol", "date", "predicted_close_price",
            "mae", "r_square", "overall_mae", "overall_r_square"
        ]
        missing_keys = [key for key in required_keys if key not in prediction]
        if missing_keys:
            return Response(
                {"error": f"Missing keys in prediction: {missing_keys}"},
                status=status.HTTP_400_BAD_REQUEST
            )
        return None

    def _parse_date(self, date_str):
        try:
            return datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            return None

    def _update_stock_data(self, stock, target_date, predicted_close_price, prediction_type):
        try:
            stock_data = StockData.objects.get(stock=stock, date=target_date)
            if prediction_type == 'LSTM':
                stock_data.LSTM_predicted_close_price = predicted_close_price
            else:
                stock_data.RF_predicted_close_price = predicted_close_price
            stock_data.save()
            return None
        except StockData.DoesNotExist:
            return "StockData does not exist for this date"

    def _update_stock_metrics(self, stock, mae, r_square, overall_mae, overall_r_square, prediction_type):
        if prediction_type == 'LSTM':
            stock.LSTM_Mean_Absolute_Error = mae
            stock.LSTM_R_Square = r_square if r_square is not None else stock.LSTM_R_Square
            stock.Overall_LSTM_Mean_Absolute_Error = overall_mae
            stock.Overall_LSTM_R_Square = overall_r_square if overall_r_square is not None else stock.Overall_LSTM_R_Square
        else:
            stock.RF_Mean_Absolute_Error = mae
            stock.RF_R_Square = r_square if r_square is not None else stock.RF_R_Square
            stock.Overall_RF_Mean_Absolute_Error = overall_mae
            stock.Overall_RF_R_Square = overall_r_square if overall_r_square is not None else stock.Overall_RF_R_Square
        stock.save()


class AddRFPrediction(AddLSTMPrediction):
    permission_classes = [AllowAny]

    def post(self, request, format=None):
        return self._process_predictions(request.data, prediction_type='RF')
