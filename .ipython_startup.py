"""
IPython startup script for Django.
Run this in IPython: exec(open('.ipython_startup.py').read())
Or add to your IPython profile startup directory.
"""
import os
import sys
import django

# Add the project directory to the Python path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# Configure Django settings
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'stock_BE.settings')
django.setup()

# Import commonly used models
from StockData.models import Stock, StockData
from accounts.models import User

print("✓ Django configured successfully!")
print("Available models: Stock, StockData, User")
