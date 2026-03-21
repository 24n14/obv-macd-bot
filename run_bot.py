import logging
import asyncio
import ccxt.pro as ccxt
import pandas as pd
import numpy as np
import requests
#import time
#from typing import Literal
import config
from info_in_telegram import TelegramNotifier

#====Импортируем все настройки из нашего файла config.py====
proxy_settings = {
    'host': config.PROXY_HOST,
    'port': config.PROXY_PORT,
    'user': config.PROXY_USER,
    'password': config.PROXY_PASS
}
notifier = TelegramNotifier(config.TG_TOKEN,
                            config.TG_CHAT_ID,
                            proxy_data=proxy_settings if config.USE_PROXY else None)
#==== Настройка логирования====
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [%(name)s] - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("bot_history.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
    )
logger = logging.getLogger(__name__)
logger.info("Бот запущен и готов к работе.")

#<===ПОДКЛЮЧЕНИЕ К ПРОКСИ===>
proxy_url = f"http://{config.PROXY_USER}:{config.PROXY_PASS}@{config.PROXY_HOST}:{config.PROXY_PORT}"
# Определяем конфиг прокси (если выключено — будет None)
proxies_config = {
    'http': proxy_url,
    'https': proxy_url,
} if config.USE_PROXY else None
# ===== ПОДКЛЮЧЕНИЕ К BYBIT =====
test_ip = requests.get('https://api.ipify.org', proxies={'https': proxy_url}).text
logger.info(f"Внешний IP через прокси: {test_ip}")
# 1. Создаем объект (это всё еще синхронная операция, в интернет не идет)
bybit = ccxt.bybit({
    'apiKey': config.API_KEY,
    'secret': config.SECRET_KEY,
    'enableRateLimit': True,
    'proxies': proxies_config,
    'options': {
        'defaultType': 'linear',  # Указываем тип контрактов (USDT-бессрочные)
        'recvWindow': 5000        # Окно задержки для безопасности
    }
})
if proxies_config:
    logger.info("Работа через прокси включена.")
else:
    logger.info("Работа напрямую (без прокси).")
# 2. Включаем демо-режим по рекомендации техподдержки
if config.ENABLE_DEMO:
    bybit.enable_demo_trading(True)
    logger.info("Режим Demo-торговли Bybit активирован.")

# 3. Твоя важная строчка (Явное подтверждение типа рынка)
bybit.options['defaultType'] = 'linear' 

# Профессорская заметка:
# Теперь любая команда к этому объекту (например, fetch_balance) 
# ДОЛЖНА выполняться внутри асинхронной функции.

# ========== ЗАПРОС БАЛАНСА ==========
async def get_detailed_balance():
    try:
        balance = await bybit.fetch_balance()
        
        # Свободные средства (для новых сделок)
        free_usdt = balance['free'].get('USDT', 0)
        
        # Общий капитал (ваша "стоимость" на бирже)
        total_usdt = balance['total'].get('USDT', 0)
        
        # Запасной вариант для специфики Bybit (Unified Account)
        if total_usdt == 0:
            try:
                # На Unified аккаунтах смотрим equity
                coin_data = balance['info']['result']['list'][0]['coin'][0]
                total_usdt = float(coin_data['equity'])
                free_usdt = float(coin_data['availableToWithdraw']) # или walletBalance
            except:
                pass

        logger.info(f"Баланс: Свободно {free_usdt} USDT | Всего {total_usdt} USDT")
        
        return {
            'free': free_usdt,
            'total': total_usdt
        }

    except Exception as e:
        logger.error(f"Ошибка баланса: {e}")
        return {'free': 0, 'total': 0}


# ===== Индикаторы =====

# 1. СЕТЕВАЯ ЧАСТЬ: Теперь асинхронная
async def fetch_ohlcv_async(symbol=config.SYMBOL, timeframe=config.TIMEFRAME, limit=config.LIMIT):
    try:
        # Ждем данные от биржи через await
        ohlcv = await bybit.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        
        logger.info(f"Успешно получены данные {symbol} ({timeframe}), свечей: {len(df)}")
        return df
    except Exception as e:
        logger.error(f"Ошибка получения данных OHLCV для {symbol}: {e}")
        return None

# 2. МАТЕМАТИЧЕСКАЯ ЧАСТЬ: Оставляем обычными функциями
def ema(series, length):
    return series.ewm(span=length, adjust=False).mean()

def calculate_indicators(df):
    """Объединяем расчеты в один блок для удобства"""
    try:
        # Расчет EMA для MACD
        df['macd_line'], df['signal_line'] = calc_macd(df['close'])
        
        # Расчет OBV
        df = calc_obv(df)
        
        return df
    except Exception as e:
        logger.error(f"Ошибка при расчете индикаторов: {e}")
        return df

def calc_obv(df):
    # Твоя логика OBV (быстрая, расчет в памяти)
    df['direction'] = np.sign(df['close'].diff()).fillna(0)
    df['obv_raw'] = (df['volume'] * df['direction']).cumsum()
    df['obv'] = ema(df['obv_raw'], config.OBV_LENGTH) if config.OBV_LENGTH > 1 else df['obv_raw']
    return df

def calc_macd(series, fast=config.MACD_FAST, slow=config.MACD_SLOW, signal=config.MACD_SIGNAL):
    macd_line = ema(series, fast) - ema(series, slow)
    signal_line = ema(macd_line, signal)
    return macd_line, signal_line



def analyze_market(df, symbol=config.SYMBOL):
    """
    Синхронная функция анализа. Принимает DataFrame с уже рассчитанными индикаторами.
    """
    if df is None or len(df) < 2:
        logger.warning(f"Недостаточно данных для анализа {symbol}")
        return None

    # Берем две последние свечи для проверки пересечения (Crossover)
    last_row = df.iloc[-1]      # Текущая (незакрытая или только что закрытая)
    prev_row = df.iloc[-2]      # Предыдущая закрытая

    curr_macd, curr_signal = last_row['macd_line'], last_row['signal_line']
    prev_macd, prev_signal = prev_row['macd_line'], prev_row['signal_line']

    signal = None

    # ЛОГИКА: Ищем именно МОМЕНТ пересечения
    # Если сейчас MACD выше, а раньше был ниже — это точка входа
    if curr_macd > curr_signal and prev_macd <= prev_signal:
        signal = 'LONG'
        logger.info(f" СИГНАЛ: Золотое пересечение MACD на {symbol}. Входим в ЛОНГ.")
    
    elif curr_macd < curr_signal and prev_macd >= prev_signal:
        signal = 'SHORT'
        logger.info(f" СИГНАЛ: Смертельное пересечение MACD на {symbol}. Входим в ШОРТ.")
    
    # Если пересечения нет, но мы просто "выше" или "ниже" — signal останется None
    return signal


#<===Работа с позициями===>

async def get_active_position():
    """
    Возвращает словарь с данными позиции или None.
    Это асинхронный 'Источник истины'.
    """
    try:
        # Ждем ответа асинхронно
        positions = await bybit.fetch_positions([config.SYMBOL])
        
        for p in positions:
            # У Bybit в CCXT поле 'contracts' или 'size' показывает объем
            size = float(p.get('contracts', 0))
            if p.get('symbol') == config.SYMBOL and size > 0:
                return p # Возвращаем весь объект позиции
        return None
    except Exception as e:
        logger.error(f"Ошибка при запросе позиций: {e}")
        return None

async def close_position(current_pos):
    """
    Закрытие позиции. Принимает объект позиции, чтобы знать ТОЧНЫЙ объем.
    """
    if not current_pos:
        logger.info("Нет открытой позиции для закрытия.")
        return

    try:
        side = current_pos['side'] # 'long' или 'short'
        amount = current_pos['contracts'] # Закрываем ВЕСЬ объем, что есть
        
        # Инвертируем сторону для закрытия
        order_side = 'sell' if side == 'long' else 'buy'

        logger.info(f"Закрываю {side} позицию объемом {amount}...")
        
        # Асинхронное создание ордера
        order = await bybit.create_order(
            symbol=config.SYMBOL,
            type='market',
            side=order_side,
            amount=amount
        )
        # ОТПРАВЛЯЕМ УВЕДОМЛЕНИЕ
        msg = f"<b>ПОЗИЦИЯ ЗАКРЫТА</b>\nСимвол: {config.SYMBOL}"
        await notifier.send_message(msg)
        
    except Exception as e:
        await notifier.send_message(f"Ошибка при закрытии: {e}")

        logger.info(f"Позиция закрыта. ID ордера: {order['id']}")
    except Exception as e:
        logger.error(f"Ошибка при закрытии позиции: {e}")

async def open_position(direction):
    """
    Открытие позиции асинхронно.
    """
    try:
        side = 'buy' if direction == 'long' else 'sell'
        
        logger.info(f"Открываем {direction.upper()} на {config.ORDER_AMOUNT}...")
        
        order = await bybit.create_order(
            symbol=config.SYMBOL,
            type='market',
            side=side,
            amount=config.ORDER_AMOUNT
        )
        # ОТПРАВЛЯЕМ УВЕДОМЛЕНИЕ
        msg = (f"<b>ОТКРЫТА ПОЗИЦИЯ</b>\n"
               f"Направление: {direction.upper()}\n"
               f"Инструмент: {config.SYMBOL}\n"
               f"Объем: {config.ORDER_AMOUNT} BTC")
        await notifier.send_message(msg)
    except Exception as e:
        await notifier.send_message(f"Ошибка открытия позиции: {e}")

        logger.info(f"Ордер исполнен. Открыт {direction.upper()}")
    except Exception as e:
        logger.error(f"Ошибка открытия позиции: {e}")


async def run_bot_cycle():
    """
    Один цикл работы асинхронного бота.
    """
    symbol = config.SYMBOL
    
    # 1. ШАГ: Проверяем, что происходит на бирже (Источник истины)
    # Мы делаем это ПЕРВЫМ делом, чтобы знать, в позиции мы или нет
    current_pos = await get_active_position()
    
    # 2. ШАГ: Получаем данные и считаем индикаторы
    df = await fetch_ohlcv_async(symbol, limit=200) # Оптимизировали до 200
    if df is None:
        logger.warning("Пропуск цикла: данные OHLCV не получены.")
        return

    df = calculate_indicators(df) # Математика (синхронно)
    
    # 3. ШАГ: Анализ рынка
    signal = analyze_market(df, symbol) # Напоминаю, там теперь поиск ПЕРЕСЕЧЕНИЯ

    # 4. ШАГ: Исполнение (Логика управления позицией)
    
    # СЛУЧАЙ А: Мы вне рынка (позиции нет)
    if current_pos is None:
        if signal == 'LONG':
            await open_position('long')
        elif signal == 'SHORT':
            await open_position('short')
        else:
            logger.info("Сигнала нет, ждем...")

    # СЛУЧАЙ Б: Мы уже в ЛОНГЕ
    elif current_pos['side'] == 'long':
        if signal == 'SHORT': # Сигнал сменился — переворачиваемся
            logger.info("Сигнал сменился на SHORT. Закрываем LONG.")
            await close_position(current_pos)
            await open_position('short')
        else:
            logger.info("Держим LONG, условий для выхода нет.")

    # СЛУЧАЙ В: Мы уже в ШОРТЕ
    elif current_pos['side'] == 'short':
        if signal == 'LONG':
            logger.info("Сигнал сменился на LONG. Закрываем SHORT.")
            await close_position(current_pos)
            await open_position('long')
        else:
            logger.info("Держим SHORT, условий для выхода нет.")

async def main():
    """Главный вход в программу"""
    logger.info("Запуск основного торгового цикла...")

    # ПРОВЕРКА СВЯЗИ С TELEGRAM
    try:
        startup_msg = (
            "🤖 <b>Биткоин-бот запущен!</b>\n"
            f"Ожидаю сигналов по {config.SYMBOL}\n"
            "Связь с биржей и уведомлениями установлена."
        )
        await notifier.send_message(startup_msg)
    except Exception as e:
        logger.error(f"Не удалось отправить стартовое сообщение в TG: {e}")

    try:
        while True:
            await run_bot_cycle()
            # Ждем начала следующей минуты или фиксированное время
            # Для 1m таймфрейма лучше ждать секунд 10-30 между проверками
            await asyncio.sleep(30) 
    except Exception as e:
        error_msg = f"Критическая ошибка в main: {e}"
        logger.error(f"Критическая ошибка в main: {e}")
    finally:
        await bybit.close() # Закрываем сессию при выходе

if __name__ == "__main__":
    try:
        # Запускаем событийный цикл и передаем ему нашу главную функцию
        asyncio.run(main())
    except KeyboardInterrupt:
        # Красиво ловим Ctrl+C, чтобы бот не плевался ошибками в консоль
        logger.info("Бот остановлен пользователем. Удачного профита!")
    except Exception as e:
        logger.critical(f"Бот упал с ошибкой: {e}")


