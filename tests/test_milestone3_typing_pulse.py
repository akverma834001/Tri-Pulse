"""Tests for Milestone 3: Pulse Signal DSP and Typing Rhythm Behavior Analysis."""

import numpy as np
import pytest
from fastapi import HTTPException
from backend.services.pulse_processor import process_pulse_series
from backend.services.behavior_engine import evaluate_typing_session, get_typing_prompt
from backend.models import PulseSession, BehaviorSession


def generate_synthetic_ppg(bpm: float = 72.0, duration_sec: float = 30.0, fps: float = 30.0, noise_amp: float = 0.05):
    """Generate a clean synthetic PPG signal with controllable heart rate and mild noise."""
    t = np.linspace(0, duration_sec, int(duration_sec * fps), endpoint=False)
    freq = bpm / 60.0
    # PPG model: fundamental + 2nd harmonic (dicrotic notch) + baseline drift
    sig = np.sin(2 * np.pi * freq * t) + 0.3 * np.sin(4 * np.pi * freq * t) + 0.1 * np.sin(2 * np.pi * 0.1 * t)
    # Add Gaussian noise
    np.random.seed(42)
    noise = np.random.normal(0, noise_amp, len(t))
    signal_with_noise = sig + noise + 100.0  # mean around 100
    timestamps_ms = (t * 1000.0).tolist()
    return timestamps_ms, signal_with_noise.tolist()


def test_synthetic_pulse_recovery():
    """Verify that synthetic 72 BPM waveform with noise is recovered within +-3 BPM."""
    ts, green = generate_synthetic_ppg(bpm=72.0, duration_sec=30.0, fps=30.0, noise_amp=0.03)
    measured_bpm, duration, quality = process_pulse_series(ts, green)
    assert abs(measured_bpm - 72.0) <= 3.0, f"Expected ~72 BPM, got {measured_bpm}"
    assert quality >= 0.6
    assert duration >= 20.0


def test_pulse_rejections():
    """Verify noise, flat signals, low fps, and short sessions are rejected with 422."""
    # 1. Pure random noise
    np.random.seed(99)
    ts_noise = (np.linspace(0, 30, 900) * 1000.0).tolist()
    green_noise = np.random.uniform(50, 150, 900).tolist()
    with pytest.raises(HTTPException) as exc:
        process_pulse_series(ts_noise, green_noise)
    assert exc.value.status_code == 422

    # 2. Flat signal
    ts_flat = (np.linspace(0, 30, 900) * 1000.0).tolist()
    green_flat = [128.0] * 900
    with pytest.raises(HTTPException) as exc:
        process_pulse_series(ts_flat, green_flat)
    assert exc.value.status_code == 422

    # 3. Too short (<20s)
    ts_short, green_short = generate_synthetic_ppg(duration_sec=15.0)
    with pytest.raises(HTTPException) as exc:
        process_pulse_series(ts_short, green_short)
    assert exc.value.status_code == 422

    # 4. Low fps (<15 fps)
    ts_slow, green_slow = generate_synthetic_ppg(fps=10.0)
    with pytest.raises(HTTPException) as exc:
        process_pulse_series(ts_slow, green_slow)
    assert exc.value.status_code == 422


def test_typing_metric_calculations():
    """Verify typing metrics derivation and bounds."""
    # 60 seconds (1 minute), 250 keystrokes, 10 backspaces -> net 240 / 5 = 48 WPM
    wpm, err_rate, pause_freq = evaluate_typing_session(
        duration_seconds=60.0,
        keystrokes=250,
        backspaces=10,
        pause_count=4,
    )
    assert wpm == 48.0
    assert err_rate == 0.04
    assert pause_freq == 4.0

    # Short session (<30s or <40 keystrokes) -> 422
    with pytest.raises(HTTPException) as exc:
        evaluate_typing_session(duration_seconds=20.0, keystrokes=50, backspaces=0, pause_count=0)
    assert exc.value.status_code == 422

    # Implausible speed (>250 WPM) -> 422
    with pytest.raises(HTTPException) as exc:
        evaluate_typing_session(duration_seconds=60.0, keystrokes=1500, backspaces=0, pause_count=0)
    assert exc.value.status_code == 422


def test_pulse_api_endpoints(client, db_session):
    """Test pulse recording endpoints with consent and idempotency."""
    client.post(
        "/api/auth/register",
        json={"name": "Rohan Pulse", "email": "rohan_pulse@test.com", "password": "Password1234!", "age_confirmed": True},
    )

    # 1. Manual entry without health_data consent -> 403
    res_no_consent = client.post("/api/pulse", json={"bpm": 74.0, "client_uuid": "manual-1"})
    assert res_no_consent.status_code == 403

    # Grant health_data consent
    client.put("/api/consent", json={"health_data": True})

    # 2. Manual entry with consent -> 201
    res_manual = client.post("/api/pulse", json={"bpm": 74.0, "client_uuid": "manual-1"})
    assert res_manual.status_code == 201
    assert res_manual.json()["bpm"] == 74.0

    # Idempotent retry with same client_uuid -> returns 201/existing record
    res_retry = client.post("/api/pulse", json={"bpm": 74.0, "client_uuid": "manual-1"})
    assert res_retry.status_code in (200, 201)
    assert res_retry.json()["id"] == res_manual.json()["id"]

    # 3. Camera PPG without camera consent -> 403
    ts, green = generate_synthetic_ppg(bpm=72.0)
    res_cam_no_consent = client.post("/api/pulse", json={"timestamps_ms": ts, "green": green, "client_uuid": "cam-1"})
    assert res_cam_no_consent.status_code == 403

    # Grant camera consent
    client.put("/api/consent", json={"camera": True})

    # 4. Camera PPG with consent -> 201
    res_cam = client.post("/api/pulse", json={"timestamps_ms": ts, "green": green, "client_uuid": "cam-1"})
    assert res_cam.status_code == 201
    assert abs(res_cam.json()["bpm"] - 72.0) <= 3.0


def test_behavior_api_endpoints(client, db_session):
    """Test typing behavior prompt retrieval, consent, submission, and rejection."""
    client.post(
        "/api/auth/register",
        json={"name": "Rohan Type", "email": "rohan_type@test.com", "password": "Password1234!", "age_confirmed": True},
    )

    # Prompt check
    res_prompt = client.get("/api/behavior/prompt")
    assert res_prompt.status_code == 200
    assert len(res_prompt.json()["text"]) > 20

    # Submit without behavior consent -> 403
    typing_payload = {
        "client_uuid": "type-uuid-1",
        "duration_seconds": 60.0,
        "keystrokes": 200,
        "backspaces": 8,
        "pause_count": 3,
    }
    res_no_consent = client.post("/api/behavior", json=typing_payload)
    assert res_no_consent.status_code == 403

    # Grant behavior consent
    client.put("/api/consent", json={"behavior": True})

    # Valid submission -> 201
    res_valid = client.post("/api/behavior", json=typing_payload)
    assert res_valid.status_code == 201
    assert res_valid.json()["typing_speed_wpm"] > 0

    # Idempotent retry
    res_retry = client.post("/api/behavior", json=typing_payload)
    assert res_retry.json()["id"] == res_valid.json()["id"]
