# Stock Market API Documentation

## Overview

This API provides endpoints for managing stock market data from Nepal Stock Exchange and generating machine learning predictions for stock prices. The API is divided into two main modules:

1. **Stock Data API** - Handles data fetching, storage, and retrieval of stock market information
2. **Predictions API** - Generates and manages ML-based stock price predictions using LSTM and Random Forest models

---

## Base URL

```
http://localhost:8000/api
```

---

## Authentication

Most endpoints are publicly accessible (`AllowAny`), but some operations require authentication:

- **Admin/Manager Required**: Data fetching and prediction generation
- **Public Access**: Data retrieval, listing, and filtering

For protected endpoints, include JWT token in the Authorization header:
```
Authorization: Bearer <your_jwt_token>
```

---

## Stock Data API

Base URL: `/api/stock-data/`

### Overview

The Stock Data API manages all stock market information including:
- Stock listings (symbols, security names, 52-week highs/lows)
- Daily trading data (open, high, low, close prices, volumes, etc.)
- Data fetching from Nepal Stock Exchange
- Structured data export for ML model training

---

### 1. List All Stocks

**GET** `/api/stock-data/`

Retrieve a list of all stocks with their basic information.

**Permissions**: Public

**Response**: Paginated list of stocks with nested stock data

**Example Request**:
```bash
curl -X GET http://localhost:8000/api/stock-data/
```

**Example Response**:
```json
{
  "count": 250,
  "next": "http://localhost:8000/api/stock-data/?page=2",
  "previous": null,
  "results": [
    {
      "id": 1,
      "symbol": "NBL",
      "security_id": 1,
      "security_name": "Nepal Bank Limited",
      "fifty_two_weeks_high": "500.00",
      "fifty_two_weeks_low": "300.00",
      "data": [
        {
          "id": 1,
          "date": "2024-01-15",
          "open_price": "450.00",
          "high_price": "470.00",
          "low_price": "445.00",
          "close_price": "465.00",
          ...
        }
      ]
    }
  ]
}
```

---

### 2. Get Stock Details

**GET** `/api/stock-data/{id}/`

Retrieve detailed information about a specific stock.

**Permissions**: Public

**Path Parameters**:
- `id` (integer): Stock ID

**Example Request**:
```bash
curl -X GET http://localhost:8000/api/stock-data/1/
```

---

### 3. Create Stock

**POST** `/api/stock-data/`

Create a new stock entry.

**Permissions**: Public

**Request Body**:
```json
{
  "symbol": "NBL",
  "security_id": 1,
  "security_name": "Nepal Bank Limited",
  "fifty_two_weeks_high": "500.00",
  "fifty_two_weeks_low": "300.00"
}
```

**Example Request**:
```bash
curl -X POST http://localhost:8000/api/stock-data/ \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "NBL",
    "security_id": 1,
    "security_name": "Nepal Bank Limited",
    "fifty_two_weeks_high": "500.00",
    "fifty_two_weeks_low": "300.00"
  }'
```

---

### 4. Update Stock

**PUT/PATCH** `/api/stock-data/{id}/`

Update an existing stock entry.

**Permissions**: Public

---

### 5. Delete Stock

**DELETE** `/api/stock-data/{id}/`

Delete a stock entry.

**Permissions**: Public

---

### 6. List Stock Data Entries

**GET** `/api/stock-data/entries/`

Retrieve all stock data entries (daily trading data).

**Permissions**: Public

**Query Parameters**:
- `page` (integer): Page number for pagination
- `page_size` (integer): Number of items per page (default: 20)

**Example Request**:
```bash
curl -X GET "http://localhost:8000/api/stock-data/entries/?page=1&page_size=50"
```

**Example Response**:
```json
{
  "count": 5000,
  "next": "http://localhost:8000/api/stock-data/entries/?page=2",
  "previous": null,
  "results": [
    {
      "id": 1,
      "stock": 1,
      "date": "2024-01-15",
      "open_price": "450.00",
      "high_price": "470.00",
      "low_price": "445.00",
      "close_price": "465.00",
      "total_traded_quantity": 10000,
      "total_traded_value": "4650000.00",
      "previous_day_close_price": "440.00",
      "last_updated_price": "465.00",
      "total_trades": 150,
      "average_traded_price": "465.00",
      "market_capitalization": "465000000.00",
      "LSTM_predicted_close_price": "460.00",
      "RF_predicted_close_price": "462.00"
    }
  ]
}
```

---

### 7. Get Stock Data Entry

**GET** `/api/stock-data/entries/{id}/`

Retrieve a specific stock data entry.

**Permissions**: Public

---

### 8. Create Stock Data Entry

**POST** `/api/stock-data/entries/`

Create a new stock data entry for a specific date.

**Permissions**: Public

**Request Body**:
```json
{
  "stock": 1,
  "date": "2024-01-16",
  "open_price": "465.00",
  "high_price": "480.00",
  "low_price": "460.00",
  "close_price": "475.00",
  "total_traded_quantity": 12000,
  "total_traded_value": "5700000.00",
  "previous_day_close_price": "465.00",
  "last_updated_price": "475.00",
  "total_trades": 180,
  "average_traded_price": "475.00",
  "market_capitalization": "475000000.00"
}
```

**Validation**: 
- `stock` and `date` combination must be unique
- High price must be >= low price
- All prices must be non-negative

---

### 9. Fetch Stock Data from Nepal Stock Exchange

**POST** `/api/stock-data/fetch/`

Fetch and load stock data directly from Nepal Stock Exchange website using web scraping for a specified date range.

**Permissions**: Admin or Manager only (currently set to AllowAny for testing)

**What it does**:
- Opens Nepal Stock Exchange website
- Loops through dates in the specified range (from date_from to date_to)
- **Smart skipping**: Checks database first - skips dates that already have data (no CSV download)
- Downloads CSV files only for dates without data
- Parses and saves data to database
- Returns detailed statistics about the operation
- Handles missing data gracefully

**Request Body**:
```json
{
  "date_from": "2024-01-01",
  "date_to": "2024-01-31"
}
```

**Parameters** (both required):
- `date_from` (string, required): Start date in YYYY-MM-DD format
- `date_to` (string, required): End date in YYYY-MM-DD format OR `"latest"` to use the latest date in database

**Example Request - Specific Date Range**:
```bash
curl -X POST http://localhost:8000/api/stock-data/fetch/ \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "date_from": "2024-01-01",
    "date_to": "2024-01-31"
  }'
```

**Example Request - Using Latest Date**:
```bash
curl -X POST http://localhost:8000/api/stock-data/fetch/ \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "date_from": "2024-01-01",
    "date_to": "latest"
  }'
```

**Example Response - Success**:
```json
{
  "message": "Data loading completed",
  "date_from": "2024-01-01",
  "date_to": "2024-01-31",
  "statistics": {
    "total_dates": 31,
    "dates_processed": 15,
    "dates_skipped": 16,
    "dates_failed": 0,
    "stocks_created": 5,
    "stocks_updated": 250
  }
}
```

**Example Response - Error (Missing Parameter)**:
```json
{
  "error": "date_from is required (format: YYYY-MM-DD)"
}
```

**Example Response - Error (Invalid Date Format)**:
```json
{
  "error": "Invalid date_from format: 2024/01/01. Use YYYY-MM-DD."
}
```

**Example Response - Error (Invalid Date Range)**:
```json
{
  "error": "date_from cannot be greater than date_to"
}
```

**Response Fields**:
- `message`: Status message
- `date_from`: Actual start date used
- `date_to`: Actual end date used
- `statistics`: Detailed operation statistics
  - `total_dates`: Total number of dates in the range
  - `dates_processed`: Number of dates successfully processed (CSV downloaded and saved)
  - `dates_skipped`: Number of dates skipped (data already exists in database)
  - `dates_failed`: Number of dates that failed to process
  - `stocks_created`: Number of new stock records created
  - `stocks_updated`: Number of existing stock data records updated

**Smart Skipping Feature**:
- Before downloading CSV for any date, the system checks if data already exists in the database
- If data exists, the date is skipped entirely (no CSV download, no processing)
- This significantly speeds up the process when re-fetching data
- Skipped dates are logged and included in the statistics

**Performance Notes**:
- This operation may take several minutes depending on the number of dates requested
- The scraper uses Selenium WebDriver to interact with the website
- Dates with existing data are skipped immediately (very fast)
- Only dates without data trigger CSV downloads (slower operation)
- Processing is done sequentially (one date at a time)

**Best Practices**:
- Use specific date ranges for better control
- Use `"latest"` for `date_to` when you want to fetch up to the most recent data
- Check statistics to see how many dates were skipped vs processed
- Run during off-peak hours for large date ranges

---

### 10. Get Structured Data for ML Training

**GET** `/api/stock-data/structured/`

Retrieve stock data in a structured format suitable for machine learning model training.

**Permissions**: Public

**What it does**:
- Fetches all stock data from database
- Structures it in a time-series format
- Converts prices to numeric format
- Sorts by symbol and date
- Returns as JSON array

**Example Request**:
```bash
curl -X GET http://localhost:8000/api/stock-data/structured/
```

**Example Response**:
```json
{
  "data": [
    {
      "stock__symbol": "NBL",
      "date": "2024-01-15T00:00:00",
      "open_price": 450.0,
      "high_price": 470.0,
      "low_price": 445.0,
      "close_price": 465.0,
      "total_traded_quantity": 10000
    },
    {
      "stock__symbol": "NBL",
      "date": "2024-01-16T00:00:00",
      "open_price": 465.0,
      "high_price": 480.0,
      "low_price": 460.0,
      "close_price": 475.0,
      "total_traded_quantity": 12000
    }
  ]
}
```

**Use Case**: This endpoint is designed to export data for training machine learning models outside of Django.

---

### 11. Get Latest Stock Data with Filters

**GET** `/api/stock-data/latest/`

Retrieve the latest stock data with advanced filtering options.

**Permissions**: Public

**Query Parameters**:
- `search` (string, optional): Search by stock symbol or security name (case-insensitive)
- `gainer` (string, optional): Filter by gainers/losers
  - `true`, `True`, or `1`: Show only gainers (close_price > open_price)
  - `false`, `False`, or `0`: Show only losers (close_price <= open_price)
- `date` (string, optional): Specific date in YYYY-MM-DD format (default: latest available date)
- `page` (integer, optional): Page number for pagination
- `page_size` (integer, optional): Items per page (default: 20)

**Example Request - Get Latest Data**:
```bash
curl -X GET "http://localhost:8000/api/stock-data/latest/"
```

**Example Request - Search by Symbol**:
```bash
curl -X GET "http://localhost:8000/api/stock-data/latest/?search=NBL"
```

**Example Request - Get Gainers Only**:
```bash
curl -X GET "http://localhost:8000/api/stock-data/latest/?gainer=true"
```

**Example Request - Specific Date**:
```bash
curl -X GET "http://localhost:8000/api/stock-data/latest/?date=2024-01-15"
```

**Example Request - Combined Filters**:
```bash
curl -X GET "http://localhost:8000/api/stock-data/latest/?search=Bank&gainer=true&date=2024-01-15"
```

**Example Response**:
```json
{
  "count": 150,
  "next": "http://localhost:8000/api/stock-data/latest/?page=2",
  "previous": null,
  "results": [
    {
      "id": 1,
      "symbol": "NBL",
      "security_id": 1,
      "security_name": "Nepal Bank Limited",
      "fifty_two_weeks_high": "500.00",
      "fifty_two_weeks_low": "300.00",
      "data": [
        {
          "date": "2024-01-15",
          "open_price": "450.00",
          "high_price": "470.00",
          "low_price": "445.00",
          "close_price": "465.00",
          "total_traded_quantity": 10000,
          "total_traded_value": "4650000.00",
          "previous_day_close_price": "440.00",
          "last_updated_price": "465.00",
          "total_trades": 150,
          "average_traded_price": "465.00",
          "market_capitalization": "465000000.00"
        }
      ]
    }
  ]
}
```

**Response Structure**:
- Data is grouped by stock
- Each stock contains an array of data entries for that date
- Supports pagination
- Optimized with database joins for performance

---

## Predictions API

Base URL: `/api/predictions/`

### Overview

The Predictions API handles machine learning-based stock price predictions using two models:
- **LSTM (Long Short-Term Memory)**: Deep learning model for time-series prediction
- **Random Forest**: Ensemble learning model for regression

The API allows you to:
- Generate predictions for all stocks
- Add/update predictions from external ML training pipelines
- Store model performance metrics (MAE, R-squared)

---

### 1. Generate Predictions

**GET** `/api/predictions/generate/`

Generate stock price predictions for all stocks using both LSTM and Random Forest models.

**Permissions**: Admin or Manager only

**What it does**:
- Loads pre-trained LSTM and Random Forest models
- For each stock, takes the last 6 days of data
- Normalizes the data
- Generates predictions for the next day
- Updates the database with predicted prices
- Returns predictions for all stocks

**Query Parameters**:
- `date` (string, optional): Target date for prediction in YYYY-MM-DD format. If not provided, uses the latest date in database.

**Example Request**:
```bash
curl -X GET "http://localhost:8000/api/predictions/generate/?date=2024-01-16" \
  -H "Authorization: Bearer <token>"
```

**Example Response**:
```json
{
  "predictions": [
    {
      "symbol": "NBL",
      "predicted_lstm_close_price": 460.25,
      "predicted_rf_close_price": 462.50,
      "date": "2024-01-16"
    },
    {
      "symbol": "ADBL",
      "predicted_lstm_close_price": 380.75,
      "predicted_rf_close_price": 382.00,
      "date": "2024-01-16"
    },
    {
      "symbol": "SCB",
      "error": "Not enough data for prediction"
    }
  ]
}
```

**Requirements**:
- Each stock must have at least 6 days of historical data
- If prediction date is provided, there must be at least 6 days of data before that date

**Note**: Predictions are automatically saved to the database. The `LSTM_predicted_close_price` and `RF_predicted_close_price` fields in StockData are updated.

---

### 2. Add LSTM Predictions

**POST** `/api/predictions/lstm/`

Add or update LSTM model predictions and metrics from an external ML training pipeline.

**Permissions**: Public

**What it does**:
- Accepts a list of predictions with model metrics
- Updates stock data with predicted prices
- Updates stock-level model performance metrics (MAE, R-squared)
- Handles missing data gracefully (skips and reports)

**Request Body**:
```json
[
  {
    "stock_symbol": "NBL",
    "date": "2024-01-16",
    "predicted_close_price": 460.25,
    "mae": 5.25,
    "r_square": 0.92,
    "overall_mae": 6.50,
    "overall_r_square": 0.90
  },
  {
    "stock_symbol": "ADBL",
    "date": "2024-01-16",
    "predicted_close_price": 380.75,
    "mae": 4.80,
    "r_square": 0.94,
    "overall_mae": 5.20,
    "overall_r_square": 0.92
  }
]
```

**Required Fields**:
- `stock_symbol` (string): Stock symbol (must exist in database)
- `date` (string): Date in YYYY-MM-DD format
- `predicted_close_price` (decimal): Predicted closing price
- `mae` (decimal): Mean Absolute Error for this stock
- `r_square` (decimal): R-squared value for this stock
- `overall_mae` (decimal): Overall MAE across all stocks
- `overall_r_square` (decimal): Overall R-squared across all stocks

**Example Request**:
```bash
curl -X POST http://localhost:8000/api/predictions/lstm/ \
  -H "Content-Type: application/json" \
  -d '[
    {
      "stock_symbol": "NBL",
      "date": "2024-01-16",
      "predicted_close_price": 460.25,
      "mae": 5.25,
      "r_square": 0.92,
      "overall_mae": 6.50,
      "overall_r_square": 0.90
    }
  ]'
```

**Example Response - Success**:
```json
{
  "message": "Predictions updated successfully"
}
```

**Example Response - With Skipped Predictions**:
```json
{
  "message": "Predictions updated successfully",
  "skipped_predictions": [
    {
      "stock_symbol": "XYZ",
      "date": "2024-01-16",
      "reason": "StockData does not exist for this date"
    }
  ]
}
```

**Error Responses**:
- `400 Bad Request`: Missing required fields, invalid date format, or stock doesn't exist
- `400 Bad Request`: Invalid data format (not a list)

---

### 3. Add Random Forest Predictions

**POST** `/api/predictions/random-forest/`

Add or update Random Forest model predictions and metrics from an external ML training pipeline.

**Permissions**: Public

**Request/Response Format**: Same as LSTM predictions endpoint

**Example Request**:
```bash
curl -X POST http://localhost:8000/api/predictions/random-forest/ \
  -H "Content-Type: application/json" \
  -d '[
    {
      "stock_symbol": "NBL",
      "date": "2024-01-16",
      "predicted_close_price": 462.50,
      "mae": 5.50,
      "r_square": 0.91,
      "overall_mae": 6.75,
      "overall_r_square": 0.89
    }
  ]'
```

**What Gets Updated**:
- `RF_predicted_close_price` in StockData
- `RF_Mean_Absolute_Error` in Stock
- `RF_R_Square` in Stock
- `Overall_RF_Mean_Absolute_Error` in Stock
- `Overall_RF_R_Square` in Stock

---

## Error Handling

### Standard Error Response Format

```json
{
  "error": "Error message describing what went wrong"
}
```

### Common HTTP Status Codes

- `200 OK`: Request successful
- `201 Created`: Resource created successfully
- `400 Bad Request`: Invalid request data or parameters
- `401 Unauthorized`: Authentication required
- `403 Forbidden`: Insufficient permissions
- `404 Not Found`: Resource not found
- `500 Internal Server Error`: Server error

### Validation Errors

When validation fails, the response includes field-specific errors:

```json
{
  "field_name": ["Error message for this field"]
}
```

Example:
```json
{
  "high_price": ["High price cannot be less than low price."],
  "close_price": ["Prices cannot be negative."]
}
```

---

## Pagination

Most list endpoints support pagination with the following query parameters:
- `page` (integer): Page number (default: 1)
- `page_size` (integer): Items per page (default: 20, max: 200)

**Pagination Response Format**:
```json
{
  "count": 1000,
  "next": "http://localhost:8000/api/endpoint/?page=2",
  "previous": null,
  "results": [...]
}
```

---

## Data Models

### Stock Model

```json
{
  "id": 1,
  "symbol": "NBL",
  "security_id": 1,
  "security_name": "Nepal Bank Limited",
  "fifty_two_weeks_high": "500.00",
  "fifty_two_weeks_low": "300.00",
  "LSTM_Mean_Absolute_Error": "5.25",
  "Overall_LSTM_Mean_Absolute_Error": "6.50",
  "LSTM_R_Square": "0.92",
  "Overall_LSTM_R_Square": "0.90",
  "RF_Mean_Absolute_Error": "5.50",
  "Overall_RF_Mean_Absolute_Error": "6.75",
  "RF_R_Square": "0.91",
  "Overall_RF_R_Square": "0.89"
}
```

### StockData Model

```json
{
  "id": 1,
  "stock": 1,
  "date": "2024-01-15",
  "open_price": "450.00",
  "high_price": "470.00",
  "low_price": "445.00",
  "close_price": "465.00",
  "total_traded_quantity": 10000,
  "total_traded_value": "4650000.00",
  "previous_day_close_price": "440.00",
  "last_updated_price": "465.00",
  "total_trades": 150,
  "average_traded_price": "465.00",
  "market_capitalization": "465000000.00",
  "LSTM_predicted_close_price": "460.00",
  "RF_predicted_close_price": "462.00"
}
```

---

## Workflow Examples

### Complete Workflow: Fetch Data → Generate Predictions

1. **Fetch stock data from Nepal Stock Exchange**:
```bash
POST /api/stock-data/fetch/
{
  "date_from": "2024-01-01",
  "date_to": "latest"
}
```

2. **Generate predictions for all stocks**:
```bash
GET /api/predictions/generate/
```

3. **View latest stock data with predictions**:
```bash
GET /api/stock-data/latest/
```

### External ML Pipeline Workflow

1. **Export structured data for training**:
```bash
GET /api/stock-data/structured/
```

2. **Train models externally** (using the exported data)

3. **Upload LSTM predictions**:
```bash
POST /api/predictions/lstm/
[...predictions array...]
```

4. **Upload Random Forest predictions**:
```bash
POST /api/predictions/random-forest/
[...predictions array...]
```

---

## Technical Analysis API

Base URL: `/api/stock-data/analysis/`

### Overview

The Technical Analysis API provides endpoints for:
- Calculating technical indicators (SMA, EMA, RSI, MACD, Bollinger Bands, etc.)
- Generating trading signals based on technical analysis
- Screening stocks based on technical criteria
- Backtesting trading strategies
- Portfolio performance tracking

---

### 1. Get Technical Indicators

Calculate all technical indicators for a specific stock.

**GET** `/api/stock-data/analysis/indicators/`

**Query Parameters:**

| Parameter | Type   | Required | Description                           |
|-----------|--------|----------|---------------------------------------|
| symbol    | string | Yes      | Stock symbol (e.g., "NABIL")         |
| days      | int    | No       | Number of days (default: 100, max: 500) |

**Example Request:**
```bash
GET /api/stock-data/analysis/indicators/?symbol=NABIL&days=100
```

**Success Response (200 OK):**
```json
{
  "symbol": "NABIL",
  "security_name": "Nabil Bank Limited",
  "days": 100,
  "data": [
    {
      "date": "2024-01-15",
      "open_price": 450.00,
      "high_price": 470.00,
      "low_price": 445.00,
      "close_price": 465.00,
      "total_traded_quantity": 10000,
      "SMA_10": 458.50,
      "SMA_20": 455.00,
      "SMA_50": 448.00,
      "EMA_10": 459.20,
      "EMA_20": 456.30,
      "RSI": 58.45,
      "MACD": 2.35,
      "MACD_Signal": 1.80,
      "MACD_Histogram": 0.55,
      "BB_Upper": 485.00,
      "BB_Middle": 455.00,
      "BB_Lower": 425.00,
      "ATR": 12.50,
      "Stoch_K": 65.30,
      "Stoch_D": 62.10,
      "OBV": 1250000,
      "VWAP": 460.25,
      "Support": 440.00,
      "Resistance": 480.00,
      "Momentum": 15.00,
      "ROC": 3.33,
      "Williams_R": -34.70,
      "Volume_SMA": 8500,
      "Volume_Ratio": 1.18,
      "Price_Position": 0.80,
      "Daily_Return": 0.0215,
      "Log_Return": 0.0213,
      "Spread": 0.054
    }
  ]
}
```

**Indicators Included:**

| Indicator | Description |
|-----------|-------------|
| SMA_10, SMA_20, SMA_50 | Simple Moving Averages |
| EMA_10, EMA_20 | Exponential Moving Averages |
| RSI | Relative Strength Index (14-period) |
| MACD, MACD_Signal, MACD_Histogram | Moving Average Convergence Divergence |
| BB_Upper, BB_Middle, BB_Lower | Bollinger Bands (20-period, 2 std) |
| ATR | Average True Range (14-period) |
| Stoch_K, Stoch_D | Stochastic Oscillator |
| OBV | On-Balance Volume |
| VWAP | Volume Weighted Average Price |
| Support, Resistance | 20-period support/resistance levels |
| Momentum | 10-period price momentum |
| ROC | Rate of Change (percentage) |
| Williams_R | Williams %R indicator |
| Volume_SMA, Volume_Ratio | Volume indicators |
| Daily_Return, Log_Return | Return metrics |
| Spread | High-Low spread as percentage of close |

---

### 2. Get Trading Signals

Generate trading signals based on technical analysis.

**GET** `/api/stock-data/analysis/signals/`

**Query Parameters:**

| Parameter | Type   | Required | Description                    |
|-----------|--------|----------|--------------------------------|
| symbol    | string | Yes      | Stock symbol (e.g., "NABIL")  |

**Example Request:**
```bash
GET /api/stock-data/analysis/signals/?symbol=NABIL
```

**Success Response (200 OK):**
```json
{
  "symbol": "NABIL",
  "security_name": "Nabil Bank Limited",
  "last_price": 465.00,
  "last_date": "2024-01-15",
  "signals": [
    {
      "type": "MA_BULLISH",
      "indicator": "Moving Average",
      "message": "Price above 20 & 50 SMA - Strong uptrend",
      "strength": "BULLISH"
    },
    {
      "type": "MACD_BULLISH",
      "indicator": "MACD",
      "message": "MACD above signal line - Bullish momentum",
      "strength": "BULLISH"
    },
    {
      "type": "HIGH_VOLUME",
      "indicator": "Volume",
      "message": "Volume 1.5x above average - High interest",
      "strength": "NEUTRAL"
    }
  ],
  "strength": 30,
  "recommendation": "STRONG_BUY",
  "signal_count": 3,
  "key_levels": {
    "support": 440.00,
    "resistance": 480.00,
    "sma_20": 455.00,
    "sma_50": 448.00
  }
}
```

**Signal Types:**

| Signal Type | Description |
|-------------|-------------|
| MA_BULLISH/MA_BEARISH | Moving average trend signals |
| RSI_OVERSOLD/RSI_OVERBOUGHT | RSI extreme conditions |
| MACD_BULLISH/MACD_BEARISH | MACD crossover signals |
| BB_OVERSOLD/BB_OVERBOUGHT | Bollinger Band signals |
| STOCH_OVERSOLD/STOCH_OVERBOUGHT | Stochastic signals |
| HIGH_VOLUME | Significant volume increase |
| WILLIAMS_OVERSOLD/WILLIAMS_OVERBOUGHT | Williams %R signals |

**Recommendations:**

| Strength Range | Recommendation |
|----------------|----------------|
| >= 30 | STRONG_BUY |
| 10 to 29 | BUY |
| -9 to 9 | HOLD |
| -29 to -10 | SELL |
| <= -30 | STRONG_SELL |

---

### 3. Stock Screener

Screen stocks based on technical criteria.

**GET** `/api/stock-data/analysis/screener/`

**Query Parameters:**

| Parameter  | Type   | Required | Description                                    |
|------------|--------|----------|------------------------------------------------|
| type       | string | No       | Screener type (default: "momentum")           |
| min_price  | float  | No       | Minimum close price filter                     |
| max_price  | float  | No       | Maximum close price filter                     |
| limit      | int    | No       | Number of results (default: 20, max: 100)     |

**Screener Types:**

| Type | Description |
|------|-------------|
| momentum | Stocks with price above moving averages and rising volume |
| oversold | Stocks with RSI < 30 and/or Stochastic < 20 |
| overbought | Stocks with RSI > 70 and/or Stochastic > 80 |
| volume_breakout | Stocks with volume > 2x average |
| trend_following | Stocks in clear uptrend (price > SMA20 > SMA50) |

**Example Request:**
```bash
GET /api/stock-data/analysis/screener/?type=oversold&limit=10
```

**Success Response (200 OK):**
```json
{
  "screener_type": "oversold",
  "count": 5,
  "total_matched": 5,
  "date": "2024-01-15",
  "results": [
    {
      "symbol": "ABC",
      "security_name": "ABC Company Limited",
      "close_price": 150.00,
      "change_percent": -2.5,
      "volume": 5000,
      "volume_ratio": 1.2,
      "rsi": 25.5,
      "sma_20": 165.00,
      "sma_50": 170.00,
      "score": 74.5
    }
  ]
}
```

---

### 4. Backtest Strategy

Backtest trading strategies on historical data.

**POST** `/api/stock-data/analysis/backtest/`

**Request Body:**

| Field      | Type   | Required | Description                                    |
|------------|--------|----------|------------------------------------------------|
| strategy   | string | No       | Strategy name (default: "sma_crossover")      |
| symbol     | string | Yes      | Stock symbol                                   |
| start_date | string | No       | Start date (YYYY-MM-DD)                       |
| end_date   | string | No       | End date (YYYY-MM-DD)                         |
| capital    | float  | No       | Initial capital (default: 100000)             |
| parameters | object | No       | Strategy-specific parameters                   |

**Supported Strategies:**

| Strategy | Parameters | Description |
|----------|------------|-------------|
| sma_crossover | short_period (20), long_period (50) | Buy when short SMA crosses above long SMA |
| rsi_reversal | oversold (30), overbought (70) | Buy when RSI < oversold, sell when RSI > overbought |
| macd_crossover | - | Buy/sell on MACD signal line crossovers |
| bollinger_bounce | - | Buy at lower band, sell at upper band |

**Example Request:**
```bash
POST /api/stock-data/analysis/backtest/
Content-Type: application/json

{
  "strategy": "sma_crossover",
  "symbol": "NABIL",
  "start_date": "2023-01-01",
  "end_date": "2024-01-01",
  "capital": 100000,
  "parameters": {
    "short_period": 20,
    "long_period": 50
  }
}
```

**Success Response (200 OK):**
```json
{
  "strategy": "sma_crossover",
  "symbol": "NABIL",
  "start_date": "2023-01-01",
  "end_date": "2024-01-01",
  "initial_capital": 100000,
  "final_value": 115000.00,
  "total_return": 15.00,
  "win_rate": 60.00,
  "max_drawdown": 8.50,
  "sharpe_ratio": 1.25,
  "total_trades": 10,
  "winning_trades": 6,
  "losing_trades": 4,
  "trades": [
    {
      "entry_price": 450.00,
      "exit_price": 480.00,
      "return": 0.0667
    }
  ]
}
```

---

## Portfolio Management API

Base URL: `/api/stock-data/`

### Overview

The Portfolio Management API provides endpoints for:
- Managing user portfolios
- Tracking stock holdings
- Recording trades
- Calculating portfolio performance

**Note:** Portfolio management endpoints require authentication.

---

### 1. Portfolio CRUD Operations

**Base URL:** `/api/stock-data/portfolios/`

#### List Portfolios

**GET** `/api/stock-data/portfolios/`

**Headers:**
```
Authorization: Bearer <your_jwt_token>
```

**Success Response (200 OK):**
```json
[
  {
    "id": 1,
    "name": "My Investment Portfolio",
    "description": "Long-term investments",
    "initial_capital": "100000.00",
    "current_value": "115000.00",
    "total_return": 15.00,
    "holdings_count": 5,
    "holdings": [...],
    "is_active": true,
    "created_at": "2024-01-01T10:00:00Z",
    "updated_at": "2024-01-15T14:30:00Z"
  }
]
```

#### Create Portfolio

**POST** `/api/stock-data/portfolios/`

**Request Body:**
```json
{
  "name": "Tech Stocks Portfolio",
  "description": "Investment in technology sector",
  "initial_capital": 50000
}
```

#### Update Portfolio

**PUT** `/api/stock-data/portfolios/{id}/`

#### Delete Portfolio

**DELETE** `/api/stock-data/portfolios/{id}/`

---

### 2. Holdings Management

**Base URL:** `/api/stock-data/holdings/`

#### List Holdings

**GET** `/api/stock-data/holdings/`

**Success Response (200 OK):**
```json
[
  {
    "id": 1,
    "portfolio": 1,
    "stock": 5,
    "stock_symbol": "NABIL",
    "stock_name": "Nabil Bank Limited",
    "quantity": 100,
    "average_buy_price": "450.00",
    "current_price": "465.00",
    "market_value": "46500.00",
    "profit_loss": "1500.00",
    "profit_loss_percentage": 3.33,
    "created_at": "2024-01-05T10:00:00Z",
    "updated_at": "2024-01-15T14:30:00Z"
  }
]
```

#### Add Holding

**POST** `/api/stock-data/holdings/`

**Request Body:**
```json
{
  "portfolio": 1,
  "stock": 5,
  "quantity": 100,
  "average_buy_price": 450.00
}
```

---

### 3. Trade Management

**Base URL:** `/api/stock-data/trades/`

#### List Trades

**GET** `/api/stock-data/trades/`

**Success Response (200 OK):**
```json
[
  {
    "id": 1,
    "portfolio": 1,
    "stock": 5,
    "stock_symbol": "NABIL",
    "stock_name": "Nabil Bank Limited",
    "trade_type": "BUY",
    "quantity": 100,
    "entry_price": "450.00",
    "exit_price": "480.00",
    "entry_date": "2024-01-05",
    "exit_date": "2024-01-15",
    "return_amount": "3000.00",
    "return_percentage": 6.67,
    "notes": "Sold on uptrend",
    "created_at": "2024-01-05T10:00:00Z"
  }
]
```

#### Create Trade

**POST** `/api/stock-data/trades/`

**Request Body:**
```json
{
  "portfolio": 1,
  "stock": 5,
  "trade_type": "BUY",
  "quantity": 100,
  "entry_price": 450.00,
  "entry_date": "2024-01-05",
  "notes": "Buying on support level"
}
```

---

### 4. Portfolio Performance

Calculate performance metrics for a portfolio or ad-hoc trades.

#### Get Portfolio Performance

**GET** `/api/stock-data/portfolio-performance/?portfolio_id=1`

**Headers:**
```
Authorization: Bearer <your_jwt_token>
```

**Success Response (200 OK):**
```json
{
  "portfolio_id": 1,
  "portfolio_name": "My Investment Portfolio",
  "initial_capital": 100000.00,
  "total_invested": 45000.00,
  "current_value": 48500.00,
  "total_profit_loss": 3500.00,
  "total_return": 7.78,
  "holdings_count": 5,
  "total_trades": 12,
  "completed_trades": 8,
  "win_rate": 62.5
}
```

#### Calculate Ad-hoc Performance

**POST** `/api/stock-data/portfolio-performance/`

Calculate performance for a list of trades (no authentication required).

**Request Body:**
```json
{
  "trades": [
    {
      "entry_price": 450,
      "exit_price": 480,
      "quantity": 100
    },
    {
      "entry_price": 500,
      "exit_price": 475,
      "quantity": 50
    }
  ]
}
```

**Success Response (200 OK):**
```json
{
  "total_return": 4.17,
  "win_rate": 50.00,
  "sharpe_ratio": 0.85,
  "max_drawdown": 5.00,
  "total_trades": 2,
  "winning_trades": 1,
  "losing_trades": 1
}
```

---

### 5. View Backtest Results

**GET** `/api/stock-data/analysis/backtest-results/`

View saved backtest results (requires authentication).

**Success Response (200 OK):**
```json
[
  {
    "id": 1,
    "stock": 5,
    "stock_symbol": "NABIL",
    "strategy_name": "sma_crossover",
    "start_date": "2023-01-01",
    "end_date": "2024-01-01",
    "initial_capital": "100000.00",
    "final_value": "115000.00",
    "total_return": "15.0000",
    "win_rate": "60.00",
    "max_drawdown": "8.5000",
    "sharpe_ratio": "1.2500",
    "total_trades": 10,
    "winning_trades": 6,
    "losing_trades": 4,
    "parameters": {
      "short_period": 20,
      "long_period": 50
    },
    "created_at": "2024-01-15T10:00:00Z"
  }
]
```

---

## Unusual Activity Detection API

Base URL: `/api/stock-data/analysis/`

### Overview

The Unusual Activity Detection API helps identify potential accumulation patterns and insider activity by detecting:

---

### TOP STOCKS TO WATCH (Primary Endpoint)

**GET** `/api/stock-data/analysis/top-stocks/`

This is the **main endpoint** for daily monitoring. It combines signals from all analysis methods and returns the best stocks to watch, ranked by a combined score.

**Query Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| symbol | string | - | Optional: specific stock symbol or comma-separated list |
| limit | int | 20 | Number of stocks to return (max: 100) - ignored if symbol provided |
| min_score | float | 40 | Minimum combined score - ignored if symbol provided |

**Example Requests:**
```bash
# Get top 20 stocks (default)
GET /api/stock-data/analysis/top-stocks/

# Get top 50 stocks
GET /api/stock-data/analysis/top-stocks/?limit=50

# Get only high-confidence signals (score >= 60)
GET /api/stock-data/analysis/top-stocks/?limit=20&min_score=60

# Get analysis for a SINGLE stock
GET /api/stock-data/analysis/top-stocks/?symbol=AKJCL

# Get analysis for MULTIPLE specific stocks
GET /api/stock-data/analysis/top-stocks/?symbol=AKJCL,RADHI,RFPL,NABIL
```

**Single Symbol Response:**
```json
{
  "date": "2026-02-01",
  "stock": {
    "symbol": "AKJCL",
    "combined_score": 69.0,
    "alert_level": "BUY_SIGNAL",
    "summary": "Extreme Volume 4.0X | Sustained Accumulation 3 Days | Near Resistance",
    ...
  }
}
```

**Multiple Symbols Response:**
```json
{
  "date": "2026-02-01",
  "requested": 4,
  "returned": 3,
  "not_found": ["INVALID"],
  "stocks": [...]
}
```

**Success Response (200 OK):**
```json
{
  "date": "2026-02-01",
  "total_analyzed": 250,
  "stocks_meeting_criteria": 45,
  "returned": 20,
  "parameters": {
    "limit": 20,
    "min_score": 40
  },
  "stocks": [
    {
      "symbol": "AKJCL",
      "security_name": "Aakaash Capital Limited",
      "combined_score": 69.0,
      "alert_level": "BUY_SIGNAL",
      "current_price": 326.40,
      "date": "2026-02-01",
      
      "score_breakdown": {
        "accumulation": 29.0,
        "breakout_readiness": 24.0,
        "momentum": 16.0
      },
      
      "key_metrics": {
        "max_volume_ratio": 4.0,
        "unusual_days_count": 3,
        "distance_to_resistance": 2.5,
        "sma_20": 285.50,
        "resistance": 341.00,
        "support": 268.30
      },
      
      "signals": {
        "accumulation": ["EXTREME_VOLUME_4.0x", "MODERATE_PRICE_MOVE", "SUSTAINED_ACCUMULATION_3_DAYS"],
        "breakout": ["NEAR_RESISTANCE", "ABOVE_SMA20", "VOLUME_SURGE"],
        "momentum": ["POSITIVE_MOMENTUM_5.2%", "BULLISH_CANDLES"]
      },
      
      "recent_unusual_activity": [
        {
          "date": "2026-01-28",
          "price": 304.70,
          "volume_ratio": 4.0,
          "price_change": 3.5,
          "is_green": true
        }
      ],
      
      "summary": "Extreme Volume 4.0X | Sustained Accumulation 3 Days | Near Resistance"
    }
  ]
}
```

**Alert Levels:**
| Level | Score Range | Action |
|-------|-------------|--------|
| STRONG_BUY_SIGNAL | >= 70 | Highest priority, immediate attention |
| BUY_SIGNAL | 55-69 | Strong candidate, add to watchlist |
| WATCH_CLOSELY | 40-54 | Monitor for improvement |
| MONITOR | < 40 | Low priority |

**Score Components (Max 100 points):**

| Component | Max Points | What It Measures |
|-----------|------------|------------------|
| Accumulation | 35 | Volume spikes with stable prices |
| Breakout Readiness | 35 | Near resistance, above SMAs, consolidation |
| Momentum | 30 | Price trend, candle patterns, trade size |

**Key Signals Explained:**

| Signal | Meaning |
|--------|---------|
| `EXTREME_VOLUME_Xx` | Volume 2.5x+ above average |
| `HIGH_VOLUME_Xx` | Volume 2.0-2.5x above average |
| `SUSTAINED_ACCUMULATION_N_DAYS` | N consecutive days of unusual activity |
| `AT_RESISTANCE` | Price within 2% of 20-day high |
| `LARGE_BLOCK_TRADES` | Trade size increasing 30%+ |
| `BULLISH_CANDLES` | 70%+ green candles in last 10 days |

---

### Other Detection Endpoints

The following endpoints provide more detailed analysis:
- Unusual volume spikes before price movements
- Volume accumulation while price remains stable
- Large block trades indicating institutional activity
- Patterns that historically precede significant breakouts

**Use Cases:**
- Identify stocks being accumulated before breakouts
- Monitor for potential insider activity
- Create watchlists of stocks showing unusual patterns
- Get early alerts before major price movements

---

### 1. Unusual Activity Detector

Scan all stocks for unusual activity patterns.

**GET** `/api/stock-data/analysis/unusual-activity/`

**Query Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| days_lookback | int | 30 | Number of days to analyze (7-90) |
| volume_threshold | float | 1.5 | Volume vs average threshold (1.5 = 150%) |
| price_threshold | float | 4.0 | Max price change % during accumulation |
| min_volume | int | 10000 | Minimum absolute volume to consider |

**Example Request:**
```bash
GET /api/stock-data/analysis/unusual-activity/?days_lookback=30&volume_threshold=1.5
```

**Success Response (200 OK):**
```json
{
  "analysis_date": "2026-01-29",
  "lookback_days": 30,
  "parameters": {
    "volume_threshold": 1.5,
    "price_threshold": 4.0,
    "min_volume": 10000
  },
  "total_unusual_stocks": 15,
  "stocks": [
    {
      "symbol": "AKJCL",
      "security_name": "Aakaash Capital Limited",
      "suspicion_score": 78.5,
      "current_price": 304.70,
      "latest_date": "2026-01-28",
      "unusual_activity_days": 4,
      "patterns_detected": [
        "VOLUME_ACCUMULATION",
        "LARGE_BLOCK_TRADES",
        "RECENT_SPIKE",
        "BULLISH_ACCUMULATION"
      ],
      "price_movement_after": {
        "detected": true,
        "total_change_pct": 45.2,
        "max_gain_pct": 52.1,
        "max_loss_pct": -3.2,
        "days_analyzed": 12,
        "breakout_confirmed": true
      },
      "recent_unusual_events": [
        {
          "date": "2026-01-18",
          "close_price": 209.10,
          "change_pct": 3.11,
          "volume": 404482,
          "volume_vs_avg": 2.24,
          "avg_trade_size": 415,
          "is_green": true
        }
      ],
      "metrics": {
        "avg_daily_volume": 250000,
        "max_volume_spike": 3.96,
        "avg_trade_size_trend": "strongly_increasing",
        "consecutive_unusual_days": 3
      }
    }
  ]
}
```

**Suspicion Score Factors:**
- Number of unusual volume days (0-25 points)
- Magnitude of volume spikes (0-25 points)
- Volume trend direction (0-15 points)
- Price stability during accumulation (0-15 points)
- Consecutive unusual days (0-10 points)
- Recency of activity (0-10 points)

**Pattern Types:**
| Pattern | Description |
|---------|-------------|
| VOLUME_ACCUMULATION | High volume with stable prices |
| VOLUME_TREND_UP | Volume increasing over time |
| LARGE_BLOCK_TRADES | Average trade size significantly higher |
| CONSECUTIVE_UNUSUAL_ACTIVITY | 3+ consecutive unusual days |
| RECENT_SPIKE | Unusual activity in last 3 days |
| BULLISH_ACCUMULATION | Green candles with high volume |

---

### 2. Accumulation Alerts

Get immediate actionable alerts for accumulation patterns.

**GET** `/api/stock-data/analysis/accumulation-alerts/`

**Query Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| symbol | string | - | Optional: specific stock to check |
| alert_level | string | high | Alert level: 'high', 'medium', 'all' |

**Example Requests:**
```bash
# Get high-priority alerts
GET /api/stock-data/analysis/accumulation-alerts/

# Check specific stock
GET /api/stock-data/analysis/accumulation-alerts/?symbol=RADHI

# Get all alerts
GET /api/stock-data/analysis/accumulation-alerts/?alert_level=all
```

**Success Response (200 OK):**
```json
{
  "date": "2026-01-29",
  "total_alerts": 8,
  "high_alerts": 3,
  "medium_alerts": 5,
  "alerts": [
    {
      "alert": true,
      "alert_level": "high",
      "symbol": "AKJCL",
      "security_name": "Aakaash Capital Limited",
      "score": 72.5,
      "current_price": 304.70,
      "date": "2026-01-28",
      "unusual_days_count": 4,
      "max_volume_ratio": 2.24,
      "avg_price_change": 2.85,
      "message": "Volume 2.2x above average | 4 unusual volume days in last 5 days | Price stable during accumulation",
      "recent_activity": [
        {
          "date": "2026-01-18",
          "price": 209.10,
          "volume_ratio": 2.24,
          "change_pct": 3.11
        }
      ]
    }
  ]
}
```

**Alert Levels:**
| Level | Criteria |
|-------|----------|
| high | Score >= 60 OR Volume ratio >= 2.5x |
| medium | Score >= 35 OR Volume ratio >= 1.8x |
| low | Other unusual activity |

---

### 3. Breakout Watchlist

Get stocks showing accumulation patterns near potential breakout levels.

**GET** `/api/stock-data/analysis/breakout-watchlist/`

**Example Request:**
```bash
GET /api/stock-data/analysis/breakout-watchlist/
```

**Success Response (200 OK):**
```json
{
  "date": "2026-01-29",
  "total_candidates": 12,
  "watchlist": [
    {
      "symbol": "RADHI",
      "security_name": "Radhi Bidyut Company Limited",
      "breakout_score": 85.0,
      "current_price": 845.00,
      "resistance": 870.00,
      "support": 780.00,
      "sma_20": 825.50,
      "volume_ratio": 1.79,
      "signals": [
        "HIGH_VOLUME_SPIKE",
        "NEAR_RESISTANCE",
        "ABOVE_SMA_20",
        "VOLUME_TREND_UP"
      ],
      "date": "2026-01-29"
    }
  ]
}
```

**Breakout Signals:**
| Signal | Points | Description |
|--------|--------|-------------|
| HIGH_VOLUME_SPIKE | 30 | Recent volume >= 2x average |
| VOLUME_ABOVE_AVERAGE | 20 | Recent volume >= 1.5x average |
| NEAR_RESISTANCE | 25 | Price within 2% of 20-day high |
| APPROACHING_RESISTANCE | 15 | Price within 5% of 20-day high |
| ABOVE_SMA_20 | 15 | Price above 20-day SMA |
| VOLUME_TREND_UP | 15 | Volume increased 30%+ recently |
| TIGHT_CONSOLIDATION | 15 | Price range <= 10% in last 10 days |

---

## Workflow: Monitoring for Unusual Activity

### Daily Monitoring Routine

1. **Check Accumulation Alerts:**
```bash
GET /api/stock-data/analysis/accumulation-alerts/?alert_level=high
```

2. **Review Breakout Watchlist:**
```bash
GET /api/stock-data/analysis/breakout-watchlist/
```

3. **Deep dive on suspicious stocks:**
```bash
GET /api/stock-data/analysis/unusual-activity/?days_lookback=30
```

4. **Get technical signals for confirmation:**
```bash
GET /api/stock-data/analysis/signals/?symbol=AKJCL
```

### Interpreting Results

**High Suspicion Score (60+):**
- Multiple unusual volume days
- Volume 2x+ above average
- Price stable during accumulation
- Consider adding to watchlist

**Confirmed Breakout Pattern:**
- Accumulation detected 3-5 days before
- Price breaks resistance with volume
- Green candles with increasing volume

---

## Floorsheet Data API

Base URL: `/api/stock-data/floorsheet/`

### Overview

The Floorsheet Data API provides endpoints for:
- Uploading and parsing floorsheet HTML from merolagani.com
- Retrieving stored floorsheet transactions
- Analyzing broker activity and trading patterns
- Detecting self-trades and large block trades

**Data Source:** Floorsheet data is scraped from [merolagani.com](https://merolagani.com)

---

### 1. Upload Floorsheet HTML

Parse floorsheet HTML content and save transactions to database.

**POST** `/api/stock-data/floorsheet/upload/`

**Request Body:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| symbol | string | Yes | Stock symbol (e.g., "MBJC") |
| html_content | string | Yes | Raw HTML from merolagani.com floorsheet tab |
| save_to_db | boolean | No | Save to database (default: true) |

**Example Request:**
```bash
POST /api/stock-data/floorsheet/upload/
Content-Type: application/json

{
  "symbol": "MBJC",
  "html_content": "<html>...floorsheet HTML...</html>",
  "save_to_db": true
}
```

**Success Response (200 OK):**
```json
{
  "symbol": "MBJC",
  "parse_metadata": {
    "symbol": "MBJC",
    "total_rows_found": 50,
    "successfully_parsed": 48,
    "parse_errors": 2,
    "errors": []
  },
  "transactions_count": 48,
  "save_stats": {
    "symbol": "MBJC",
    "total": 48,
    "created": 45,
    "updated": 3,
    "errors": 0,
    "error_messages": []
  },
  "sample_transactions": [
    {
      "transaction_date": "2026-02-01",
      "transaction_no": 2026020105024797,
      "buyer_broker": 57,
      "seller_broker": 29,
      "quantity": 81,
      "rate": 291.50,
      "amount": 23611.50
    }
  ]
}
```

---

### 2. Scrape Floorsheet (Selenium)

Automatically scrape floorsheet data from merolagani.com using Selenium WebDriver.
This is similar to how `NepalStockScraper` in `utils.py` works.

**POST** `/api/stock-data/floorsheet/scrape/`

**Request Body:**

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| symbol | string | Yes | - | Stock symbol (e.g., "MBJC") |
| date_from | string | No | Last 10 days | Start date in MM/DD/YYYY format |
| date_to | string | No | Today | End date in MM/DD/YYYY format |
| save_to_db | boolean | No | true | Save to database |
| scrape_all_pages | boolean | No | true | Scrape all pagination pages |

**Date Handling:**
- If no dates provided: fetches data for the **last 10 days**
- Dates must be in `MM/DD/YYYY` format (e.g., "02/01/2026", "12/31/2025")

**Example Requests:**

```bash
# Get last 10 days (default)
POST /api/stock-data/floorsheet/scrape/
{
  "symbol": "MBJC"
}

# Get specific date range
POST /api/stock-data/floorsheet/scrape/
{
  "symbol": "MBJC",
  "date_from": "01/22/2026",
  "date_to": "02/01/2026"
}

# Get single day
POST /api/stock-data/floorsheet/scrape/
{
  "symbol": "MBJC",
  "date_from": "02/01/2026",
  "date_to": "02/01/2026"
}
```

**What it does:**
1. Opens Chrome WebDriver (headless mode)
2. Navigates to `https://merolagani.com/CompanyDetail.aspx?symbol=MBJC`
3. Clicks the "Floorsheet" tab (JavaScript postback)
4. Applies date filters if specified
5. **Scrapes ALL pages** (handles pagination - e.g., 306 records across 4 pages)
6. Parses all floorsheet tables
7. Saves transactions to database

**Success Response (200 OK):**
```json
{
  "symbol": "MBJC",
  "date_range": {
    "from": "01/22/2026",
    "to": "02/01/2026"
  },
  "scrape_metadata": {
    "symbol": "MBJC",
    "url": "https://merolagani.com/CompanyDetail.aspx?symbol=MBJC",
    "date_from": "01/22/2026",
    "date_to": "02/01/2026",
    "total_rows_found": 306,
    "successfully_parsed": 306,
    "parse_errors": 0,
    "pages_scraped": 4,
    "total_pages": 4,
    "total_records_expected": 306,
    "errors": [],
    "scrape_method": "selenium"
  },
  "transactions_count": 306,
  "save_stats": {
    "symbol": "MBJC",
    "total": 306,
    "created": 300,
    "updated": 6,
    "errors": 0,
    "error_messages": []
  },
  "sample_transactions": [...]
}
```

**Pagination Handling:**
- Automatically detects pagination (e.g., "Showing 1-100 of 306 records [Total pages: 4]")
- Clicks through all pages to collect all data
- Reports pages_scraped and total_pages in metadata

**Requirements:**
- Chrome browser installed on server
- ChromeDriver available in PATH
- Selenium already in requirements.txt

---

### 3. Get Floorsheet Data

Retrieve stored floorsheet transactions with filtering options.

**GET** `/api/stock-data/floorsheet/data/`

**Query Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| symbol | string | Yes | - | Stock symbol |
| days | int | No | 7 | Number of days to fetch (if no date range) |
| start_date | string | No | - | Start date (YYYY-MM-DD) |
| end_date | string | No | - | End date (YYYY-MM-DD) |
| buyer | int | No | - | Filter by buyer broker number |
| seller | int | No | - | Filter by seller broker number |
| limit | int | No | 1000 | Max records to return |

**Example Requests:**
```bash
# Get last 7 days of floorsheet data
GET /api/stock-data/floorsheet/data/?symbol=MBJC

# Get specific date range
GET /api/stock-data/floorsheet/data/?symbol=MBJC&start_date=2026-01-15&end_date=2026-02-01

# Filter by specific broker
GET /api/stock-data/floorsheet/data/?symbol=MBJC&buyer=57

# Filter by both buyer and seller
GET /api/stock-data/floorsheet/data/?symbol=MBJC&buyer=57&seller=29
```

**Success Response (200 OK):**
```json
{
  "symbol": "MBJC",
  "count": 156,
  "summary": {
    "total_quantity": 25800,
    "total_amount": 7523520.00,
    "avg_rate": 291.45,
    "transaction_count": 156
  },
  "transactions": [
    {
      "transaction_date": "2026-02-01",
      "transaction_no": 2026020105024797,
      "buyer_broker": 57,
      "seller_broker": 29,
      "quantity": 81,
      "rate": 291.50,
      "amount": 23611.50,
      "scraped_at": "2026-02-01T15:30:00Z"
    }
  ]
}
```

---

### 4. Floorsheet Analysis

Analyze floorsheet patterns including broker activity, self-trades, and large blocks.

**GET** `/api/stock-data/floorsheet/analysis/`

**Query Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| symbol | string | Yes | - | Stock symbol |
| days | int | No | 30 | Number of days to analyze |

**Example Request:**
```bash
GET /api/stock-data/floorsheet/analysis/?symbol=MBJC&days=30
```

**Success Response (200 OK):**
```json
{
  "symbol": "MBJC",
  "date_range": {
    "start": "2026-01-02",
    "end": "2026-02-01"
  },
  "overview": {
    "total_trades": 1250,
    "total_quantity": 185000,
    "total_amount": 53887500.00,
    "unique_buyers": 45,
    "unique_sellers": 52
  },
  "top_buyers": [
    {
      "buyer_broker": 57,
      "total_quantity": 25000,
      "total_amount": 7287500.00,
      "transaction_count": 85
    }
  ],
  "top_sellers": [
    {
      "seller_broker": 29,
      "total_quantity": 18000,
      "total_amount": 5246100.00,
      "transaction_count": 62
    }
  ],
  "self_trades": {
    "count": 45,
    "total_quantity": 12000,
    "total_amount": 3498000.00,
    "percentage_of_volume": 6.48
  },
  "large_block_trades": {
    "threshold_quantity": 750,
    "trades": [
      {
        "transaction_date": "2026-01-28",
        "transaction_no": 2026012805012345,
        "buyer_broker": 6,
        "seller_broker": 49,
        "quantity": 5000,
        "rate": 291.50,
        "amount": 1457500.00
      }
    ]
  },
  "daily_volume": [
    {
      "date": "2026-01-15",
      "total_quantity": 8500,
      "total_amount": 2477975.00,
      "trade_count": 45,
      "avg_rate": 291.52
    }
  ],
  "concentration": {
    "buyer_hhi": 1850.25,
    "interpretation": "Moderately concentrated"
  }
}
```

**Analysis Components:**

| Component | Description |
|-----------|-------------|
| Top Buyers/Sellers | Most active brokers by volume |
| Self-trades | Same broker on both sides (potential manipulation indicator) |
| Large Block Trades | Trades 5x above average size (institutional activity) |
| Daily Volume | Daily transaction patterns |
| Concentration (HHI) | Market concentration indicator |

**HHI Interpretation:**
| HHI Score | Interpretation |
|-----------|----------------|
| > 2500 | Highly concentrated |
| 1500-2500 | Moderately concentrated |
| < 1500 | Competitive/Distributed |

---

### 5. Broker Activity Tracker

Track a specific broker's activity across all stocks.

**GET** `/api/stock-data/floorsheet/broker/`

**Query Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| broker | int | Yes | - | Broker number to track |
| days | int | No | 30 | Number of days to analyze |
| symbol | string | No | - | Optional: filter to specific stock |
| role | string | No | "both" | "buyer", "seller", or "both" |

**Example Requests:**
```bash
# Track broker 57 across all stocks
GET /api/stock-data/floorsheet/broker/?broker=57

# Track broker as buyer only
GET /api/stock-data/floorsheet/broker/?broker=57&role=buyer

# Track broker for specific stock
GET /api/stock-data/floorsheet/broker/?broker=57&symbol=MBJC
```

**Success Response (200 OK):**
```json
{
  "broker": 57,
  "date_range": {
    "start": "2026-01-02",
    "end": "2026-02-01"
  },
  "summary": {
    "total_bought_quantity": 125000,
    "total_sold_quantity": 85000,
    "net_quantity": 40000,
    "overall_position": "ACCUMULATING",
    "stocks_traded": 15
  },
  "positions": [
    {
      "symbol": "MBJC",
      "bought_quantity": 25000,
      "bought_amount": 7287500.00,
      "buy_count": 85,
      "sold_quantity": 12000,
      "sold_amount": 3498000.00,
      "sell_count": 45,
      "net_quantity": 13000,
      "net_amount": 3789500.00,
      "net_position": "ACCUMULATING"
    },
    {
      "symbol": "AKJCL",
      "bought_quantity": 5000,
      "bought_amount": 1532000.00,
      "buy_count": 15,
      "sold_quantity": 8000,
      "sold_amount": 2451200.00,
      "sell_count": 22,
      "net_quantity": -3000,
      "net_amount": -919200.00,
      "net_position": "DISTRIBUTING"
    }
  ]
}
```

**Position Types:**
| Position | Meaning |
|----------|---------|
| ACCUMULATING | Broker is net buyer (buying more than selling) |
| DISTRIBUTING | Broker is net seller (selling more than buying) |

---

### FloorsheetData Model

```json
{
  "id": 1,
  "stock": 5,
  "transaction_date": "2026-02-01",
  "transaction_no": 2026020105024797,
  "buyer_broker": 57,
  "seller_broker": 29,
  "quantity": 81,
  "rate": "291.50",
  "amount": "23611.50",
  "scraped_at": "2026-02-01T15:30:00Z"
}
```

---

### How to Scrape Floorsheet Data

1. **Navigate to merolagani.com:**
   ```
   https://merolagani.com/CompanyDetail.aspx?symbol=MBJC
   ```

2. **Click the "Floorsheet" tab** to load floorsheet data

3. **Copy the full page HTML** (right-click → View Page Source or Inspect → copy `<html>` tag)

4. **Upload via API:**
   ```bash
   POST /api/stock-data/floorsheet/upload/
   {
     "symbol": "MBJC",
     "html_content": "<html>...copied HTML...</html>"
   }
   ```

---

### 6. Broker Holdings by Stock

Per-broker bought / sold / net quantities for a single stock over a date range, plus an
optional carry-forward position estimate.

```
GET /api/stock-data/floorsheet/broker-holdings/
```

**Query Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `symbol` | string | *required* | Stock symbol, case-insensitive |
| `start_date` | date | 30 days before `end_date` | Range start, `YYYY-MM-DD` |
| `end_date` | date | Symbol's latest date with floorsheet data | Range end, `YYYY-MM-DD` |
| `lookback_days` | integer | `0` | Cap how far back the carry-forward baseline reaches. `0` = use all available history |
| `exclude_self_trades` | boolean | `true` | Exclude trades where buyer == seller |
| `min_net_qty` | integer | `0` | Drop brokers whose absolute net is below this |
| `sort_by` | string | `net` | One of `net`, `bought`, `sold`, `broker` |
| `limit` | integer | `50` | Max brokers returned (capped at 500) |

> **Default date range note:** `end_date` deliberately resolves to the symbol's latest
> *available* floorsheet date rather than today. Floorsheet data lags well behind the
> current date, so a "last 30 days" default would render an empty page for most symbols.

**Example Request:**
```bash
curl "http://127.0.0.1:8000/api/stock-data/floorsheet/broker-holdings/?symbol=KKHC&start_date=2026-02-03&end_date=2026-02-05"
```

**Example Response:**
```json
{
  "symbol": "KKHC",
  "security_name": "Khanikhola Hydropower Co. Ltd.",
  "stock_type": "stock",
  "date_range": {
    "start": "2026-02-03",
    "end": "2026-02-05",
    "trading_days_expected": 3,
    "trading_days_with_data": 3
  },
  "baseline": {
    "requested_lookback_days": 0,
    "available_days": 0,
    "first_data_date": null,
    "is_continuous": false,
    "reliability": "none"
  },
  "coverage": {
    "trading_days_expected": 3,
    "trading_days_with_data": 3,
    "coverage_pct": 100.0,
    "missing_days": [],
    "warnings": [
      "No floorsheet history exists before the start of this range, so a carry-forward holdings estimate cannot be computed. Only in-range buy/sell activity is shown."
    ]
  },
  "summary": {
    "total_bought_qty": 723166,
    "total_sold_qty": 723166,
    "total_bought_amount": 174761243.9,
    "total_sold_amount": 174761243.9,
    "net_qty": 0,
    "net_amount": 0.0,
    "brokers_matched": 82,
    "brokers_reported": 50,
    "unique_buyers": 72,
    "unique_sellers": 77,
    "total_trades": 1794,
    "self_trade_qty_pct": 2.02,
    "self_trades_excluded": true,
    "top_accumulator": { "broker": 46, "net_qty": 139611 },
    "top_distributor": { "broker": 34, "net_qty": -92150 },
    "concentration": { "hhi": 686.88, "interpretation": "Competitive/Distributed" }
  },
  "brokers": [
    {
      "broker": 46,
      "bought_qty": 140300,
      "bought_amount": 35240463.8,
      "buy_count": 179,
      "avg_buy_rate": 250.73,
      "sold_qty": 689,
      "sold_amount": 164900.0,
      "sell_count": 9,
      "avg_sell_rate": 238.36,
      "net_qty": 139611,
      "net_amount": 35075563.8,
      "position": "ACCUMULATING",
      "baseline_qty": null,
      "estimated_holding_qty": null,
      "holdings_reliability": "none",
      "share_pct": 18.66,
      "daily_net": [
        { "date": "2026-02-03", "net_qty": -100 },
        { "date": "2026-02-04", "net_qty": 0 },
        { "date": "2026-02-05", "net_qty": 139711 }
      ]
    }
  ],
  "notes": [
    "NEPSE floorsheet shows broker agency flow, not beneficial ownership - brokers trade on behalf of clients."
  ]
}
```

#### Exact figures vs. estimates

This endpoint deliberately mixes two very different kinds of number, and separates them
in the response:

| Field | Reliability |
|-------|-------------|
| `bought_qty`, `sold_qty`, `net_qty`, amounts, counts, average rates | **Exact** for the selected range |
| `baseline_qty`, `estimated_holding_qty` | **Estimate** — depends on floorsheet rows *before* `start_date` |

The carry-forward estimate is:

```
estimated_holding[b] = baseline_net[b] + period_net[b]

baseline_net[b] = Σ(qty bought by b, date < start) − Σ(qty sold by b, date < start)
period_net[b]   = Σ(qty bought by b, start ≤ date ≤ end) − Σ(qty sold by b, start ≤ date ≤ end)
```

#### `holdings_reliability` tiers

| Tier | Meaning |
|------|---------|
| `none` | No floorsheet rows exist before `start_date`. `baseline_qty` and `estimated_holding_qty` are **`null`** |
| `partial` | Prior rows exist but are not continuous across the requested `lookback_days`. An estimate is returned and flagged |
| `full` | Prior rows are continuous across the lookback window, so the carry-forward position is a sound estimate |

A `null` holdings figure is intentional. Because floorsheet history is incomplete in
this database (the median stock has only 3 days of data), reporting a confident-looking
position for most symbols would be misleading. Range analytics remain exact regardless.

#### Other notes

- `net_qty` is **never** clamped to zero. A negative value is a genuine distributing signal.
- `summary` totals always describe the **whole range**, independent of `limit`. Use
  `brokers_matched` vs `brokers_reported` to tell whether the broker list was truncated.
- `share_pct` is a magnitude share across **all** brokers on **both** sides of the trade,
  so it sums to 100 and a broker's buyer and seller counterpart each hold half.
- Self-trades are excluded by default because they net to zero for a broker's own position
  while inflating activity and turnover (2.0% of quantity for KKHC, 6.7% for SIFC).
- `total_bought_qty` equals `total_sold_qty` for any stock/date window, since every
  floorsheet row is a matched trade with one buyer and one seller.
- Broker IDs outside the expected `1-100` range are **flagged in `notes`, not dropped**.
  ID `101` carries real quantities in this dataset.

#### Errors

| Status | Cause |
|--------|-------|
| `400` | Missing `symbol`, malformed date (must be `YYYY-MM-DD`), or `start_date > end_date` |
| `404` | No `Stock` with the given symbol |

---

## NEPSE Indices API

The NEPSE Indices API allows you to scrape and analyze market indices data from nepalstock.com. This includes the main NEPSE Index and all sub-indices like Banking, Hydro, Finance, etc.

### Available Indices

| ID | Index Name |
|----|------------|
| 51 | Banking SubIndex |
| 52 | Hotels And Tourism Index |
| 53 | Others Index |
| 54 | HydroPower Index |
| 55 | Development Bank Index |
| 56 | Manufacturing And Processing |
| 57 | Sensitive Index |
| 58 | NEPSE Index (Main) |
| 59 | Non Life Insurance |
| 60 | Finance Index |
| 61 | Trading Index |
| 62 | Float Index |
| 63 | Sensitive Float Index |
| 64 | Microfinance Index |
| 65 | Life Insurance |
| 66 | Mutual Fund |
| 67 | Investment Index |

---

### 1. Scrape NEPSE Indices

**POST** `/api/stock-data/indices/scrape/`

Scrape NEPSE indices data from nepalstock.com using headless Selenium.

**Permissions**: Public

**Request Body:**
```json
{
  "index_ids": [58, 51, 54],
  "max_pages": 5,
  "save_to_db": true,
  "skip_existing": true
}
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `index_ids` | array | No | List of index IDs to scrape. If not provided, scrapes ALL indices. |
| `max_pages` | int | No | Maximum pages per index (default: all pages) |
| `save_to_db` | bool | No | Save to database (default: true) |
| `skip_existing` | bool | No | Skip dates already in DB (default: true) |

**Example Request - Scrape All Indices:**
```bash
curl -X POST http://localhost:8000/api/stock-data/indices/scrape/ \
  -H "Content-Type: application/json" \
  -d '{}'
```

**Example Request - Scrape Specific Indices:**
```bash
curl -X POST http://localhost:8000/api/stock-data/indices/scrape/ \
  -H "Content-Type: application/json" \
  -d '{
    "index_ids": [58, 51, 54, 55],
    "max_pages": 10
  }'
```

**Example Response:**
```json
{
  "success": true,
  "total_records_scraped": 2450,
  "summary": {
    "NEPSE Index": {
      "index_id": 58,
      "records_scraped": 245,
      "date_range": {
        "from": "2025-01-15",
        "to": "2026-02-01"
      },
      "db_stats": {
        "created": 200,
        "updated": 0,
        "skipped": 45,
        "errors": 0
      }
    },
    "Banking SubIndex": {
      "index_id": 51,
      "records_scraped": 245,
      "date_range": {
        "from": "2025-01-15",
        "to": "2026-02-01"
      },
      "db_stats": {
        "created": 245,
        "updated": 0,
        "skipped": 0,
        "errors": 0
      }
    }
  }
}
```

**GET** `/api/stock-data/indices/scrape/`

Get available indices information and API usage.

---

### 2. Get NEPSE Indices Data

**GET** `/api/stock-data/indices/data/`

Retrieve indices data from the database.

**Permissions**: Public

**Query Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `index_id` | int | Filter by index ID |
| `index_name` | string | Filter by index name (partial match) |
| `date_from` | string | Start date (YYYY-MM-DD) |
| `date_to` | string | End date (YYYY-MM-DD) |
| `days` | int | Get last N days of data (default: 30) |
| `limit` | int | Max records to return (default: 100) |
| `offset` | int | Pagination offset |

**Example Request:**
```bash
curl -X GET "http://localhost:8000/api/stock-data/indices/data/?index_id=58&days=30"
```

**Example Response:**
```json
{
  "total_count": 22,
  "limit": 100,
  "offset": 0,
  "data": [
    {
      "id": 1,
      "index_id": 58,
      "index_name": "NEPSE Index",
      "date": "2026-02-01",
      "close": 2694.20,
      "high": 2719.62,
      "low": 2688.08,
      "absolute_change": -19.85,
      "percentage_change": -0.73,
      "fifty_two_weeks_high": 3002.07,
      "fifty_two_weeks_low": 2487.17,
      "turnover_value": 8987854804.30,
      "turnover_volume": 19120133,
      "total_transactions": 109261
    }
  ]
}
```

---

### 3. NEPSE Indices Analysis

**GET** `/api/stock-data/indices/analysis/`

Get detailed analysis of a specific NEPSE index.

**Permissions**: Public

**Query Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `index_id` | int | Yes | Index ID to analyze |
| `days` | int | No | Analysis period in days (default: 30) |

**Example Request:**
```bash
curl -X GET "http://localhost:8000/api/stock-data/indices/analysis/?index_id=58&days=30"
```

**Example Response:**
```json
{
  "index_id": 58,
  "index_name": "NEPSE Index",
  "analysis_period": {
    "days": 30,
    "date_from": "2026-01-02",
    "date_to": "2026-02-01",
    "trading_days": 22
  },
  "current": {
    "date": "2026-02-01",
    "close": 2694.20,
    "daily_change": -19.85,
    "daily_change_percent": -0.73
  },
  "statistics": {
    "avg_close": 2680.45,
    "max_close": 2772.17,
    "min_close": 2610.63,
    "period_return_percent": 2.81,
    "max_daily_gain_percent": 2.12,
    "max_daily_loss_percent": -1.53
  },
  "volume_analysis": {
    "avg_daily_volume": 16542385,
    "total_volume": 363932470,
    "avg_daily_turnover": 8254632158.45,
    "total_turnover": 181601907485.90,
    "avg_daily_transactions": 97562,
    "total_transactions": 2146364
  },
  "market_sentiment": {
    "positive_days": 10,
    "negative_days": 11,
    "unchanged_days": 1,
    "positive_ratio": 45.5,
    "trend": "uptrend"
  },
  "fifty_two_weeks": {
    "high": 3002.07,
    "low": 2487.17,
    "distance_from_high_percent": -10.25,
    "distance_from_low_percent": 8.33
  }
}
```

---

### 4. Compare NEPSE Indices

**GET** `/api/stock-data/indices/compare/`

Compare performance of multiple indices.

**Permissions**: Public

**Query Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `index_ids` | string | Yes | Comma-separated list of index IDs (e.g., "58,51,54") |
| `days` | int | No | Comparison period in days (default: 30) |

**Example Request:**
```bash
curl -X GET "http://localhost:8000/api/stock-data/indices/compare/?index_ids=58,51,54,55&days=30"
```

**Example Response:**
```json
{
  "comparison_period_days": 30,
  "date_from": "2026-01-02",
  "indices_count": 4,
  "comparison": [
    {
      "index_id": 54,
      "index_name": "HydroPower Index",
      "current_close": 1856.42,
      "start_close": 1725.30,
      "period_return_percent": 7.60,
      "daily_change_percent": -1.25,
      "avg_daily_volume": 8524612,
      "total_turnover": 45621548952.00,
      "positive_days_ratio": 54.5,
      "52_week_high": 2125.50,
      "52_week_low": 1425.80
    },
    {
      "index_id": 58,
      "index_name": "NEPSE Index",
      "current_close": 2694.20,
      "start_close": 2620.92,
      "period_return_percent": 2.80,
      "daily_change_percent": -0.73,
      "avg_daily_volume": 16542385,
      "total_turnover": 181601907485.90,
      "positive_days_ratio": 45.5,
      "52_week_high": 3002.07,
      "52_week_low": 2487.17
    },
    {
      "index_id": 51,
      "index_name": "Banking SubIndex",
      "current_close": 1245.60,
      "start_close": 1230.80,
      "period_return_percent": 1.20,
      "daily_change_percent": -0.45,
      "avg_daily_volume": 5125485,
      "total_turnover": 65421548245.00,
      "positive_days_ratio": 40.9,
      "52_week_high": 1450.20,
      "52_week_low": 1125.50
    },
    {
      "index_id": 55,
      "index_name": "Development Bank Index",
      "current_close": 2856.30,
      "start_close": 2895.40,
      "period_return_percent": -1.35,
      "daily_change_percent": -0.52,
      "avg_daily_volume": 2145325,
      "total_turnover": 25142536548.00,
      "positive_days_ratio": 36.4,
      "52_week_high": 3125.80,
      "52_week_low": 2650.20
    }
  ]
}
```

**Note:** Results are sorted by `period_return_percent` (best performers first).

---

### 5. List All NEPSE Indices

**GET** `/api/stock-data/indices/list/`

Get a list of all available indices with their latest data.

**Permissions**: Public

**Example Request:**
```bash
curl -X GET http://localhost:8000/api/stock-data/indices/list/
```

**Example Response:**
```json
{
  "total_indices": 17,
  "indices": [
    {
      "index_id": 51,
      "index_name": "Banking SubIndex",
      "record_count": 245,
      "latest_date": "2026-02-01",
      "latest_close": 1245.60,
      "daily_change": -5.62,
      "daily_change_percent": -0.45
    },
    {
      "index_id": 52,
      "index_name": "Hotels And Tourism Index",
      "record_count": 245,
      "latest_date": "2026-02-01",
      "latest_close": 958.25,
      "daily_change": 12.35,
      "daily_change_percent": 1.31
    },
    {
      "index_id": 58,
      "index_name": "NEPSE Index",
      "record_count": 245,
      "latest_date": "2026-02-01",
      "latest_close": 2694.20,
      "daily_change": -19.85,
      "daily_change_percent": -0.73
    }
  ]
}
```

---

### NepseIndex Model

```json
{
  "id": 1,
  "index_id": 58,
  "index_name": "NEPSE Index",
  "date": "2026-02-01",
  "close": 2694.20,
  "high": 2719.62,
  "low": 2688.08,
  "absolute_change": -19.85,
  "percentage_change": -0.73,
  "fifty_two_weeks_high": 3002.07,
  "fifty_two_weeks_low": 2487.17,
  "turnover_value": 8987854804.30,
  "turnover_volume": 19120133,
  "total_transactions": 109261,
  "scraped_at": "2026-02-02T04:30:00Z"
}
```

---

### How to Scrape NEPSE Indices

1. **Scrape all indices (recommended for initial setup):**
   ```bash
   POST /api/stock-data/indices/scrape/
   {}
   ```
   This will scrape all 17 indices with their full historical data (items per page set to 500 automatically).

2. **Scrape specific indices:**
   ```bash
   POST /api/stock-data/indices/scrape/
   {
     "index_ids": [58, 51, 54]
   }
   ```

3. **Incremental updates (skip existing dates):**
   ```bash
   POST /api/stock-data/indices/scrape/
   {
     "skip_existing": true
   }
   ```

**Notes:**
- The scraper runs in **headless mode** (no browser window)
- Items per page is automatically set to **500** for efficient scraping
- Each index may have multiple pages of data
- Existing dates can be skipped to avoid re-scraping

---

## Notes

1. **Date Format**: All dates should be in `YYYY-MM-DD` format
2. **Decimal Precision**: Prices are stored with 2 decimal places, metrics with 5 decimal places
3. **Time Zone**: All dates are stored in UTC
4. **Data Fetching**: The web scraping operation may take time depending on the number of days requested
5. **Model Requirements**: Predictions require at least 6 days of historical data per stock
6. **Unique Constraints**: Stock symbol and (stock, date) combinations must be unique
7. **Technical Indicators**: Require minimum 20-60 days of data for accurate calculations
8. **Backtesting**: Requires at least 60 data points for meaningful results
9. **Portfolio Management**: All portfolio endpoints require JWT authentication
10. **Unusual Activity Detection**: Works best with 20+ days of historical data
11. **NEPSE Indices Scraper**: Runs in headless mode with automatic items per page set to 500

---

## Support

For issues or questions, please refer to the codebase documentation or contact the development team.
