/**
 * Typing rhythm task manager.
 * Counts rhythm metrics (keystrokes, backspaces, pauses) without reading or transmitting typed text.
 */

import { api } from './api.js';

export class TypingTaskManager {
  constructor(inputEl, promptEl, timerEl, onComplete) {
    this.inputEl = inputEl;
    this.promptEl = promptEl;
    this.timerEl = timerEl;
    this.onComplete = onComplete;

    this.keystrokes = 0;
    this.backspaces = 0;
    this.pauseCount = 0;
    this.lastKeyPressTime = null;
    this.startTime = null;
    this.timerInterval = null;
    this.durationSec = 60;
    this.isRunning = false;

    this.bindEvents();
  }

  bindEvents() {
    // Block paste to ensure accurate natural typing rhythm
    this.inputEl.addEventListener('paste', (e) => {
      e.preventDefault();
    });

    this.inputEl.addEventListener('keydown', (e) => {
      if (!this.isRunning) {
        this.startSession();
      }

      const now = performance.now();
      if (this.lastKeyPressTime !== null) {
        const gapSec = (now - this.lastKeyPressTime) / 1000.0;
        if (gapSec >= 2.0) {
          this.pauseCount++;
        }
      }
      this.lastKeyPressTime = now;

      if (e.key === 'Backspace') {
        this.backspaces++;
      } else if (e.key.length === 1) {
        // Printable character
        this.keystrokes++;
      }
    });
  }

  async loadPrompt() {
    const res = await api.get('/api/behavior/prompt');
    this.promptEl.textContent = res.text;
    this.inputEl.value = '';
    this.inputEl.disabled = false;
    this.inputEl.focus();
    this.resetStats();
  }

  resetStats() {
    this.keystrokes = 0;
    this.backspaces = 0;
    this.pauseCount = 0;
    this.lastKeyPressTime = null;
    this.startTime = null;
    this.isRunning = false;
    if (this.timerInterval) {
      clearInterval(this.timerInterval);
      this.timerInterval = null;
    }
    this.timerEl.textContent = '60s';
  }

  startSession() {
    this.isRunning = true;
    this.startTime = performance.now();
    let remaining = this.durationSec;

    this.timerInterval = setInterval(() => {
      remaining--;
      this.timerEl.textContent = `${remaining}s`;

      if (remaining <= 0) {
        this.finishSession();
      }
    }, 1000);
  }

  async finishSession() {
    clearInterval(this.timerInterval);
    this.isRunning = false;
    this.inputEl.disabled = true;

    const actualDurationSec = Math.round((performance.now() - this.startTime) / 1000.0);
    const clientUuid = 'type-' + Date.now() + '-' + Math.random().toString(36).substring(2, 8);

    if (actualDurationSec < 30 || this.keystrokes < 40) {
      this.inputEl.value = '';
      this.inputEl.disabled = false;
      this.resetStats();
      throw new Error(`Typing session too short (${this.keystrokes} keystrokes, ${actualDurationSec}s). A minimum of 40 keystrokes and 30 seconds is required.`);
    }

    const payload = {
      client_uuid: clientUuid,
      duration_seconds: actualDurationSec,
      keystrokes: this.keystrokes,
      backspaces: this.backspaces,
      pause_count: this.pauseCount,
    };

    // Clear typed text from memory and UI immediately
    this.inputEl.value = '';

    try {
      const res = await api.post('/api/behavior', payload);
      this.onComplete(res);
    } catch (err) {
      this.inputEl.disabled = false;
      throw err;
    }
  }
}
