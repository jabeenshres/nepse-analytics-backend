import os
import pickle
from django.apps import AppConfig


class StockDataConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'StockData'

    def ready(self):
        # Only load models if they exist (for migration purposes, this can be skipped)
        base_dir = os.path.dirname(os.path.dirname(__file__))
        lstm_model_path = os.path.join(base_dir, "models", "lstm_stock_model.pkl")
        rf_model_path = os.path.join(base_dir, "models", "rf_stock_model.pkl")

        try:
            if os.path.exists(lstm_model_path):
                with open(lstm_model_path, "rb") as lstm_file:
                    self.lstm_model = pickle.load(lstm_file)
            if os.path.exists(rf_model_path):
                with open(rf_model_path, "rb") as rf_file:
                    self.rf_model = pickle.load(rf_file)
        except Exception as e:
            # Don't fail if models can't be loaded (they're now in predictions app)
            pass
