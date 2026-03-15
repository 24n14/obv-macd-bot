import os
import ccxt
import pandas as pd
import numpy as np
import time
import logging
from dotenv import load_dotenv
#from datetime import datetime
from typing import Literal

# =====настройка логирования =======

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler("bot_history.log", encoding='utf-8'), # Запись в файл
        logging.StreamHandler() # Дублирование в консоль PyCharm
    ]
)
logging.info("Бот запущен и готов к работе.")

# ===== НАСТРОЙКИ ПОДКЛЮЧЕНИЯ =====
load_dotenv()
#api_key = os.getenv('API_KEY')
#secret_key = os.getenv('SECRET_KEY')
# recv_window = "5000"
bybit = ccxt.bybit({
    'apiKey': os.getenv('API_KEY'),
    'secret': os.getenv('SECRET_KEY'),
    'enableRateLimit': True,
    'options': {
        'defaultType': 'linear', #<--Чтобы он сразу искал USDT-фьючерсы-->
        'recvWindow': 5000       #<--Окно времени для запросов-->
    }
})

bybit.enable_demo_trading(True)
bybit.options['defaultType'] = 'linear'
#==========запрос баланса==================

balance = bybit.fetch_balance()
# Безопасный способ получить USDT (вернет 0, если ключа нет)
usdt_balance = balance['total'].get('USDT', 0)
# Если USDT все еще 0, но в демо-аккаунте есть деньги (как у вас):
if usdt_balance == 0:
    # Для Unified Account в Demo данные лежат здесь:
    try:
        usdt_balance = float(balance['info']['result']['list'][0]['coin'][0]['equity'])
    except (KeyError, IndexError):
        usdt_balance = 0
logging.info(f"Рабочий баланс: {usdt_balance} USDT")

# ===== ПАРАМЕТРЫ ТОРГОВЛИ =====
SYMBOL = 'BTC/USDT:USDT'
CATEGORY = 'linear'
TIMEFRAME = '15m'
ORDER_AMOUNT = 0.01  # размер позиции в BTC

# ===== ПАРАМЕТРЫ ИНДИКАТОРА =====
OBV_LENGTH = 5
EMA_LENGTH = 14
MACD_FAST = 12
MACD_SLOW = 24
MACD_SIGNAL = 9

def fetch_ohlcv(symbol, timeframe='15m', limit=200):
    """Забираем свежие свечи."""
    ohlcv = bybit.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    df = pd.DataFrame(ohlcv, columns=['timestamp','open','high','low','close','volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    return df

def ema(series, length):
    return series.ewm(span=length, adjust=False).mean()

def calc_obv(df):
    """Расчёт OBV + сглаживание длиной OBV_LENGTH (если нужно)."""
    df = df.copy()
    df['direction'] = np.sign(df['close'].diff()).fillna(0)
    df['obv_raw'] = (df['volume'] * df['direction']).cumsum()
    # Можно ещё раз сгладить obv_raw по OBV_LENGTH, если хочешь
    if OBV_LENGTH > 1:
        df['obv'] = ema(df['obv_raw'], OBV_LENGTH)
    else:
        df['obv'] = df['obv_raw']
    return df

def calc_macd(series, fast=12, slow=24, signal=9):
    ema_fast = ema(series, fast)
    ema_slow = ema(series, slow)
    macd_line = ema_fast - ema_slow
    signal_line = ema(macd_line, signal)
    hist = macd_line - signal_line
    return macd_line, signal_line, hist

def get_position_side():
    """
    Определяем, есть ли открытая позиция по BTCUSDT.
    Возвращает: 'long', 'short' или None
    """
    try:
        positions = bybit.fetch_positions([SYMBOL])
        # Если positions — это не список (бывает при ошибках API),
        # проверка ниже предотвратит падение
        if not isinstance(positions, list):
            logging.info(f"Неожиданный ответ API: {positions}")
            return None

    except Exception as e:
        logging.info(f"Ошибка при запросе позиций: {e}")
        return None

    for p in positions:
        # Проверяем, что p — это словарь, прежде чем вызывать .get()
        if not isinstance(p, dict):
            continue

        # CCXT обычно приводит символы к единому виду.
        # Проще сравнивать напрямую с SYMBOL, если он задан верно для CCXT.
        if p.get('symbol') == SYMBOL:
            # Используем .get() с дефолтным значением 0
            size = float(p.get('contracts')  or 0)
            side = p.get('side')

            if size > 0:
                # Приводим к нижнему регистру для надежности
                return str(side).lower()

    return None

def close_position():
    """Закрытие открытой позиции по рынку."""
    side = get_position_side()
    if side is None:
        logging.info("Нет открытой позиции для закрытия.")
        return
    order_side: Literal['buy', 'sell']
    try:
        # Для закрытия лонга надо продать, для шорта — купить
        if side == 'long':
            order_side = 'sell'
        else:
            order_side = 'buy'
        
        logging.info(f"Закрываю {side} позицию по рынку...")
        bybit.create_order(
            symbol=SYMBOL,
            type='market',
            side=order_side,
            amount=ORDER_AMOUNT
        )
        logging.info(f"Ордер на закрытие отправлен.")
    except Exception as e:
        logging.info(f"Ошибка при закрытии позиции: {e}")

def open_position(direction):
    """
    Открытие позиции:
    direction: 'long' или 'short'
    """
    if direction not in ['long', 'short']:
        logging.info(f"Неверное направление: {direction}")
        return
    side: Literal['buy', 'sell']
    try:
        if direction == 'long':
            side = 'buy'
        else:
            side = 'sell'
        
        logging.info(f"Открываю {direction} позицию ({side}) по рынку, {ORDER_AMOUNT} BTC...")
        bybit.create_order(
            symbol=SYMBOL,
            type='market',
            side=side,
            amount=ORDER_AMOUNT
        )
        logging.info(f"Ордер на открытие отправлен.")
        logging.info(f"ОТКРЫТА ПОЗИЦИЯ: {direction.upper()} | Символ: {SYMBOL} | Объем: {ORDER_AMOUNT}")
    except Exception as e:
        logging.info(f"Ошибка при открытии позиции: {e}")
        logging.error(f"Ошибка при открытии позиции: {e}")
# ===== ОСНОВНОЙ ЦИКЛ СИГНАЛОВ =====

def run_bot_once():
    logging.info(f"Анализ рынка...")
    """
    Один проход:
    - забираем свечи
    - считаем OBV + MACD по OBV
    - определяем сигнал
    - открываем/закрываем позицию
    """
    df = fetch_ohlcv(SYMBOL, TIMEFRAME, limit=200)
    df = calc_obv(df)
    
    # MACD по OBV
    df['macd'], df['signal'], df['hist'] = calc_macd(
        df['obv'],
        fast=MACD_FAST,
        slow=MACD_SLOW,
        signal=MACD_SIGNAL
    )
    
    # Берём последние 2 свечи для пересечения
    last = df.iloc[-1]
    prev = df.iloc[-2]
    
    macd_prev, sig_prev = prev['macd'], prev['signal']
    macd_curr, sig_curr = last['macd'], last['signal']
    
    logging.info(f"\nВремя: {last['timestamp']}")
    logging.info(f"MACD_prev={macd_prev:.6f}, Signal_prev={sig_prev:.6f}")
    logging.info(f"MACD_curr={macd_curr:.6f}, Signal_curr={sig_curr:.6f}")
    
    long_signal = (macd_prev < sig_prev) and (macd_curr > sig_curr)
    short_signal = (macd_prev > sig_prev) and (macd_curr < sig_curr)
    
    current_pos = get_position_side()
    logging.info(f"Текущая позиция: {current_pos}")
    
    if long_signal:
        logging.info(f"Сигнал на ЛОНГ.")
        # если есть шорт — закрываем
        if current_pos == 'short':
            close_position()
        # если нет лонга — открываем
        if current_pos != 'long':
            open_position('long')
        else:
            logging.info(f"Лонг уже открыт, не открываю повторно.")
    
    elif short_signal:
        logging.info(f"Сигнал на ШОРТ.")
        # если есть лонг — закрываем
        if current_pos == 'long':
            close_position()
        # если нет шорта — открываем
        if current_pos != 'short':
            open_position('short')
        else:
            logging.info(f"Шорт уже открыт, не открываю повторно.")
    else:
        logging.info(f"Нового сигнала нет.")

def log_to_file(message):
    with open("bot_log.txt", "a") as f:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} - {message}\n")


if __name__ == "__main__":
    # Можно запускать в цикле с паузой
    while True:
        try:
            run_bot_once()
        except Exception as e:
            logging.info(f"Глобальная ошибка в цикле:{e} ")
        # Пауза между проверками (например, 60 сек)
        time.sleep(60)

