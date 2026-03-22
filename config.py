import os
from dotenv import load_dotenv

load_dotenv()

# ===== НАСТРОЙКИ ПОДКЛЮЧЕНИЯ =====
API_KEY = os.getenv('API_KEY')
SECRET_KEY = os.getenv('SECRET_KEY')
ENABLE_DEMO = True # True для демо-счета, False для реального
TG_TOKEN = os.getenv('TG_TOKEN')
TG_CHAT_ID = os.getenv('TG_CHAT_ID')

# ===== ПАРАМЕТРЫ ТОРГОВЛИ =====
SYMBOL = 'BTC/USDT:USDT'
CATEGORY = 'linear'
TIMEFRAME = '5m'
ORDER_AMOUNT = 0.01  # размер позиции в BTC
LIMIT = 200

# ===== ПАРАМЕТРЫ ИНДИКАТОРА =====
OBV_LENGTH = 2
EMA_LENGTH = 14
MACD_FAST = 12
MACD_SLOW = 24
MACD_SIGNAL = 9

# =====ПАРАМЕТРЫ ПРОКСИ =====
PROXY_HOST = '154.219.207.178'
PROXY_PORT = '63690'
PROXY_USER = os.getenv('PROXY_USER')
PROXY_PASS = os.getenv('PROXY_PASS')
USE_PROXY = True