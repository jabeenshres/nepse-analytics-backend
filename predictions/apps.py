import os
import pickle
from django.apps import AppConfig


class PredictionsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'predictions'

    def ready(self):
        base_dir = os.path.dirname(os.path.dirname(__file__))
        lstm_model_path = os.path.join(base_dir, "models", "lstm_stock_model.pkl")
        rf_model_path = os.path.join(base_dir, "models", "rf_stock_model.pkl")

        try:
            with open(lstm_model_path, "rb") as lstm_file:
                self.lstm_model = pickle.load(lstm_file)
            with open(rf_model_path, "rb") as rf_file:
                self.rf_model = pickle.load(rf_file)
        except FileNotFoundError as e:
            raise RuntimeError(f"Model file not found: {e}")
