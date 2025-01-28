from django.apps import apps
import numpy as np
from sklearn.preprocessing import MinMaxScaler
from collections import defaultdict
from datetime import datetime

class StockPrediction:
    def getPrediction(self, stockData, prediction_date=None):
        # Get the models from the StockDataConfig (ensure they are loaded only once)
        stock_data_config = apps.get_app_config('StockData')  # Get the StockDataConfig instance
        lstm_model = stock_data_config.lstm_model  # LSTM model
        rf_model = stock_data_config.rf_model  # Random Forest model
        scaler = MinMaxScaler()  # Use a single scaler for all stocks

        predictions = []  # To store predictions for each stock

        try:
            # Parse the prediction date if provided
            if prediction_date:
                prediction_date = datetime.strptime(prediction_date, '%Y-%m-%d').date()

            # Fetch all stock data and group it by stock symbol in one query
            all_stock_data = stockData.objects.order_by('stock__symbol', '-date').values(
                'id', 'stock__symbol', 'date', 'open_price', 'high_price', 'low_price', 
                'close_price', 'total_traded_quantity'
            )

            # Group stock data by symbol
            grouped_data = defaultdict(list)
            for entry in all_stock_data:
                grouped_data[entry['stock__symbol']].append(entry)

            # Process each stock symbol
            for stock_symbol, stock_entries in grouped_data.items():
                # Ensure there are at least 6 data points for prediction
                if len(stock_entries) < 6:
                    predictions.append({
                        'symbol': stock_symbol,
                        'error': 'Not enough data for prediction'
                    })
                    continue

                # Determine the target date for prediction
                if prediction_date:
                    # Find the data points before the prediction date
                    stock_entries = [
                        entry for entry in stock_entries if entry['date'] < prediction_date
                    ]
                else:
                    # Use the latest date
                    prediction_date = stock_entries[0]['date']

                # Ensure at least 6 data points exist before the target date
                if len(stock_entries) < 6:
                    predictions.append({
                        'symbol': stock_symbol,
                        'error': f'Not enough data before {prediction_date} for prediction'
                    })
                    continue

                # Take the latest 6 entries for prediction
                stock_data = stock_entries[:6]

                # Prepare data for prediction
                data = np.array([[d['open_price'], d['high_price'], d['low_price'], 
                                  d['close_price'], d['total_traded_quantity']] for d in stock_data])

                # Normalize the data
                normalized_data = scaler.fit_transform(data)

                # Prepare data for LSTM (3D input: [samples, time_steps, features])
                X_lstm = normalized_data.reshape((1, 6, 5))  # Last 6 days, 5 features

                # Predict using the LSTM model
                predicted_lstm_price = lstm_model.predict(X_lstm)

                # Prepare data for Random Forest (Flatten 6 days of data into 1D: [samples, features])
                X_rf = normalized_data[-6:].reshape(1, -1)  # Flatten to 1 row with 30 features

                # Predict using the Random Forest model
                predicted_rf_price = rf_model.predict(X_rf)

                # Inverse transform LSTM prediction
                data_padded_lstm = np.zeros((1, 5))  # Placeholder with 5 features
                data_padded_lstm[:, 3] = predicted_lstm_price.flatten()  # Set predicted 'close_price'
                predicted_lstm_close_price = scaler.inverse_transform(data_padded_lstm)[0, 3]

                # Inverse transform Random Forest prediction
                data_padded_rf = np.zeros((1, 5))  # Placeholder with 5 features
                data_padded_rf[:, 3] = predicted_rf_price.flatten()  # Set predicted 'close_price'
                predicted_rf_close_price = scaler.inverse_transform(data_padded_rf)[0, 3]

                # Append the predictions to the list
                predictions.append({
                    'symbol': stock_symbol,
                    'predicted_lstm_close_price': predicted_lstm_close_price,
                    'predicted_rf_close_price': predicted_rf_close_price,
                    'date': prediction_date
                })

                # Update the database with the predicted close prices for the target date
                stock_data_obj = stockData.objects.filter(
                    stock__symbol=stock_symbol, date=prediction_date
                ).first()
                if stock_data_obj:
                    stock_data_obj.LTSM_predicted_close_price = predicted_lstm_close_price
                    stock_data_obj.RF_predicted_close_price = predicted_rf_close_price
                    stock_data_obj.save()

            # Return the predictions
            return {'predictions': predictions}

        except Exception as e:
            return {'error': str(e)}
