from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    StockDataViewSet,
    StockViewSet,
    LoadStockDataView,
    StructuredDataView,
    LatestStockDataViewSet
)
from .analysis_views import (
    TechnicalIndicatorsView,
    TradingSignalsView,
    StockScreenerView,
    BacktestStrategyView,
    PortfolioViewSet,
    PortfolioHoldingViewSet,
    TradeViewSet,
    PortfolioPerformanceView,
    BacktestResultViewSet,
)
from .unusual_activity_views import (
    UnusualActivityDetectorView,
    AccumulationAlertView,
    BreakoutWatchlistView,
    TopStocksToWatchView,
    VolumeSpikeDetectorView,
    StockRecommendationsView,
)
from .floorsheet_views import (
    FloorsheetUploadView,
    FloorsheetScrapeView,
    NepalstockFloorsheetScrapeView,
    FloorsheetDataView,
    FloorsheetAnalysisView,
    BrokerActivityView,
)
from .nepse_indices_views import (
    NepseIndicesScrapeView,
    NepseIndicesDataView,
    NepseIndicesAnalysisView,
    NepseIndicesCompareView,
    NepseIndicesListView,
)

router_stock_data = DefaultRouter()
router_stock_data.register(r"entries", StockDataViewSet, basename="stock-data-entry")

router_stock = DefaultRouter()
router_stock.register(r"", StockViewSet, basename="stock")

# Portfolio and analysis routers
router_portfolio = DefaultRouter()
router_portfolio.register(r"", PortfolioViewSet, basename="portfolio")

router_holdings = DefaultRouter()
router_holdings.register(r"", PortfolioHoldingViewSet, basename="holding")

router_trades = DefaultRouter()
router_trades.register(r"", TradeViewSet, basename="trade")

router_backtest_results = DefaultRouter()
router_backtest_results.register(r"", BacktestResultViewSet, basename="backtest-result")

urlpatterns = [
    # Specific paths must come before router includes to avoid conflicts
    path('fetch/', LoadStockDataView.as_view(), name='fetch-stock-data'),
    path('structured/', StructuredDataView.as_view(), name='structured-data'),
    path('latest/', LatestStockDataViewSet.as_view({'get': 'list'}), name='latest-stock-data'),
    
    # Technical Analysis endpoints
    path('analysis/indicators/', TechnicalIndicatorsView.as_view(), name='technical-indicators'),
    path('analysis/signals/', TradingSignalsView.as_view(), name='trading-signals'),
    path('analysis/screener/', StockScreenerView.as_view(), name='stock-screener'),
    path('analysis/backtest/', BacktestStrategyView.as_view(), name='backtest-strategy'),
    path('analysis/backtest-results/', include(router_backtest_results.urls)),
    
    # Unusual Activity Detection endpoints
    path('analysis/unusual-activity/', UnusualActivityDetectorView.as_view(), name='unusual-activity'),
    path('analysis/accumulation-alerts/', AccumulationAlertView.as_view(), name='accumulation-alerts'),
    path('analysis/breakout-watchlist/', BreakoutWatchlistView.as_view(), name='breakout-watchlist'),
    path('analysis/top-stocks/', TopStocksToWatchView.as_view(), name='top-stocks-to-watch'),
    path('analysis/volume-spikes/', VolumeSpikeDetectorView.as_view(), name='volume-spikes'),
    path('analysis/recommendations/', StockRecommendationsView.as_view(), name='stock-recommendations'),
    
    # Portfolio management endpoints
    path('portfolios/', include(router_portfolio.urls)),
    path('holdings/', include(router_holdings.urls)),
    path('trades/', include(router_trades.urls)),
    path('portfolio-performance/', PortfolioPerformanceView.as_view(), name='portfolio-performance'),
    
    # Floorsheet data endpoints
    path('floorsheet/upload/', FloorsheetUploadView.as_view(), name='floorsheet-upload'),
    path('floorsheet/scrape/', FloorsheetScrapeView.as_view(), name='floorsheet-scrape'),
    path('floorsheet/nepalstock-scrape/', NepalstockFloorsheetScrapeView.as_view(), name='nepalstock-floorsheet-scrape'),
    path('floorsheet/data/', FloorsheetDataView.as_view(), name='floorsheet-data'),
    path('floorsheet/analysis/', FloorsheetAnalysisView.as_view(), name='floorsheet-analysis'),
    path('floorsheet/broker/', BrokerActivityView.as_view(), name='broker-activity'),
    
    # NEPSE Indices endpoints
    path('indices/scrape/', NepseIndicesScrapeView.as_view(), name='nepse-indices-scrape'),
    path('indices/data/', NepseIndicesDataView.as_view(), name='nepse-indices-data'),
    path('indices/analysis/', NepseIndicesAnalysisView.as_view(), name='nepse-indices-analysis'),
    path('indices/compare/', NepseIndicesCompareView.as_view(), name='nepse-indices-compare'),
    path('indices/list/', NepseIndicesListView.as_view(), name='nepse-indices-list'),
    
    # Router includes
    path('entries/', include(router_stock_data.urls)),
    path('', include(router_stock.urls)),
]
