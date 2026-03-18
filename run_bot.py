import ccxt
import pandas as pd
import numpy as np
import time
import logging
from typing import Literal

#====Импортируем все настройки из нашего файла config.py====
import config

#==== Настройка логирования====
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("bot_history.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
    )
logging.info("Бот запущен и готов к работе.")
logger = logging.getLogger(__name__)

# ===== ПОДКЛЮЧЕНИЕ К BYBIT =====
bybit = ccxt.bybit({
    'apiKey': config.API_KEY,
    'secret': config.SECRET_KEY,
    'enableRateLimit': True,
    'options': {
        'defaultType': 'linear',
        'recvWindow': 5000
    }
})

bybit.enable_demo_trading(config.ENABLE_DEMO)
bybit.options['defaultType'] = 'linear'

# ========== ЗАПРОС БАЛАНСА ==========
balance = bybit.fetch_balance()
# Безопасный способ получить USDT (вернет 0, если ключа нет)
usdt_balance = balance['total'].get('USDT', 0)

if usdt_balance == 0:
    try:
        usdt_balance = float(balance['info']['result']['list'][0]['coin'][0]['equity'])
    except (KeyError, IndexError):
        usdt_balance = 0
logging.info(f"Рабочий баланс: {usdt_balance} USDT")

# ===== ФУНКЦИИ =====

def fetch_ohlcv(symbol=config.SYMBOL, timeframe=config.TIMEFRAME, limit=config.LIMIT):
    try:
        ohlcv = bybit.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        logger.info(f"Успешно получены данные {symbol} ({timeframe}), свечей: {len(df)}")
        return df
    except Exception as e:
        logger.error(f"Ошибка получения данных OHLCV для {symbol}: {e}")
        return None

def ema(series, length=config.EMA_LENGTH): #изменил length на length=config.EMA_LENGTH
    return series.ewm(span=length, adjust=False).mean()

def calc_obv(df): # Расчёт OBV + сглаживание длиной OBV_LENGTH
    df['direction'] = np.sign(df['close'].diff()).fillna(0)
    df['obv_raw'] = (df['volume'] * df['direction']).cumsum()
    df['obv'] = ema(df['obv_raw'], config.OBV_LENGTH) if config.OBV_LENGTH > 1 else df['obv_raw']
    return df

def calc_macd(series,
              fast=config.MACD_FAST,
              slow=config.MACD_SLOW, 
              signal=config.MACD_SIGNAL
              ):
    macd_line = ema(series, fast) - ema(series, slow)
    signal_line = ema(macd_line, signal)
    return macd_line, signal_line

def analyze_market(df, symbol=config.SYMBOL):
    logger.info(f"Начат анализ рынка для {symbol}...")
    #logging.info(f"Текущая позиция: {current_pos}")
    # Вычисление сигнала
    macd_line, signal_line = calc_macd(df['close'])
    last_macd, last_signal = macd_line.iloc[-1], signal_line.iloc[-1]
    
    signal = None
    if last_macd > last_signal:
        signal = 'LONG'
        logging.info(f"Сигнал на ЛОНГ.")
    elif last_macd < last_signal:
        signal = 'SHORT'
        logging.info(f"Сигнал на ШОРТ.")
    logger.info(f"Анализ завершен. Текущий сигнал: {signal if signal else 'НЕЙТРАЛЬНО'}")
    return signal

# Здесь логика создания ордера через ccxt (bybit.create_market_order и т.д.)
def get_position_side():
    """
    Определяем, есть ли открытая позиция по BTCUSDT.
    Возвращает: 'long', 'short' или None
    """
    try:
        positions = bybit.fetch_positions([config.SYMBOL])
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
        if p.get('symbol') == config.SYMBOL:
            # Используем .get() с дефолтным значением 0
            size = float(p.get('contracts') or 0)
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
            symbol=config.SYMBOL,
            type='market',
            side=order_side,
            amount=config.ORDER_AMOUNT
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

        logging.info(f"Открываю {direction} позицию ({side}) по рынку, {config.ORDER_AMOUNT} BTC...")
        bybit.create_order(
            symbol=config.SYMBOL,
            type='market',
            side=side,
            amount=config.ORDER_AMOUNT
        )
        logging.info(f"Ордер на открытие отправлен.")
        logging.info(f"ОТКРЫТА ПОЗИЦИЯ: {direction.upper()} | Символ: {config.SYMBOL} | Объем: {config.ORDER_AMOUNT}")
    except Exception as e:
        logging.info(f"Ошибка при открытии позиции: {e}")
        logging.error(f"Ошибка при открытии позиции: {e}")
def run_bot_once():
    symbol = config.SYMBOL # Берем символ из конфига
    trade_amount = config.ORDER_AMOUNT # Объем в BTC (можно вынести в config)
    
    df = fetch_ohlcv(symbol)
    if df is not None:
        # Расчет индикаторов
        df = calc_obv(df)
        
        # Получение сигнала
        signal = analyze_market(df, symbol)

        if signal == 'LONG':
            open_position('long')
        elif signal == 'SHORT':
            open_position('short')
    else:
        logger.warning("Пропуск цикла: не удалось получить данные.")

if __name__ == "__main__":
    while True:
        try:
            run_bot_once()
        except Exception as e:
            logging.error(f"Глобальная ошибка в цикле: {e}")
        time.sleep(60)
