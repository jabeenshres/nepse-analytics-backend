from django.apps import apps
import numpy as np
from sklearn.preprocessing import MinMaxScaler

class StockPrediction:
    def getPrediction(self, stockData):
        # Get the models from the StockDataConfig (ensure they are loaded only once)
        stock_data_config = apps.get_app_config('StockData')  # Get the StockDataConfig instance
        lstm_model = stock_data_config.lstm_model  # LSTM model
        scaler = MinMaxScaler()  # Use a single scaler for all stocks
        
        predictions = []
        
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

                # Normalize the data for all stocks (fit on the first stock and apply to all)
                normalized_data = scaler.fit_transform(data)

                # Reshape the data for prediction
                X = normalized_data.reshape((1, 6, 5))  # 6 days, 5 features (open, high, low, close, quantity)

                # Make the prediction using the LSTM model
                predicted_price = lstm_model.predict(X)

                # Inverse transform to original scale
                data_padded = np.zeros_like(data)  # Create a padded array for the predicted data
                data_padded[:, 3] = predicted_price.flatten()  # Set only the predicted 'close_price'

                # Reverse scaling for predicted close price
                original_scaled_data = scaler.inverse_transform(data_padded)
                predicted_close_price_original = original_scaled_data[0, 3]  # Get the predicted close price in original scale

                predictions.append({
                    'symbol': stock_symbol,  # Use stock symbol directly
                    'predicted_close_price': predicted_close_price_original
                })

            # Get the total number of unique stocks (distinct stock symbols)
            total_unique_stocks_count = distinct_stocks.count()

            # Return the predictions along with the total number of unique stocks
            return {'total_unique_stocks_count': total_unique_stocks_count, 'predictions': predictions}

        except Exception as e:
            return {'error': str(e)}
