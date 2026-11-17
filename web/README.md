# Airdrop Hunter PWA shell

This is the first mobile-first installable PWA shell. It intentionally contains no fake campaign, wallet or reward data.

## Local preview

Serve this directory from an HTTP server at the site root. The UI loads data from same-origin API routes:

- GET /api/health
- GET /api/dashboard
- GET /api/notifications
- GET /api/push/public-key
- POST /api/push/subscribe

Those API routes are not implemented yet. Until the backend is deployed, the UI will correctly show that the server is not connected.

## iPhone

1. Open the deployed HTTPS URL in Safari.
2. Tap Share → Add to Home Screen.
3. Launch the installed app from the Home Screen.
4. Enable push from the Notifications screen after the backend and VAPID keys are configured.

On iOS, Web Push requires an installed Home Screen web app and explicit notification permission. The notification inbox must remain available even if push is disabled.

## Security

- Never place Supabase service-role keys, OpenAI API keys or VAPID private keys in frontend code.
- The browser may receive only the VAPID public key.
- Push subscriptions must be associated with the authenticated owner on the server.
- API routes must require owner authentication and enforce RLS.
