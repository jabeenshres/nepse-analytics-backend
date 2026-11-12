"""
Constants for stock_data app.
"""
from datetime import timedelta

# Date formats
DATE_FORMAT = '%Y-%m-%d'
NEPAL_STOCK_DATE_FORMAT = '%m/%d/%Y'

# Pagination
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 200

# Query parameters
SEARCH_PARAM = 'search'
GAINER_PARAM = 'gainer'
DATE_PARAM = 'date'

# Gainer filter values
GAINER_TRUE_VALUES = ['true', 'True', '1']
GAINER_FALSE_VALUES = ['false', 'False', '0']

# Nepal Stock Exchange URL
NEPAL_STOCK_BASE_URL = "https://www.nepalstock.com/today-price"
