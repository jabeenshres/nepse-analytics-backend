class StockSequenceGenerator:
    def __init__(self, sequence_length=30):
        self.sequence_length = sequence_length

    def fetch_data(self,StockData):
        import pandas as pd
        print("count",StockData.objects.count())
        stock_data = StockData.objects.select_related('stock').all()
        print("stock data", stock_data)
        data = pd.DataFrame(list(stock_data.values(
            'stock__symbol', 'date', 'open_price', 'high_price', 'low_price',
            'close_price', 'total_traded_quantity', 'total_traded_value',
            'previous_day_close_price', 'last_updated_price',
            'total_trades', 'average_traded_price', 'market_capitalization'
        )))
        data.rename(columns={'stock__symbol': 'symbol'}, inplace=True)
        data['date'] = pd.to_datetime(data['date'])
        data.sort_values(['symbol', 'date'], inplace=True)
        print("data",data)
        return data

    def create_sequences(self, group):
        sequences = []
        targets = []
        print("group",group)
        data = group[['open_price', 'high_price', 'low_price', 'close_price', 'total_traded_quantity']].values
        target = group['close_price'].values
        print ("values and target",data, target)
        print(f"Number of rows in group: {len(group)}")


        for i in range(len(data) - self.sequence_length):
            sequences.append(data[i:i + self.sequence_length])
            targets.append(target[i + self.sequence_length])
        
        print("sequence",sequences)    

        return sequences, targets

    def process(self,StockData):
        print("count",StockData.objects.count())
        import numpy as np
        data = self.fetch_data(StockData)
        X, y = [], []
        for symbol, group in data.groupby('symbol'):
            group_sequences, group_targets = self.create_sequences(group)
            X.extend(group_sequences)
            y.extend(group_targets)
        return np.array(X), np.array(y)



