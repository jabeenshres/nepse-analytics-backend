from django.apps import apps
import numpy as np
from sklearn.preprocessing import MinMaxScaler
from collections import defaultdict
from datetime import datetime

MIN_DATA_POINTS_REQUIRED = 6
TIME_STEPS = 6
FEATURE_COUNT = 5
CLOSE_PRICE_INDEX = 3


class StockPrediction:
    def get_prediction(self, stock_data_model, prediction_date=None):
        stock_data_config = apps.get_app_config('StockData')
        lstm_model = stock_data_config.lstm_model
        rf_model = stock_data_config.rf_model
        scaler = MinMaxScaler()

        predictions = []

        try:
            if prediction_date:
                prediction_date = datetime.strptime(prediction_date, '%Y-%m-%d').date()

            all_stock_data = stock_data_model.objects.order_by(
                'stock__symbol', '-date'
            ).values(
                'id', 'stock__symbol', 'date', 'open_price', 'high_price',
                'low_price', 'close_price', 'total_traded_quantity'
            )

            grouped_data_by_symbol = defaultdict(list)
            for stock_entry in all_stock_data:
                grouped_data_by_symbol[stock_entry['stock__symbol']].append(stock_entry)

            for stock_symbol, stock_entries in grouped_data_by_symbol.items():
                if len(stock_entries) < MIN_DATA_POINTS_REQUIRED:
                    predictions.append({
                        'symbol': stock_symbol,
                        'error': 'Not enough data for prediction'
                    })
                    continue

                if prediction_date:
                    stock_entries = [
                        entry for entry in stock_entries
                        if entry['date'] < prediction_date
                    ]
                else:
                    prediction_date = stock_entries[0]['date']

                if len(stock_entries) < MIN_DATA_POINTS_REQUIRED:
                    predictions.append({
                        'symbol': stock_symbol,
                        'error': f'Not enough data before {prediction_date} for prediction'
                    })
                    continue

                recent_stock_data = stock_entries[:MIN_DATA_POINTS_REQUIRED]

                feature_matrix = np.array([[
                    d['open_price'], d['high_price'], d['low_price'],
                    d['close_price'], d['total_traded_quantity']
                ] for d in recent_stock_data])

                normalized_data = scaler.fit_transform(feature_matrix)

                lstm_input = normalized_data.reshape((1, TIME_STEPS, FEATURE_COUNT))
                lstm_prediction = lstm_model.predict(lstm_input)

                rf_input = normalized_data[-TIME_STEPS:].reshape(1, -1)
                rf_prediction = rf_model.predict(rf_input)

                lstm_predicted_close_price = self._inverse_transform_prediction(
                    scaler, lstm_prediction, CLOSE_PRICE_INDEX
                )
                rf_predicted_close_price = self._inverse_transform_prediction(
                    scaler, rf_prediction, CLOSE_PRICE_INDEX
                )

                predictions.append({
                    'symbol': stock_symbol,
                    'predicted_lstm_close_price': lstm_predicted_close_price,
                    'predicted_rf_close_price': rf_predicted_close_price,
                    'date': prediction_date
                })

                self._update_database_predictions(
                    stock_data_model, stock_symbol, prediction_date,
                    lstm_predicted_close_price, rf_predicted_close_price
                )

            return {'predictions': predictions}

        except Exception as e:
            return {'error': str(e)}

    def _inverse_transform_prediction(self, scaler, prediction, close_price_index):
        padded_data = np.zeros((1, FEATURE_COUNT))
        padded_data[:, close_price_index] = prediction.flatten()
        return scaler.inverse_transform(padded_data)[0, close_price_index]

    def _update_database_predictions(
        self, stock_data_model, stock_symbol, target_date,
        lstm_predicted_price, rf_predicted_price
    ):
        stock_data_instance = stock_data_model.objects.filter(
            stock__symbol=stock_symbol, date=target_date
        ).first()
        if stock_data_instance:
            stock_data_instance.LSTM_predicted_close_price = lstm_predicted_price
            stock_data_instance.RF_predicted_close_price = rf_predicted_price
            stock_data_instance.save()
