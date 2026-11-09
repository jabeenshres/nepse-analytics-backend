"""
Config-driven access control for the frontend and API.

Edit ``ROLE_ACCESS`` to change who can reach which destination. The sidebar is built
from the same feature keys, and API endpoints are gated by ``VIEW_FEATURES`` below, so
the UI and the API cannot drift apart.

A feature key represents one sidebar destination. Actions inside that page (for example
"view floorsheet" vs "trigger a scrape") share the same key except where a view declares
its own ``required_features`` / ``write_features`` attribute.
"""

# Every destination the frontend knows about. Keep this in sync with
# Stock_FE/src/app/config/features.js (same keys).
FEATURES = {
    'dashboard': {'label': 'Dashboard', 'path': '/'},
    'sharelist': {'label': 'Stock Prices', 'path': '/Sharelist'},
    'top_stocks': {'label': 'Top Stocks', 'path': '/TopStocks'},
    'indices': {'label': 'NEPSE Indices', 'path': '/Indices'},
    'screener': {'label': 'Screener', 'path': '/Screener'},
    'broker_holdings': {'label': 'Broker Holdings', 'path': '/BrokerHoldings'},
    'download': {'label': 'Download Data', 'path': '/Download'},
    'users': {'label': 'Users', 'path': '/Users'},
    'about': {'label': 'About', 'path': '/About'},
}

# Role -> allowed feature keys. ``'*'`` means every feature.
ROLE_ACCESS = {
    'admin': ['*'],
    'manager': [
        'dashboard',
        'sharelist',
        'top_stocks',
        'indices',
        'screener',
        'broker_holdings',
        'download',
        'about',
    ],
    'user': [
        'dashboard',
        'sharelist',
        'top_stocks',
        'indices',
        'screener',
        'broker_holdings',
        'about',
    ],
}

# Routes that never require a login (handled in the frontend middleware).
PUBLIC_FEATURES = ('about',)

# API view class -> feature required to call it. Views not listed here are open to any
# authenticated user. This is the API half of the same config; the sidebar uses
# ROLE_ACCESS, so changing a role in one place updates both.
VIEW_FEATURES = {
    # Analysis / screener
    'StockScreenerView': 'screener',
    'BacktestStrategyView': 'screener',
    'BacktestResultViewSet': 'screener',

    # Top stocks and unusual-activity family
    'TopStocksToWatchView': 'top_stocks',
    'UnusualActivityDetectorView': 'top_stocks',
    'AccumulationAlertView': 'top_stocks',
    'BreakoutWatchlistView': 'top_stocks',
    'VolumeSpikeDetectorView': 'top_stocks',
    'StockRecommendationsView': 'top_stocks',

    # Floorsheet read endpoints
    'FloorsheetDataView': 'broker_holdings',
    'FloorsheetAnalysisView': 'broker_holdings',
    'BrokerActivityView': 'broker_holdings',
    'BrokerHoldingsView': 'broker_holdings',

    # Indices
    'NepseIndicesDataView': 'indices',
    'NepseIndicesAnalysisView': 'indices',
    'NepseIndicesCompareView': 'indices',
    'NepseIndicesListView': 'indices',

    # Ingest / expensive operations
    'LoadStockDataView': 'download',
    'FloorsheetUploadView': 'download',
    'FloorsheetScrapeView': 'download',
    'NepalstockFloorsheetScrapeView': 'download',
    'NepseIndicesScrapeView': 'download',
    'GetPredictionsView': 'download',
    'AddLSTMPredictionView': 'download',
    'AddRFPredictionView': 'download',

    # Account administration
    'UserListView': 'users',
}

# For ModelViewSets: require this feature on non-GET requests, while leaving reads open
# to any authenticated user.
VIEW_WRITE_FEATURES = {
    'StockDataViewSet': 'download',
    'StockViewSet': 'download',
}


def features_for_role(role):
    """Return the set of feature keys granted to ``role``."""
    allowed = ROLE_ACCESS.get(role, [])
    if '*' in allowed:
        return set(FEATURES)
    return {key for key in allowed if key in FEATURES}


def allowed_features(user):
    """Return the feature keys for a user, honouring the superuser bypass."""
    if user is None or not getattr(user, 'is_authenticated', False):
        return set()
    if getattr(user, 'is_superuser', False):
        return set(FEATURES)
    return features_for_role(getattr(user, 'role', None))


def has_feature(user, feature):
    """True when ``user`` may use ``feature``."""
    return feature in allowed_features(user)
