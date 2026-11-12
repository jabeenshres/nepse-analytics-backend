"""
Constants for predictions app.
"""
# Date format
DATE_FORMAT = '%Y-%m-%d'

# Prediction types
PREDICTION_TYPE_LSTM = 'LSTM'
PREDICTION_TYPE_RF = 'RF'

# Required prediction keys
REQUIRED_PREDICTION_KEYS = [
    "stock_symbol",
    "date",
    "predicted_close_price",
    "mae",
    "r_square",
    "overall_mae",
    "overall_r_square"
]
