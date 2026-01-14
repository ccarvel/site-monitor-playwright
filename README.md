# Site Sentinel Playwright

A custom web application uptime and content monitor built with Python, FastAPI, and Playwright.

## Features
- **Keyword Verification**: Checks page source for specific strings.
- **Full-Page Screenshots**: Captures the entire page length.
- **Device Emulation**: Supports Desktop and Mobile (iPhone) viewports.
- **Discord Notifications**: Real-time alerts via Webhooks.
- **Security**: Basic Authentication for dashboard access.
- **Auto-Cleanup**: Automatically removes screenshots and logs older than 7 days.

## Tech Stack
- **Backend**: FastAPI, SQLAlchemy (SQLite), APScheduler.
- **Browser Automation**: Playwright (Chromium).
- **Deployment**: Docker, Docker Compose.

## Getting Started

1. **Clone the repo**:
   ```bash
   git clone [https://github.com/ccarvel/site-monitor-playwright.git](https://github.com/ccarvel/site-monitor-playwright.git)
   cd site-monitor-playwright
   ```
2. **Create a .env file**
   You can use the ```.env.template``` file to verify what secrets are expected;    
   (**note: uses Discord webhooks for notifications** TK: add documentation for setting this up)  
4. **With Docker Engine or Docker Desktop running**
   ```bash
   docker compose up --build -d
   ```
