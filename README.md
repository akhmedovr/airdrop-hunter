# 🤖 Airdrop Hunter

Мультивалютный бот-охотник за аирдропами.
Автоматически сканирует рынок, находит перспективные проекты, выполняет задания (свапы, бриджи, квесты) и управляет несколькими кошельками.

## 🎯 Что делает

- **Сканер** — находит аирдропы через DeFiLlama (проекты на Polygon без токена, с активным TVL)
- **Исполнитель** — автоматически выполняет задания через Playwright *(в разработке)*
- **Менеджер кошельков** — управляет несколькими аккаунтами с шифрованием ключей
- **Уведомления** — присылает отчёты в Telegram
- **Telegram-бот** — принимает команды (`/status`, `/scan`, `/wallets`)

## 🛠 Технологии

| Стек | Назначение |
|---|---|
| Python 3.11+ | Язык |
| web3.py | Работа с блокчейном |
| Playwright | Автоматизация браузера |
| SQLAlchemy | База данных |
| APScheduler | Планировщик задач |
| loguru | Логирование |
| pydantic | Валидация данных |
| python-telegram-bot | Telegram-бот |
| cryptography | Шифрование приватных ключей |
| httpx + tenacity | HTTP-запросы с retry |

## 📁 Структура

```
src/
├── core/                       — ядро
│   ├── config.py               — настройки из .env
│   ├── logger.py               — логирование
│   ├── database.py             — SQLAlchemy модели
│   ├── http.py                 — HTTP-клиент с retry
│   ├── rpc.py                  — Web3 с fallback RPC
│   ├── notifier.py             — Telegram-уведомления
│   └── telegram_bot.py         — приём команд от владельца
├── modules/
│   ├── wallets/                — управление кошельками
│   │   ├── manager.py          — генерация/импорт/сохранение
│   │   └── security.py         — Fernet-шифрование ключей
│   ├── scanner/                — поиск аирдропов
│   │   └── defillama.py        — сканер DeFiLlama
│   └── executor/               — выполнение заданий *(TODO)*
├── services/                   — интеграции с площадками *(TODO)*
└── main.py                     — тестовая точка входа

data/                           — БД и логи
logs/                           — логи PM2
ecosystem.config.js             — конфиг PM2
```

## 🚀 Установка

### Шаг 1. Клонировать репозиторий

```
git clone https://github.com/akhmedovr/airdrop-hunter.git
cd airdrop-hunter
```

### Шаг 2. Создать виртуальное окружение

```
python3 -m venv venv
source venv/bin/activate
```

### Шаг 3. Установить зависимости

```
pip install -r requirements.txt
playwright install chromium
playwright install-deps chromium
```

### Шаг 4. Настроить окружение

```
cp .env.example .env
nano .env
```

Заполнить обязательные переменные (см. ниже).

### Шаг 5. Запустить бота

**Разово (для теста):**
```
python -m src.core.telegram_bot
```

**Через PM2 (production, в фоне):**
```
pm2 start ecosystem.config.js
pm2 save
pm2 startup
```

### Шаг 6. Управлять ботом через Telegram

```
/ping     — проверить, что бот жив
/help     — список команд
/status   — состояние системы (RPC, кошелёк, uptime)
/wallets  — список кошельков с балансами
/scan     — запустить сканер DeFiLlama
```

## 🔐 Обязательные переменные `.env`

```env
# Telegram
TELEGRAM_BOT_TOKEN=   # токен от @BotFather
TELEGRAM_CHAT_ID=     # твой chat_id (узнать у @userinfobot)

# База данных
DATABASE_URL=sqlite:///./data/airdrop.db

# RPC
POLYGON_RPC_URL=https://polygon-bor-rpc.publicnode.com

# Шифрование
WALLET_ENCRYPTION_KEY=   # см. ниже
```

### Как сгенерировать `WALLET_ENCRYPTION_KEY`

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Скопируй результат в `.env`. **Никогда** не коммить его в git и не показывать никому.

## 🔒 Безопасность

- `.env` не коммитится в git — там секреты
- **Приватные ключи кошельков хранятся в SQLite в зашифрованном виде (Fernet)**
- **Ключ шифрования — только в `.env` (`WALLET_ENCRYPTION_KEY`)**
- Если кто-то получит и `data/airdrop.db`, и `WALLET_ENCRYPTION_KEY` — он расшифрует все кошельки. **Никогда** не храни их рядом.
- Используй отдельные кошельки для тестов и реальных денег
- Не заводи больше денег, чем готов потерять

## 📊 Логи

- **Loguru**: `logs/airdrop.log` с ротацией
- **PM2**: `logs/pm2-out.log`, `logs/pm2-err.log`
- **Telegram**: важные события дублируются в личку

## 📜 Лицензия

MIT
