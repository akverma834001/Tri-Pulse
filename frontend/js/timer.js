/**
 * Timer manager for guided interventions.
 * Accessible with aria-live, pause/resume, and fast-forward for demo presentation.
 */

export class InterventionTimer {
  constructor(totalSeconds, displayEl, progressFillEl, onTick, onComplete) {
    this.totalSeconds = totalSeconds;
    this.remainingSeconds = totalSeconds;
    this.displayEl = displayEl;
    this.progressFillEl = progressFillEl;
    this.onTick = onTick;
    this.onComplete = onComplete;

    this.intervalId = null;
    this.isPaused = false;
  }

  start() {
    this.updateDisplay();
    this.intervalId = setInterval(() => {
      if (!this.isPaused) {
        this.remainingSeconds--;
        this.updateDisplay();

        if (this.onTick) {
          this.onTick(this.remainingSeconds, this.totalSeconds);
        }

        if (this.remainingSeconds <= 0) {
          this.stop();
          if (this.onComplete) {
            this.onComplete();
          }
        }
      }
    }, 1000);
  }

  pause() {
    this.isPaused = true;
  }

  resume() {
    this.isPaused = false;
  }

  togglePause() {
    this.isPaused = !this.isPaused;
    return this.isPaused;
  }

  fastForward(toSeconds = 3) {
    // Fast forward demo presentation
    if (this.remainingSeconds > toSeconds) {
      this.remainingSeconds = toSeconds;
      this.updateDisplay();
    }
  }

  stop() {
    if (this.intervalId) {
      clearInterval(this.intervalId);
      this.intervalId = null;
    }
  }

  updateDisplay() {
    const mins = Math.floor(this.remainingSeconds / 60);
    const secs = this.remainingSeconds % 60;
    const formatted = `${mins}:${secs < 10 ? '0' : ''}${secs}`;

    if (this.displayEl) {
      this.displayEl.textContent = formatted;
    }

    if (this.progressFillEl) {
      const elapsed = this.totalSeconds - this.remainingSeconds;
      const pct = Math.min(100, (elapsed / this.totalSeconds) * 100);
      this.progressFillEl.style.width = `${pct}%`;
    }
  }
}
