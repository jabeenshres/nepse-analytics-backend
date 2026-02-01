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

## Notes

1. **Date Format**: All dates should be in `YYYY-MM-DD` format
2. **Decimal Precision**: Prices are stored with 2 decimal places, metrics with 5 decimal places
3. **Time Zone**: All dates are stored in UTC
4. **Data Fetching**: The web scraping operation may take time depending on the number of days requested
5. **Model Requirements**: Predictions require at least 6 days of historical data per stock
6. **Unique Constraints**: Stock symbol and (stock, date) combinations must be unique

---

## Support

For issues or questions, please refer to the codebase documentation or contact the development team.
