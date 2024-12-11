"""
URL configuration for stock_BE project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/4.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from StockData.views import StockDataViewSet, LoadStockData, StockViewSet, LatestStockDataViewSet, StructStockData
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

router_stock_data = DefaultRouter()
router_stock_data.register(r"",StockDataViewSet)

router_stock = DefaultRouter()
router_stock.register(r"",StockViewSet)

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/admin/', include([
        path('stock_data/', include(router_stock_data.urls)), 
        path('stock/', include(router_stock.urls)), 
        path('load_stock_data/', LoadStockData.as_view(), name='load_stock_data'),  
        path('structdata/', StructStockData.as_view(), name='struct_stock_data'),  
        path('recent/', LatestStockDataViewSet.as_view({'get': 'list'}), name='recent_stock_data'),  
    ])),
    path('api/token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('api/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),

]
