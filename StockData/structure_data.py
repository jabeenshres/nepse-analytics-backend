class StockSequenceGenerator:
    def fetch_data(self,StockData):
        import pandas as pd

        # Query data
        data = StockData.objects.values("stock__symbol", "date", "open_price", "high_price","low_price", "close_price", "total_traded_quantity")
        df = pd.DataFrame(data)

        # Convert 'date' to datetime and sort
        df["date"] = pd.to_datetime(df["date"])
        df.sort_values(by=["stock__symbol", "date"], inplace=True)
        return df
