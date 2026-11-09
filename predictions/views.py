"""
Views for stock price predictions.
"""
import logging
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from django.shortcuts import get_object_or_404
from datetime import datetime

from stock_data.models import StockData, Stock
from .predict_stock import StockPrediction
from .constants import (
    DATE_FORMAT,
    PREDICTION_TYPE_LSTM,
    PREDICTION_TYPE_RF,
    REQUIRED_PREDICTION_KEYS,
)
from accounts.permissions import IsAdminOrManager
from rest_framework.permissions import AllowAny

logger = logging.getLogger(__name__)


class GetPredictionsView(APIView):
    """
    API view for generating stock price predictions.
    
    Requires admin or manager permissions.
    """
    # permission_classes = [IsAdminOrManager]

    def get(self, request):
        """
        Generate predictions for all stocks.
        
        Query Parameters:
            date: Optional date for prediction (YYYY-MM-DD format)
        
        Returns:
            Response with predictions for all stocks
        """
        prediction_date = request.query_params.get('date', None)
        
        try:
            stock_predictor = StockPrediction()
            predictions_result = stock_predictor.get_prediction(
                StockData,
                prediction_date
            )
            
            logger.info(f"Generated predictions for date: {prediction_date}")
            return Response(
                predictions_result,
                status=status.HTTP_200_OK
            )
        except Exception as e:
            logger.error(f"Error generating predictions: {str(e)}", exc_info=True)
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class AddLSTMPredictionView(APIView):
    """
    API view for adding LSTM model predictions.
    """

    def post(self, request, format=None):
        """
        Add LSTM predictions for stocks.
        
        Expected payload: List of prediction dictionaries with:
            - stock_symbol
            - date
            - predicted_close_price
            - mae
            - r_square
            - overall_mae
            - overall_r_square
        
        Returns:
            Response with success message and any skipped predictions
        """
        return self._process_predictions(request.data, prediction_type=PREDICTION_TYPE_LSTM)

    def _process_predictions(self, predictions_list, prediction_type):
        """
        Process and save predictions.
        
        Args:
            predictions_list: List of prediction dictionaries
            prediction_type: Type of prediction (LSTM or RF)
        
        Returns:
            Response with success message
        """
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
                        {
                            "error": (
                                f"Invalid date format: {prediction['date']}. "
                                f"Use {DATE_FORMAT}."
                            )
                        },
                        status=status.HTTP_400_BAD_REQUEST
                    )

                predicted_close_price = prediction["predicted_close_price"]
                mae = prediction["mae"]
                r_square = prediction["r_square"]
                overall_mae = prediction["overall_mae"]
                overall_r_square = prediction["overall_r_square"]

                stock = get_object_or_404(Stock, symbol=stock_symbol)

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
                logger.warning(
                    f"Skipped {len(skipped_predictions)} predictions for {prediction_type}"
                )

            logger.info(f"Successfully processed {len(predictions_list)} {prediction_type} predictions")
            return Response(response_message, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"Error processing predictions: {str(e)}", exc_info=True)
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )

    def _validate_prediction(self, prediction):
        """
        Validate prediction dictionary has all required keys.
        
        Args:
            prediction: Prediction dictionary
        
        Returns:
            Response with error if validation fails, None otherwise
        """
        missing_keys = [
            key for key in REQUIRED_PREDICTION_KEYS
            if key not in prediction
        ]
        if missing_keys:
            return Response(
                {"error": f"Missing keys in prediction: {missing_keys}"},
                status=status.HTTP_400_BAD_REQUEST
            )
        return None

    def _parse_date(self, date_str):
        """
        Parse date string to date object.
        
        Args:
            date_str: Date string in YYYY-MM-DD format
        
        Returns:
            Date object or None if invalid
        """
        try:
            return datetime.strptime(date_str, DATE_FORMAT).date()
        except ValueError:
            return None

    def _update_stock_data(self, stock, target_date, predicted_close_price, prediction_type):
        """
        Update stock data with predicted price.
        
        Args:
            stock: Stock instance
            target_date: Target date for prediction
            predicted_close_price: Predicted close price
            prediction_type: Type of prediction (LSTM or RF)
        
        Returns:
            None if successful, error message string if failed
        """
        try:
            stock_data = StockData.objects.get(stock=stock, date=target_date)
            if prediction_type == PREDICTION_TYPE_LSTM:
                stock_data.LSTM_predicted_close_price = predicted_close_price
            else:
                stock_data.RF_predicted_close_price = predicted_close_price
            stock_data.save()
            return None
        except StockData.DoesNotExist:
            return "StockData does not exist for this date"

    def _update_stock_metrics(
        self, stock, mae, r_square, overall_mae, overall_r_square, prediction_type
    ):
        """
        Update stock model metrics.
        
        Args:
            stock: Stock instance
            mae: Mean Absolute Error
            r_square: R-squared value
            overall_mae: Overall Mean Absolute Error
            overall_r_square: Overall R-squared value
            prediction_type: Type of prediction (LSTM or RF)
        """
        if prediction_type == PREDICTION_TYPE_LSTM:
            stock.LSTM_Mean_Absolute_Error = mae
            stock.LSTM_R_Square = r_square if r_square is not None else stock.LSTM_R_Square
            stock.Overall_LSTM_Mean_Absolute_Error = overall_mae
            stock.Overall_LSTM_R_Square = (
                overall_r_square if overall_r_square is not None
                else stock.Overall_LSTM_R_Square
            )
        else:
            stock.RF_Mean_Absolute_Error = mae
            stock.RF_R_Square = r_square if r_square is not None else stock.RF_R_Square
            stock.Overall_RF_Mean_Absolute_Error = overall_mae
            stock.Overall_RF_R_Square = (
                overall_r_square if overall_r_square is not None
                else stock.Overall_RF_R_Square
            )
        stock.save()


class AddRFPredictionView(AddLSTMPredictionView):
    """
    API view for adding Random Forest model predictions.
    """

    def post(self, request, format=None):
        """
        Add Random Forest predictions for stocks.
        
        Expected payload: Same as LSTM predictions.
        
        Returns:
            Response with success message and any skipped predictions
        """
        return self._process_predictions(request.data, prediction_type=PREDICTION_TYPE_RF)
