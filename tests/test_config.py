"""Tests for LoopGuardConfig."""

import pytest

from fastapi_loopguard import LoopGuardConfig


class TestLoopGuardConfig:
    """Tests for configuration validation."""

    def test_default_config(self) -> None:
        """Test default configuration values."""
        config = LoopGuardConfig()

        assert config.enabled is True
        assert config.monitor_interval_ms == 10.0
        assert config.threshold_multiplier == 5.0
        assert config.calibration_iterations == 100
        assert config.fallback_threshold_ms == 50.0
        assert config.dev_mode is False
        assert config.log_blocking_events is True
        assert config.prometheus_enabled is False

    def test_custom_config(self) -> None:
        """Test custom configuration values."""
        config = LoopGuardConfig(
            enabled=False,
            monitor_interval_ms=50.0,
            threshold_multiplier=10.0,
            dev_mode=True,
        )

        assert config.enabled is False
        assert config.monitor_interval_ms == 50.0
        assert config.threshold_multiplier == 10.0
        assert config.dev_mode is True

    def test_invalid_monitor_interval(self) -> None:
        """Test that invalid monitor_interval_ms raises ValueError."""
        with pytest.raises(ValueError, match="monitor_interval_ms must be positive"):
            LoopGuardConfig(monitor_interval_ms=0)

        with pytest.raises(ValueError, match="monitor_interval_ms must be positive"):
            LoopGuardConfig(monitor_interval_ms=-10)

    def test_invalid_threshold_multiplier(self) -> None:
        """Test that invalid threshold_multiplier raises ValueError."""
        with pytest.raises(ValueError, match="threshold_multiplier"):
            LoopGuardConfig(threshold_multiplier=1.0)

        with pytest.raises(ValueError, match="threshold_multiplier"):
            LoopGuardConfig(threshold_multiplier=0.5)

    def test_invalid_calibration_iterations(self) -> None:
        """Test that invalid calibration_iterations raises ValueError."""
        with pytest.raises(ValueError, match="calibration_iterations"):
            LoopGuardConfig(calibration_iterations=5)

    def test_invalid_fallback_threshold(self) -> None:
        """Test that invalid fallback_threshold_ms raises ValueError."""
        with pytest.raises(ValueError, match="fallback_threshold_ms must be positive"):
            LoopGuardConfig(fallback_threshold_ms=0)

    def test_config_is_frozen(self) -> None:
        """Test that config is immutable."""
        config = LoopGuardConfig()

        with pytest.raises(AttributeError):
            config.enabled = False  # type: ignore[misc]

    def test_exclude_paths_default(self) -> None:
        """Test default excluded paths."""
        config = LoopGuardConfig()

        assert "/health" in config.exclude_paths
        assert "/healthz" in config.exclude_paths
        assert "/ready" in config.exclude_paths
        assert "/metrics" in config.exclude_paths

    def test_adaptive_config_defaults(self) -> None:
        """Test default adaptive threshold configuration."""
        config = LoopGuardConfig()

        assert config.adaptive_threshold is False
        assert config.adaptive_window_size == 1000
        assert config.adaptive_percentile == 0.95
        assert config.adaptive_min_samples == 100
        assert config.adaptive_update_interval_ms == 1000.0

    def test_adaptive_config_custom(self) -> None:
        """Test custom adaptive threshold configuration."""
        config = LoopGuardConfig(
            adaptive_threshold=True,
            adaptive_window_size=2000,
            adaptive_percentile=0.99,
            adaptive_min_samples=200,
            adaptive_update_interval_ms=500.0,
        )

        assert config.adaptive_threshold is True
        assert config.adaptive_window_size == 2000
        assert config.adaptive_percentile == 0.99
        assert config.adaptive_min_samples == 200
        assert config.adaptive_update_interval_ms == 500.0

    def test_invalid_adaptive_window_size(self) -> None:
        """Test that invalid adaptive_window_size raises ValueError."""
        with pytest.raises(
            ValueError, match="adaptive_window_size must be at least 100"
        ):
            LoopGuardConfig(adaptive_window_size=50)

    def test_invalid_adaptive_percentile_low(self) -> None:
        """Test that adaptive_percentile < 0.5 raises ValueError."""
        with pytest.raises(ValueError, match="adaptive_percentile must be between"):
            LoopGuardConfig(adaptive_percentile=0.3)

    def test_invalid_adaptive_percentile_high(self) -> None:
        """Test that adaptive_percentile > 0.99 raises ValueError."""
        with pytest.raises(ValueError, match="adaptive_percentile must be between"):
            LoopGuardConfig(adaptive_percentile=1.0)

    def test_invalid_adaptive_min_samples(self) -> None:
        """Test that invalid adaptive_min_samples raises ValueError."""
        with pytest.raises(
            ValueError, match="adaptive_min_samples must be at least 10"
        ):
            LoopGuardConfig(adaptive_min_samples=5)

    def test_invalid_adaptive_update_interval(self) -> None:
        """Test that invalid adaptive_update_interval_ms raises ValueError."""
        with pytest.raises(
            ValueError, match="adaptive_update_interval_ms must be positive"
        ):
            LoopGuardConfig(adaptive_update_interval_ms=0)
