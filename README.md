# 👻 InstructureGhost

**InstructureGhost** is a powerful, stealth-enabled AI web dashboard and Chrome extension combo, crafted to interact with Canvas LMS (Instructure) accounts in an efficient, automated, and user-friendly way. It allows you to **extract course data**, **download student submissions**, and **chat with an AI** for assignment help — all through a web dashboard and optionally powered by cookie automation via a Chrome extension.

---

## 🧠 What is InstructureGhost?

This tool was made for students, educational developers, or Canvas automation testers to:

- Instantly grab assignments, due dates, and submission statuses.
- Summarize assignments per quarter into a clean, easy-to-read chart.
- Extract actual student submission files into downloadable folders.
- Chat with an AI that can help understand or summarize workload.
- Optionally connect a Chrome Extension that sends over Canvas session cookies.

---

## 🔧 Components

- `app.py`: The core Flask app that handles all data extraction, AI chat, and file downloads.
- `manifest.json`: The Chrome extension manifest.
- `popup.html`: The extension's user interface (loads the chat view).
- `background.js`: Background service worker that sends cookies to the Flask server.

---

## 🚀 How to Install & Use

### 🖥️ Backend (Web Dashboard)

1. **Clone the Repo**
```bash
git clone https://github.com/listentosmoke/InstructureGhost.git
cd InstructureGhost
```

2. **Install Python Dependencies**
```bash
pip install flask requests groq
```

3. **Configure your settings in `app.py`**
   - Replace `CANVAS_BASE_URL` with your Canvas domain.
   - Replace `GROQ_API_KEY` with your Groq API key (for AI).

4. **Run the server**
```bash
python app.py
```

The server will start on `http://localhost:5000`

---

### 🧩 Chrome Extension Setup

The extension is designed to work with your deployed server to auto-send Canvas cookies.

1. Open **Google Chrome**, go to `chrome://extensions/`.
2. Enable **Developer Mode** (top-right).
3. Click **Load Unpacked**, and select the folder containing:
   - `manifest.json`
   - `popup.html`
   - `background.js`

4. The popup will open the `/chat?ext=1` page in an iframe.

---

## 🌍 Deploying the Site Publicly

To make it work on other devices or online, you'll need to **host your Flask app publicly**. Here's how:

### 🛜 Port Forwarding with Ngrok (Example)
```bash
ngrok http 5000
```

Then Ngrok will give you a public URL like `http://abc123.ngrok.io`

### 🛠 Update These Two Files:

**In `manifest.json`**
```json
"host_permissions": [
  "https://your-canvas-domain.com/*",
  "http://abc123.ngrok.io/*"
]
```

**In `popup.html`**
```html
<iframe id="chatFrame" src="http://abc123.ngrok.io/chat?ext=1"></iframe>
```

Then reload the extension from `chrome://extensions/`.

---

## 🧪 API Endpoints

| Endpoint              | Description                                  |
|----------------------|----------------------------------------------|
| `/`                  | Home dashboard for token entry & summary     |
| `/chat`              | AI chatbot interface                         |
| `/extract`           | Begins extraction of Canvas assignment data  |
| `/submissions`       | Downloads all assignment submission files    |
| `/filter`            | Creates a smart summary chart                |
| `/receive_cookies`   | Endpoint that Chrome extension sends cookies |

---

## ⚠️ Disclaimer

This project is **educational**. Do not deploy on unauthorized systems.
You are responsible for any misuse of this tool. Always get **explicit consent** before interacting with any external system or user data.

---

Crafted with 💻 by [listentosmoke](https://github.com/listentosmoke)

license: MIT, just dont use it for anything bad
