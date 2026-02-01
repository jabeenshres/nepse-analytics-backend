"""
Custom pagination classes for stock_data app.
"""
from rest_framework.pagination import PageNumberPagination


class StockDataPagination(PageNumberPagination):
    """
    Pagination class for StockData endpoints.
    """
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 500


class StockPagination(PageNumberPagination):
    """
    Pagination class for Stock endpoints.
    """
    page_size = 100
    page_size_query_param = 'page_size'
    max_page_size = 1000
