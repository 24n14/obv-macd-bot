import os
from dotenv import load_dotenv

load_dotenv()

# ===== НАСТРОЙКИ ПОДКЛЮЧЕНИЯ =====
API_KEY = os.getenv('API_KEY')
SECRET_KEY = os.getenv('SECRET_KEY')
ENABLE_DEMO = True # True для демо-счета, False для реального

# ===== ПАРАМЕТРЫ ТОРГОВЛИ =====
SYMBOL = 'BTC/USDT:USDT'
CATEGORY = 'linear'
TIMEFRAME = '15m'
ORDER_AMOUNT = 0.01  # размер позиции в BTC
LIMIT = 200
# ===== ПАРАМЕТРЫ ИНДИКАТОРА =====
OBV_LENGTH = 2
EMA_LENGTH = 14
MACD_FAST = 12
MACD_SLOW = 24
MACD_SIGNAL = 9

TG_TOKEN = '7520972174:AAED-3L7U4HsKxtR_7I3aSp0ojw7G6UnYUI' #'874967342:AAEpZxlGUumcAwXuHZ6g84Cyp3Zh011P3no'
TG_CHAT_ID = '6210921859'
PROXY_HOST = '154.219.207.178'
PROXY_PORT = '63690'
PROXY_USER = 'hwVGinSC'
PROXY_PASS = 'shT11Rug'
