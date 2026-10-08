/**
 * Camera pulse estimation capture module.
 * Feeds green channel means to backend DSP service.
 */

import { api } from './api.js';
import { showToast } from './ui.js';

export class PulseCameraCapture {
  constructor(videoEl, canvasEl, onProgress, onStatus, onComplete, onError) {
    this.videoEl = videoEl;
    this.canvasEl = canvasEl;
    this.ctx = canvasEl.getContext('2d', { willReadFrequently: true });
    this.onProgress = onProgress;
    this.onStatus = onStatus;
    this.onComplete = onComplete;
    this.onError = onError;

    this.stream = null;
    this.track = null;
    this.isRecording = false;
    this.animId = null;

    this.timestamps = [];
    this.greenValues = [];
    this.startTime = null;
    this.durationSec = 30;
  }

  static checkCompatibility() {
    const isSecure = window.isSecureContext || window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1';
    const hasMedia = !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia);
    return {
      compatible: isSecure && hasMedia,
      isSecure,
      hasMedia,
    };
  }

  async start() {
    const compat = PulseCameraCapture.checkCompatibility();
    if (!compat.compatible) {
      throw new Error('Camera access requires HTTPS or localhost and a supported browser.');
    }

    this.timestamps = [];
    this.greenValues = [];
    this.isRecording = false;

    // Prefer environment (rear) camera
    const constraints = {
      video: {
        facingMode: { ideal: 'environment' },
        width: { ideal: 640 },
        height: { ideal: 480 },
      },
      audio: false,
    };

    try {
      this.stream = await navigator.mediaDevices.getUserMedia(constraints);
      this.videoEl.srcObject = this.stream;
      await this.videoEl.play();

      this.track = this.stream.getVideoTracks()[0];

      // Try enabling torch if supported (Android Chrome)
      const capabilities = this.track.getCapabilities ? this.track.getCapabilities() : {};
      if (capabilities.torch) {
        try {
          await this.track.applyConstraints({ advanced: [{ torch: true }] });
        } catch {
          // Torch not allowed or failed, fallback to external light
        }
      }

      this.isRecording = true;
      this.startTime = performance.now();
      this.loop();
    } catch (err) {
      this.stop();
      throw new Error(`Unable to start camera: ${err.message}`);
    }
  }

  loop() {
    if (!this.isRecording) return;

    const now = performance.now();
    const elapsedSec = (now - this.startTime) / 1000.0;
    const progressPct = Math.min(100, Math.round((elapsedSec / this.durationSec) * 100));
    const remainingSec = Math.max(0, Math.ceil(this.durationSec - elapsedSec));

    // Draw video frame to small 32x32 canvas
    const w = this.canvasEl.width || 32;
    const h = this.canvasEl.height || 32;
    this.ctx.drawImage(this.videoEl, 0, 0, w, h);

    const imgData = this.ctx.getImageData(0, 0, w, h);
    const data = imgData.data;

    let sumR = 0;
    let sumG = 0;
    const totalPixels = w * h;

    for (let i = 0; i < data.length; i += 4) {
      sumR += data[i];
      sumG += data[i + 1];
    }

    const meanR = sumR / totalPixels;
    const meanG = sumG / totalPixels;

    // Finger detection heuristic: mean red should be dominant (> 80)
    const isFingerCovering = meanR > 80 && meanR > (meanG * 1.2);

    this.onStatus({
      fingerDetected: isFingerCovering,
      remainingSec,
      progressPct,
      meanR: Math.round(meanR),
      meanG: Math.round(meanG),
    });

    if (isFingerCovering) {
      this.timestamps.push(now);
      this.greenValues.push(meanG);
    }

    this.onProgress(progressPct, remainingSec);

    if (elapsedSec >= this.durationSec) {
      this.finish()
        .then((res) => {
          if (this.onComplete) this.onComplete(res);
        })
        .catch((err) => {
          if (this.onError) this.onError(err);
        });
      return;
    }

    this.animId = requestAnimationFrame(() => this.loop());
  }

  async finish() {
    this.stop();
    if (this.timestamps.length < 150) {
      throw new Error('Not enough steady finger contact recorded. Please try again with firm, gentle placement.');
    }

    const clientUuid = 'cam-' + Date.now() + '-' + Math.random().toString(36).substring(2, 8);
    const res = await api.post('/api/pulse', {
      timestamps_ms: this.timestamps,
      green: this.greenValues,
      client_uuid: clientUuid,
    });
    return res;
  }

  stop() {
    this.isRecording = false;
    if (this.animId) {
      cancelAnimationFrame(this.animId);
      this.animId = null;
    }
    if (this.stream) {
      this.stream.getTracks().forEach(t => t.stop());
      this.stream = null;
    }
  }
}
