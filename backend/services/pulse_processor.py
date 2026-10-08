"""Digital Signal Processing for camera pulse estimation using green-channel PPG time series.

Pure NumPy implementation. Never fabricates measurements.
"""

from typing import List, Tuple, Dict, Any, Optional
import numpy as np
from fastapi import HTTPException, status
from backend.config import (
    PULSE_MIN_SECONDS,
    PULSE_MIN_FPS,
    PULSE_SAMPLING_RATE_HZ,
    PULSE_DETREND_WINDOW_SECONDS,
    PULSE_FREQ_MIN_HZ,
    PULSE_FREQ_MAX_HZ,
    PULSE_MIN_QUALITY,
    PULSE_MIN_BPM,
    PULSE_MAX_BPM,
    PULSE_MAX_ESTIMATE_DIFF_BPM,
    PULSE_MAX_SAMPLES,
    PULSE_DROP_INITIAL_SECONDS,
)


def process_pulse_series(
    timestamps_ms: List[float],
    green_values: List[float],
) -> Tuple[float, float, float]:
    """Process green-channel PPG time series.
    Returns: (bpm, duration_seconds, signal_quality)
    Raises HTTPException(422) if signal is invalid or rejected.
    """
    if len(timestamps_ms) != len(green_values):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "sample_mismatch", "message": "Timestamps and green values count mismatch."},
        )

    if len(timestamps_ms) > PULSE_MAX_SAMPLES:
        timestamps_ms = timestamps_ms[:PULSE_MAX_SAMPLES]
        green_values = green_values[:PULSE_MAX_SAMPLES]

    if len(timestamps_ms) < 30:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "insufficient_samples",
                "message": "Measurement rejected. Try better lighting and keep your finger still.",
            },
        )

    ts = np.array(timestamps_ms, dtype=np.float64) / 1000.0  # Convert to seconds
    ts = ts - ts[0]
    green = np.array(green_values, dtype=np.float64)

    total_duration = float(ts[-1] - ts[0])

    # 1. Usable duration check
    if total_duration < PULSE_MIN_SECONDS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "recording_too_short",
                "message": f"Measurement rejected. Need at least {int(PULSE_MIN_SECONDS)}s of steady recording.",
            },
        )

    # Check FPS
    intervals = np.diff(ts)
    valid_intervals = intervals[intervals > 0]
    if len(valid_intervals) < 10:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "bad_timestamps", "message": "Measurement rejected. Inconsistent frame timing."},
        )

    median_fps = 1.0 / np.median(valid_intervals)
    if median_fps < PULSE_MIN_FPS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "fps_too_low",
                "message": f"Measurement rejected. Frame rate too low ({median_fps:.1f} fps; need at least {int(PULSE_MIN_FPS)} fps).",
            },
        )

    # Drop initial settling seconds (default 3.0s)
    mask = ts >= PULSE_DROP_INITIAL_SECONDS
    if np.sum(mask) < 30:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "insufficient_settled_data", "message": "Measurement rejected. Not enough settled data."},
        )

    ts_settled = ts[mask] - ts[mask][0]
    green_settled = green[mask]
    usable_duration = float(ts_settled[-1] - ts_settled[0])

    if usable_duration < (PULSE_MIN_SECONDS - PULSE_DROP_INITIAL_SECONDS):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "usable_duration_too_short", "message": "Measurement rejected. Insufficient steady capture."},
        )

    # 2. Resample to uniform 30 Hz
    fs = PULSE_SAMPLING_RATE_HZ
    num_uniform_points = int(usable_duration * fs)
    if num_uniform_points < 100:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "resample_failed", "message": "Measurement rejected. Insufficient points after resampling."},
        )

    uniform_t = np.linspace(0, usable_duration, num_uniform_points, endpoint=False)
    sort_idx = np.argsort(ts_settled)
    ts_sorted = ts_settled[sort_idx]
    green_sorted = green_settled[sort_idx]
    unique_idx = np.where(np.diff(np.concatenate(([-1.0], ts_sorted))) > 1e-5)[0]
    ts_clean = ts_sorted[unique_idx]
    green_clean = green_sorted[unique_idx]

    sig_uniform = np.interp(uniform_t, ts_clean, green_clean)

    # Check for flat signal (zero variance)
    sig_std = float(np.std(sig_uniform))
    if sig_std < 1e-4:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "flat_signal", "message": "Measurement rejected. No pulse variation detected."},
        )

    # 3. Detrend: subtract moving average (~1.5s window) with valid mode to avoid edge distortion
    window_pts = max(3, int(PULSE_DETREND_WINDOW_SECONDS * fs))
    if window_pts % 2 == 0:
        window_pts += 1
    kernel = np.ones(window_pts) / window_pts
    trend = np.convolve(sig_uniform, kernel, mode="valid")
    half_w = window_pts // 2
    detrended = sig_uniform[half_w : half_w + len(trend)] - trend

    detrend_std = float(np.std(detrended))
    if detrend_std < 1e-6:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "low_variance", "message": "Measurement rejected. Insufficient signal amplitude."},
        )
    detrended = detrended / detrend_std

    # Apply Hann window to eliminate spectral leakage
    n_fft = len(detrended)
    windowed = detrended * np.hanning(n_fft)

    # 4. FFT & Band-limiting (0.7 Hz - 3.0 Hz, approx 42 - 180 BPM)
    freqs = np.fft.rfftfreq(n_fft, d=1.0 / fs)
    fft_vals = np.fft.rfft(windowed)
    psd = np.abs(fft_vals) ** 2

    # In-band mask
    in_band = (freqs >= PULSE_FREQ_MIN_HZ) & (freqs <= PULSE_FREQ_MAX_HZ)
    if not np.any(in_band):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "dsp_error", "message": "Measurement rejected. Frequency range error."},
        )

    in_band_psd = psd.copy()
    in_band_psd[~in_band] = 0.0

    peak_idx = int(np.argmax(in_band_psd))
    peak_freq = freqs[peak_idx]

    # Parabolic interpolation on peak for sub-bin precision
    if 0 < peak_idx < len(psd) - 1 and psd[peak_idx - 1] > 0 and psd[peak_idx + 1] > 0:
        alpha = float(psd[peak_idx - 1])
        beta = float(psd[peak_idx])
        gamma = float(psd[peak_idx + 1])
        denom = 2 * (alpha - 2 * beta + gamma)
        if abs(denom) > 1e-8:
            delta = (alpha - gamma) / denom
            if abs(delta) < 1.0:
                df = freqs[1] - freqs[0]
                peak_freq = peak_freq + delta * df

    bpm_fft = float(peak_freq * 60.0)

    # 5. Time-domain peak interval estimate via in-band filtered signal
    filtered_fft = fft_vals.copy()
    filtered_fft[~in_band] = 0.0
    filtered_sig = np.fft.irfft(filtered_fft, n=n_fft)

    min_distance = int((fs / PULSE_FREQ_MAX_HZ) * 0.7)
    peak_indices = []
    last_peak = -min_distance
    for i in range(1, len(filtered_sig) - 1):
        if filtered_sig[i] > filtered_sig[i - 1] and filtered_sig[i] > filtered_sig[i + 1] and filtered_sig[i] > 0:
            if i - last_peak >= min_distance:
                peak_indices.append(i)
                last_peak = i

    bpm_peaks = None
    if len(peak_indices) >= 5:
        intervals_sec = np.diff(peak_indices) / fs
        valid_intervals = intervals_sec[
            (intervals_sec >= 1.0 / PULSE_FREQ_MAX_HZ) & (intervals_sec <= 1.0 / PULSE_FREQ_MIN_HZ)
        ]
        if len(valid_intervals) >= 4:
            median_interval = float(np.median(valid_intervals))
            if median_interval > 0:
                bpm_peaks = 60.0 / median_interval

    if bpm_peaks is None:
        bpm_peaks = bpm_fft

    # 6. Quality Score Computation
    # (a) Spectral SNR: peak power in +/- 0.15 Hz vs total in-band power
    peak_band = (freqs >= (peak_freq - 0.15)) & (freqs <= (peak_freq + 0.15))
    peak_power = float(np.sum(psd[peak_band]))
    total_in_band_power = float(np.sum(psd[in_band]))
    spectral_snr = (peak_power / total_in_band_power) if total_in_band_power > 0 else 0.0
    spectral_snr = min(max(spectral_snr, 0.0), 1.0)

    # (b) Agreement score: agreement within 5 BPM gets high score
    bpm_diff = abs(bpm_fft - bpm_peaks)
    agreement_score = max(0.0, 1.0 - (bpm_diff / 10.0))

    # (c) Amplitude stability
    chunk_size = int(len(filtered_sig) / 4)
    if chunk_size > 10:
        chunk_stds = [np.std(filtered_sig[k * chunk_size : (k + 1) * chunk_size]) for k in range(4)]
        std_cv = float(np.std(chunk_stds) / (np.mean(chunk_stds) + 1e-6))
        amplitude_stability = max(0.0, min(1.0, 1.0 - std_cv))
    else:
        amplitude_stability = 0.8

    quality = round(0.5 * spectral_snr + 0.3 * agreement_score + 0.2 * amplitude_stability, 2)

    # 7. Acceptance criteria
    final_bpm = round((bpm_fft + bpm_peaks) / 2.0, 1)

    if (
        quality < PULSE_MIN_QUALITY
        or not (PULSE_MIN_BPM <= final_bpm <= PULSE_MAX_BPM)
        or bpm_diff > PULSE_MAX_ESTIMATE_DIFF_BPM
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "poor_signal_quality",
                "message": "Measurement rejected. Try better lighting and keep your finger still.",
            },
        )

    return final_bpm, round(total_duration, 1), quality
