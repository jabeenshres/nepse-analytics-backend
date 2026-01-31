"""
Utilities for structuring stock data for machine learning models.
"""
import pandas as pd
import logging

logger = logging.getLogger(__name__)


class StockSequenceGenerator:
    """
    Generator for creating structured stock data sequences for ML models.
    """
    
    def fetch_data(self, stock_data_model):
        """
        Fetch and structure stock data for model training.
        
        Args:
            stock_data_model: StockData model class
        
        Returns:
            pandas.DataFrame: Structured stock data with:
                - stock__symbol
                - date
                - open_price
                - high_price
                - low_price
                - close_price
                - total_traded_quantity
        
        Raises:
            Exception: If data fetching fails
        """
        try:
            stock_data_queryset = stock_data_model.objects.values(
                "stock__symbol",
                "date",
                "open_price",
                "high_price",
                "low_price",
                "close_price",
                "total_traded_quantity"
            )
            stock_dataframe = pd.DataFrame(stock_data_queryset)

            # Convert price columns to numeric, handling invalid values
            price_columns = ["open_price", "high_price", "low_price", "close_price"]
            for column in price_columns:
                stock_dataframe[column] = pd.to_numeric(
                    stock_dataframe[column],
                    errors="coerce"
                )

            # Convert date to datetime and sort
            stock_dataframe["date"] = pd.to_datetime(stock_dataframe["date"])
            stock_dataframe.sort_values(
                by=["stock__symbol", "date"],
                inplace=True
            )

            logger.info(
                f"Generated structured data for {len(stock_dataframe)} records"
            )
            return stock_dataframe
        except Exception as e:
            logger.error(f"Error fetching structured data: {e}")
            raise
