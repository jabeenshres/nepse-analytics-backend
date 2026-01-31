from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    StockDataViewSet,
    StockViewSet,
    LoadStockDataView,
    StructuredDataView,
    LatestStockDataViewSet
)

router_stock_data = DefaultRouter()
router_stock_data.register(r"entries", StockDataViewSet, basename="stock-data-entry")

router_stock = DefaultRouter()
router_stock.register(r"", StockViewSet, basename="stock")

urlpatterns = [
    path('entries/', include(router_stock_data.urls)),
    path('', include(router_stock.urls)),
    path('fetch/', LoadStockDataView.as_view(), name='fetch-stock-data'),
    path('structured/', StructuredDataView.as_view(), name='structured-data'),
    path('latest/', LatestStockDataViewSet.as_view({'get': 'list'}), name='latest-stock-data'),
]
