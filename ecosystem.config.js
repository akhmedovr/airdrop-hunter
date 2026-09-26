// ecosystem.config.js
// PM2 config for Airdrop Hunter

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
      instances: 1,
      exec_mode: "fork",
      autorestart: true,
      max_restarts: 10,
      min_uptime: "30s",
      output: "./logs/pm2-sched-out.log",
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
