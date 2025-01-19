from django.apps import apps
import numpy as np
from sklearn.preprocessing import MinMaxScaler
from .models import StockData

class StockPrediction:
    def getPrediction(self, stockData):
        # Get the models from the StockDataConfig (ensure they are loaded only once)
        stock_data_config = apps.get_app_config('StockData')  # Get the StockDataConfig instance
        lstm_model = stock_data_config.lstm_model  # LSTM model
        rf_model = stock_data_config.rf_model  # Random Forest model
        scaler = MinMaxScaler()  # Use a single scaler for all stocks

        predictions = []  # To store predictions for each stock

        try:
            # Get the distinct stock symbols
            distinct_stocks = stockData.objects.values('stock__symbol').distinct()

            # Loop through each distinct stock symbol
            for stock_entry in distinct_stocks:
                stock_symbol = stock_entry['stock__symbol']
                
                # Fetch the latest 6 days of stock data for the current stock symbol
                stock_data = stockData.objects.filter(stock__symbol=stock_symbol).order_by('-date')[:6]

                if len(stock_data) < 6:
                    predictions.append({
                        'symbol': stock_symbol,
                        'error': 'Not enough data for prediction'
                    })
                    continue

                # Prepare the data for prediction
                data = np.array([[d.open_price, d.high_price, d.low_price, d.close_price, d.total_traded_quantity] for d in stock_data])
                
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

                # Find the most recent date in the stock data for this symbol
                most_recent_date = stock_data[0].date

                # Check if a prediction already exists for this stock on the most recent date
                existing_prediction = StockData.objects.filter(
                    stock__symbol=stock_symbol,
                    date=most_recent_date
                ).first()

                if existing_prediction:
                    # Update the existing prediction data
                    existing_prediction.LTSM_predicted_close_price = predicted_lstm_close_price
                    existing_prediction.RF_predicted_close_price = predicted_rf_close_price
                    existing_prediction.save()
                else:
                    # Create a new prediction entry
                    StockData.objects.create(
                        stock=stockData.objects.get(stock__symbol=stock_symbol),
                        date=most_recent_date,
                        LTSM_predicted_close_price=predicted_lstm_close_price,
                        RF_predicted_close_price=predicted_rf_close_price
                    )

                # Append the predictions to the list
                predictions.append({
                    'symbol': stock_symbol,
                    'predicted_lstm_close_price': predicted_lstm_close_price,
                    'predicted_rf_close_price': predicted_rf_close_price
                })

            # Return the predictions
            return {'predictions': predictions}

        except Exception as e:
            return {'error': str(e)}