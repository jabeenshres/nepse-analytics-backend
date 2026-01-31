import pandas as pd


class StockSequenceGenerator:
    def fetch_data(self, stock_data_model):
        stock_data_queryset = stock_data_model.objects.values(
            "stock__symbol", "date", "open_price", "high_price",
            "low_price", "close_price", "total_traded_quantity"
        )
        stock_dataframe = pd.DataFrame(stock_data_queryset)

        for column in ["open_price", "high_price", "low_price", "close_price"]:
            stock_dataframe[column] = pd.to_numeric(
                stock_dataframe[column], errors="coerce"
            )

        stock_dataframe["date"] = pd.to_datetime(stock_dataframe["date"])
        stock_dataframe.sort_values(by=["stock__symbol", "date"], inplace=True)
        return stock_dataframe
