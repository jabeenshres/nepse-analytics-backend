from django.urls import path
from .views import (
    AddLSTMPredictionView,
    AddRFPredictionView
)

urlpatterns = [
    path('lstm/', AddLSTMPredictionView.as_view(), name='add-lstm-prediction'),
    path('random-forest/', AddRFPredictionView.as_view(), name='add-rf-prediction'),
]
