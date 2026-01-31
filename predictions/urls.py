from django.urls import path
from .views import (
    GetPredictionsView,
    AddLSTMPredictionView,
    AddRFPredictionView
)

urlpatterns = [
    path('generate/', GetPredictionsView.as_view(), name='generate-predictions'),
    path('lstm/', AddLSTMPredictionView.as_view(), name='add-lstm-prediction'),
    path('random-forest/', AddRFPredictionView.as_view(), name='add-rf-prediction'),
]
