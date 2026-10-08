# Project Pulse: Silent Co-Pilot (v2, Hardened)

> **Medical Disclaimer:** Project Pulse is a wellness and behavioral-support tool. It is **not a medical device** and does not diagnose, treat, cure, or prevent any medical condition.

Project Pulse is a private, deterministic behavioral-pattern observer for high-stress professionals. It collects a few consented signals (delivery receipts, resting blood pressure, camera pulse estimates, typing cadence), computes individual baseline deviations, detects lifestyle routines, and suggests one focused micro-action right now.

---

## 1. Core Principles

- **Silence & Non-Intrusiveness:** Minimal nudges (max 3/day, 6h cooldown between repeated types, quiet hours). No pop-ups mid-task.
- **Data Minimization:** No raw camera frames, no typed text, and no raw receipt text are ever stored on disk or in the database. Phone numbers, addresses, and OTPs in receipts are discarded in memory.
- **Eating Care:** No calorie counting, no weight tracking, and no dietary guilt. The pre-order pause explicitly affirms: *"If you're hungry, eating is fine. This is just a pause to check in with yourself."* "Order anyway" is a neutral, normal outcome. Users can disable all food-related nudges at any time in Settings.
- **Explainability:** Transparent rules (Rules A through G). Every insight contains a "Why am I seeing this?" expander listing the exact rule and evidence metrics.
- **Zero-Stub Policy:** All algorithms—NumPy optical photoplethysmography (DSP), deterministic regex receipt parsing, median baseline calculation, circular time averaging, and cooldown learning—are fully implemented and tested.

---

## 2. Architecture & Pipeline

```text
[ CONSENTED SIGNALS ]
  ├── Receipts (Zomato, Swiggy, etc.) -> In-memory Regex Parser -> [Orders Table]
  ├── Blood Pressure (Manual / BT)    -> Precedence Classifier   -> [Blood Pressure Table]
  ├── Camera PPG (Rear camera/Flash)  -> Pure NumPy DSP Filter   -> [Pulse Sessions Table]
  └── Typing Cadence (Neutral Prompt) -> Rhythm Keystrokes Math  -> [Behavior Sessions Table]
                                      │
                                      ▼
                          [ BASELINE ENGINE ]
                          Median of first 5 sessions -> Frozen Baseline
                          Rolling 7-day average -> Current Deviation
                                      │
                                      ▼
                          [ PATTERN ENGINE ]
                          Evaluates Rules A through G (Idempotent Upsert)
                                      │
                                      ▼
                          [ INTERVENTION ENGINE ]
                          Cooldowns, Quiet Hours, Learning & Outcome Feedback
                                      │
                                      ▼
                          [ DASHBOARD & TIMELINE ]
                          Unified Co-Pilot UI (Zero-CDN Static Frontend)
```

---

## 3. Technology Stack

- **Backend:** Python 3.10+, FastAPI, Pydantic v2, SQLAlchemy 2.0, SQLite (WAL mode, Foreign Keys enforced), NumPy (Signal Processing), `bcrypt`, `python-dotenv`, `tzdata`.
- **Frontend:** HTML5, CSS3 Custom Properties (Design System), Vanilla JavaScript (ES modules). Zero external CDN dependencies (works offline after load).
- **Security:** HTTP-only SameSite cookies, CSRF header validation (`X-Pulse-Client: 1`), Content Security Policy (CSP), Permissions-Policy, Rate limiting on login, CSV formula injection neutralization (`'`).
- **Tests:** Pytest, HTTPX TestClient, injectable `Clock`.

---

## 4. Getting Started

### Prerequisites
- Python 3.10 or higher (Python 3.11, 3.12, 3.13 supported).
- Windows, macOS, or Linux.

### Installation

1. **Clone or Navigate to the Repository:**
   ```bash
   cd "c:\Users\abhis\Downloads\IIT ISM\Prototype main\Basics"
   ```

2. **Create and Activate a Virtual Environment:**
   - **Windows:**
     ```cmd
     python -m venv venv
     venv\Scripts\activate
     ```
   - **Linux / macOS:**
     ```bash
     python3 -m venv venv
     source venv/bin/activate
     ```

3. **Install Dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure Environment:**
   Copy `.env.example` to `.env`:
   ```bash
   # Windows
   copy .env.example .env

   # Linux / macOS
   cp .env.example .env
   ```

---

## 5. Running the Application

### One-Command Quickstart

- **Windows:** Double-click or run `run.bat`:
  ```cmd
  run.bat
  ```
- **Linux / macOS:** Execute `run.sh`:
  ```bash
  chmod +x run.sh
  ./run.sh
  ```
- **Manual Command:**
  ```bash
  python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
  ```

Open your browser at **http://127.0.0.1:8000** to access Project Pulse.

---

## 6. Accessing Camera Pulse on a Physical Phone (HTTPS)

Browsers require a **Secure Context (HTTPS or localhost)** to access `navigator.mediaDevices.getUserMedia`. Webcams on laptops generally lack the sensor sensitivity and flash illumination required for transmissive fingertip photoplethysmography (PPG).

To test or use the camera pulse on your smartphone:

### Option A: Local Tunnel (Recommended for Development)
Using [ngrok](https://ngrok.com) or [Cloudflare Tunnels](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/):
```bash
ngrok http 8000
```
Open the generated HTTPS URL on your phone's browser (e.g. Chrome on Android or Safari on iOS).

### Option B: Local SSL Certificate with mkcert
1. Install [mkcert](https://github.com/FiloSottile/mkcert) and run:
   ```bash
   mkcert -install
   mkcert localhost 127.0.0.1 <your-lan-ip>
   ```
2. Run uvicorn with SSL:
   ```bash
   python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --ssl-keyfile localhost+2-key.pem --ssl-certfile localhost+2.pem
   ```
3. Open `https://<your-lan-ip>:8000` on your mobile phone.

### Camera Guidance:
- **Android (Chrome):** When camera starts, Pulse attempts to automatically engage the rear torch flash via `track.applyConstraints({advanced:[{torch:true}]})`.
- **iOS (Safari):** Safari does not expose the torch API to WebRTC. Hold your finger over the rear camera lens while facing a bright, steady ambient light source (such as a desk lamp or flashlight).
- **Laptop / Webcam Fallback:** If camera access is unavailable or unreliable, use the **"Enter pulse manually"** option on the Check-in page.

---

## 7. Interactive One-Click Demo Mode

Project Pulse features a complete, zero-registration **Demo Mode** (`demo@pulse.local`).

1. On `http://127.0.0.1:8000/login.html`, click **"Try 1-Click Demo"**.
2. A persistent warning banner indicates: **DEMO DATA — NOT REAL HEALTH DATA**.
3. All demo data is generated relative to the current timestamp and processed through the **real production pipeline** (raw records -> baseline computation -> pattern rules -> recommendations). No fake insights are injected.

### 7-Step Guided Walkthrough Script
Click the **"Demo Guide"** button in the top demo banner to launch the interactive guide:
1. **Load Demo:** Explains the deterministic 3-week seed.
2. **Pulse Deviation:** Points out the resting pulse elevation (+11% vs baseline 74 BPM).
3. **Combined Routine Insight (Rule G):** Reviews the composite insight card showing 4 late-night orders (circular average 23:41), elevated BP, and slower typing rhythm.
4. **"Why am I seeing this?" Expander:** Click the expander to view the transparent evidence metrics.
5. **Recommended Action:** Click "Take Action" to open the 5-Minute Evening Wind-down.
6. **Fast-Forward Evaluation:** Press **"⏩ Skip ahead (Demo)"** to fast-forward the countdown timer to the final 3 seconds.
7. **Complete & Rate:** Submit completion, rate your post-session state (Calmer), and return to Dashboard to observe the updated completion rate.

To restart the demo at any point, click **"Reset Demo"** in the top banner.

---

## 8. Pattern Engine Rules & Thresholds

All thresholds are named constants defined in `backend/config.py` and overridable via environment variables.

| Rule | Trigger Condition | Severity | Recommended Action |
|---|---|---|---|
| **A** | ≥ 3 late-night orders in 7 days | notice | 5-Minute Evening Wind-down |
| **B** | ≥ 2 different calendar days in 14 days with elevated or higher BP | notice | Monitor trend & consult healthcare professional |
| **C** | ≥ 1 late-night order in 7 days AND typing cadence ≤ −10% vs baseline | info | 4-Minute Guided Breathing |
| **D** | ≥ 1 late-night order in 7 days AND pulse ≥ +8% AND ≥ +5 BPM vs baseline | info | 4-Minute Guided Breathing |
| **E** | Pulse ≥ +8% AND ≥ +5 BPM vs baseline (independent of orders) | info | 4-Minute Guided Breathing |
| **F** | Typing cadence ≤ −10% vs baseline (independent of orders) | info | 4-Minute Guided Breathing |
| **G** | Rule A AND at least one of {D/E, C/F, B} | attention (if ≥2 signals) else notice | 5-Minute Evening Wind-down |

*Circular Time Averaging:* Average late-night order times are calculated using circular trigonometry relative to 18:00 UTC (so times like 23:52 and 00:02 average to ~23:57 rather than midday 11:57).

---

## 9. Blood Pressure Threshold Reference

Thresholds are based on simplified clinical screening guidelines (ACC/AHA cut-offs) for routine wellness self-monitoring:
- **Normal:** Systolic < 130 mmHg AND Diastolic < 80 mmHg.
- **Elevated:** Systolic 130–139 mmHg OR Diastolic 80–89 mmHg.
- **Above Target Range:** Systolic ≥ 140 mmHg OR Diastolic ≥ 90 mmHg.
- **Urgent Attention:** Systolic > 180 mmHg OR Diastolic > 120 mmHg.

*Urgent Safety Action:* Any reading with systolic > 180 or diastolic > 120 immediately presents a blocking emergency dialogue prompting the user to rest and seek urgent emergency medical attention. Relaxation interventions are strictly suppressed during urgent readings.

---

## 10. API Specification

All endpoints communicate via JSON, require the `X-Pulse-Client: 1` CSRF header for state-changing requests, and use HTTP-only session cookies.

### Authentication & Account
- `POST /api/auth/register` — Register (Name, email, password ≥10 chars, 18+ confirmation).
- `POST /api/auth/login` — Session login (rate-limited: 5 attempts / 15 min).
- `POST /api/auth/logout` — Revoke session cookie.
- `GET /api/me` — Current authenticated user profile.
- `POST /api/auth/change-password` — Update password.
- `DELETE /api/account/data` — Permanently purge all health & behavioral data.
- `DELETE /api/account` — Permanently delete entire user account.

### Consent & Settings
- `GET /api/consent` / `PUT /api/consent` — Manage 4 independent consent toggles (`camera`, `behavior`, `order_data`, `health_data`).
- `GET /api/settings` / `PATCH /api/settings` — Update timezone, late-night windows, quiet hours, and food nudges toggle.
- `POST /api/settings/recalibrate` — Recalibrate personal baselines from next 5 sessions.

### Ingestion & Logging
- `POST /api/orders/parse` — Parse raw receipt text in-memory; returns preview with found/not-found badges.
- `POST /api/orders` — Save user-confirmed order (Requires `order_data` consent).
- `GET /api/orders` / `DELETE /api/orders/{id}` — Order records management.
- `POST /api/bp` — Record BP reading (Requires `health_data` consent).
- `GET /api/bp` / `DELETE /api/bp/{id}` — BP records management.
- `POST /api/pulse` — Record camera series or manual pulse (Requires `health_data` and optionally `camera` consent).
- `GET /api/pulse` / `DELETE /api/pulse/{id}` — Pulse records management.
- `GET /api/behavior/prompt` — Retrieve neutral sentence from randomized prompt pool.
- `POST /api/behavior` — Record typing rhythm metrics (Requires `behavior` consent).
- `GET /api/behavior` / `DELETE /api/behavior/{id}` — Typing sessions management.

### Co-Pilot Intelligence & Interventions
- `GET /api/insights` — Current ranked insights.
- `PATCH /api/insights/{id}` — Update insight status (`seen`, `dismissed`) or feedback (`useful`, `not_useful`).
- `GET /api/interventions/recommendation` — Co-pilot recommended micro-action.
- `POST /api/interventions` — Start or suggest intervention.
- `POST /api/interventions/{id}/complete` / `skip` / `dismiss` / `abandon` — State machine transitions.
- `POST /api/interventions/{id}/outcome` — Pre-order delay outcome (`waited`, `ordered_anyway`).
- `POST /api/interventions/{id}/feedback` — Post-intervention feeling rating (`calmer`, `same`, `worse`).
- `GET /api/interventions/stats` — Smoothed completion rate statistics.
- `GET /api/dashboard` — Unified dashboard composite payload.
- `GET /api/timeline` — Paginated event timeline grouped by calendar day.
- `GET /api/export` — Download complete sanitized ZIP archive of CSV tables.
- `POST /api/demo/load` / `POST /api/demo/reset` — Demo sandbox management.
- `GET /api/health` — System status health check.

---

## 11. Admin CLI: Password Reset

To reset an account password locally from the terminal without an email service:
```bash
python -m backend.cli reset-password <user-email>
```
Follow the interactive prompt to enter a secure replacement password.

---

## 12. Running Tests

The test suite validates the entire stack, including DSP filters, regex parser variations, baseline calculations, pattern engine idempotency, safety copy banned phrases, and end-to-end user journeys:

```bash
python -m pytest tests -v
```

---

## 13. Safety & Emergency Support Resources

If you are experiencing severe emotional distress or require crisis intervention:
- **India (Tele-MANAS):** Call toll-free **14416** or **1800-891-4416** (24/7 National Tele Mental Health Programme).
- **India Emergency Medical:** Dial **112** or **102**.
- **United States & Canada:** Dial **988** (Suicide & Crisis Lifeline).
- **United Kingdom:** Dial **111** (NHS Mental Health Services).

---

## 14. Roadmap & Post-MVP Extensions

- **Wearable PPG Integration:** Direct Apple HealthKit and Google Health Connect sync for resting pulse.
- **Bluetooth Upper-Arm BP Sync:** Web Bluetooth API (GATT protocol) for Omron and Beurer monitors.
- **Email Receipt Ingestion:** Consented read-only OAuth integration with Google Workspace / Outlook to ingest delivery receipts without manual pasting.
