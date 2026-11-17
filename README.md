# 🤖 Airdrop Hunter

Личный помощник для поиска, проверки и учёта Web3-наград. Целевая версия 2.0 — закрытое mobile-first PWA с AI-аналитикой и push-уведомлениями на iPhone.

Текущий репозиторий содержит legacy Python-бота и планировщик. Автоматическое выполнение on-chain транзакций отключено по умолчанию; новая система не должна подписывать или отправлять транзакции без явного подтверждения владельца.

## 🎯 Что делает

- **Сканер** — находит аирдропы через DeFiLlama (проекты на Polygon без токена, с активным TVL)
- **AI-планировщик** — оценивает условия и готовит пошаговые инструкции; действия с аккаунтами и транзакциями требуют участия владельца.
- **Менеджер кошельков** — управляет несколькими аккаунтами с шифрованием ключей
- **Уведомления** — целевой канал: центр уведомлений и Web Push в PWA; legacy Telegram-уведомления выключены по умолчанию.
- **Legacy Telegram-бот** — временный интерфейс старой версии; не является каналом уведомлений новой PWA.
- **Scheduler** — автономно сканирует и мониторит систему по расписанию

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
│   ├── notifier.py             — legacy Telegram-уведомления (выключены по умолчанию)
│   ├── telegram_bot.py         — точка входа бота
│   ├── telegram_wallet_cmds.py — команды управления кошельками
│   └── scheduler.py            — APScheduler
├── modules/
│   ├── wallets/                — управление кошельками
│   │   ├── manager.py          — генерация/импорт/сохранение
│   │   └── security.py         — Fernet-шифрование ключей
│   ├── scanner/                — поиск аирдропов
│   │   └── defillama.py        — сканер DeFiLlama
│   └── executor/               — выполнение заданий (TODO)
├── services/                   — интеграции с площадками (TODO)
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

### Шаг 5. Запустить бота и scheduler

**Разово (для теста):**
```
python -m src.core.telegram_bot
python -m src.core.scheduler
```

**Через PM2 (production, в фоне):**
```
pm2 start ecosystem.config.js
pm2 save
pm2 startup
```

### Шаг 6. Управлять ботом через Telegram

**Система:**
```
/ping     — проверить, что бот жив
/help     — список команд
/status   — состояние системы (RPC, кошелёк, uptime)
```

**Кошельки:**
```
/wallets                        — список всех кошельков с балансами
/create_wallet <метка>          — создать новый farming-кошелёк
/balance <адрес|метка>          — баланс одного кошелька
/rename_wallet <адрес> <метка>  — переименовать кошелёк
```

**Аирдропы:**
```
/scan     — запустить сканер DeFiLlama вручную
```

## ⏰ Автономные задачи (scheduler)

| Задача | Интервал |
|---|---|
| Скан DeFiLlama на новые аирдропы | каждые 6 часов |
| Проверка балансов кошельков | каждые 24 часа |
| Пинг RPC (защита от простоя) | каждый час |

Результаты новой версии должны сохраняться в центре уведомлений PWA; Web Push включается после установки PWA на экран «Домой» и разрешения уведомлений.

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
- Telegram-бот отвечает только владельцу (проверка по `chat_id`)
- Используй отдельные кошельки для тестов и реальных денег
- Не заводи больше денег, чем готов потерять
## 🛡 Правила безопасной автоматизации
- Не обходить KYC, географические ограничения, CAPTCHA, антибот- и anti-Sybil-проверки.
- Не использовать прокси или несколько аккаунтов для обхода ограничений платформ.
- Не хранить seed-фразы и приватные ключи в PWA или передавать их AI-агенту.
- Не подписывать и не отправлять on-chain транзакции без явного подтверждения владельца.
- Проверять eligibility, комиссии, ликвидность, сроки и фактическую возможность claim до оценки награды.
## 📊 Логи

- **Loguru**: `logs/airdrop.log` с ротацией
- **PM2 (bot)**: `logs/pm2-bot-out.log`, `logs/pm2-bot-err.log`
- **PM2 (scheduler)**: `logs/pm2-sched-out.log`, `logs/pm2-sched-err.log`
- **Telegram**: важные события дублируются в личку

## 📜 Лицензия

MIT
