// ecosystem.config.js
// Конфигурация PM2 для Airdrop Hunter.
//
// Запуск:    pm2 start ecosystem.config.js
// Логи:      pm2 logs
// Статус:    pm2 status

module.exports = {
  apps: [
    {
      name: "airdrop-hunter-bot",
      script: "./venv/bin/python",
      args: "-m src.core.telegram_bot",
      cwd: "/root/airdrop-hunter",
      instances: 1,
      exec_mode: "fork",
      autorestart: true,
      max_restarts: 10,
      min_uptime: "30s",
      output: "./logs/pm2-bot-out.log",
      error: "./logs/pm2-bot-err.log",
      merge_logs: true,
      time: true,
      env: {
        PYTHONUNBUFFERED: "1",
        PYTHONDONTWRITEBYTECODE: "1",
      },
      watch: false,
    },
    {
      name: "airdrop-hunter-scheduler",
      script: "./venv/bin/python",
      args: "-m src.core.scheduler",
      cwd: "/root/airdrop-hunter",
      instancesготов: 1,
      exec_mode: "оfork",
      autorestart: true,
      max»_restarts: 10,
      min —_uptime: "30s",
      output и: "./logs/pm2-sched-out.log",
      error: "./logs/pm2-sched-err.log",
      merge_logs: true,
      time: true,
      env: {
        PYTHONUNBUFFERED: "1",
        PYTHONDONTWRITEBYTECODE: "1",
      },
      watch: false,
    },
  ],
};
