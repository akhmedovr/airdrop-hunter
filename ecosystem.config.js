// ecosystem.config.js
// Конфигурация PM2 для Airdrop Hunter.
//
// Запуск:  pm2 start ecosystem.config.js
// Логи:    pm2 logs airdrop-hunter-bot
// Стоп:    pm2 stop airdrop-hunter-bot
// Рестарт: pm2 restart airdrop-hunter-bot
// Статус:  pm2 status

module.exports = {
  apps: [
    {
      name: "airdrop-hunter-bot",
      script: "./venv/bin/python",
      args: "-m src.core.telegram_bot",
      cwd: "/root/airdrop-hunter",

      // Один процесс, без кластеризации (у нас один бот)
      instances: 1,
      exec_mode: "fork",

      // Автозапуск при перезагрузке сервера
      autorestart: true,
      max_restarts: 10,
      min_uptime: "30s",

      // Логи (пишутся в ~/.pm2/logs/)
      output: "./logs/pm2-out.log",
      error: "./logs/pm2-err.log",
      merge_logs: true,
      time: true,

      // Переменные окружения
      env: {
        PYTHONUNBUFFERED: "1",  // не буферизовать stdout Python
        PYTHONDONTWRITEBYTECODE: "1",  // не создавать .pyc файлы
      },

      // Автоперезапуск при изменении файлов (для dev)
      watch: false,
    },
  ],
};
