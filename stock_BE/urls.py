"""
URL configuration for stock_BE project.
"""
from django.contrib import admin
from django.urls import path, include
from rest_framework_simplejwt.views import TokenRefreshView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/stock-data/', include('stock_data.urls')),
    path('api/predictions/', include('predictions.urls')),
    path('api/accounts/', include('accounts.urls')),
    path('api/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
]
