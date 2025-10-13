#!/usr/bin/env python3
"""
Configuration data class for the Kp Index Space Weather Monitor.

This module provides a YAML-based configuration system with validation
and type safety for the monitoring system.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List

import yaml


@dataclass
class MonitorConfig:
    """
    Configuration data class for the Kp Index Monitor.

    Contains all configuration parameters for the Kp monitoring system
    including alert thresholds, email settings, and logging configuration.

    Attributes
    ----------
    kp_alert_threshold : float
        Kp value threshold for triggering alerts (0-9 scale)
    check_interval_hours : float
        Hours between monitoring checks (must be positive)
    recipients : List[str]
        Email addresses to receive alerts
    log_folder : str
        Path to log folder for monitoring output
    log_level : str, default="INFO"
        Logging level (DEBUG, INFO, WARNING, ERROR)
    """

    # Alert settings
    kp_alert_threshold: float
    check_interval_hours: float

    recipients: List[str]

    # Logging configuration
    log_folder: str
    log_level: str = "INFO"

    @staticmethod
    def from_yaml(config_file: Path | str = None) -> MonitorConfig:
        """
        Load configuration from YAML file.

        Parameters
        ----------
        config_file : Path or str, optional
            Path to YAML configuration file. If None, uses environment variable
            KP_MONITOR_CONFIG or defaults to 'config.yaml'

        Returns
        -------
        MonitorConfig
            Loaded and validated configuration object

        Raises
        ------
        FileNotFoundError
            If configuration file doesn't exist
        yaml.YAMLError
            If YAML file is invalid
        ValueError
            If configuration validation fails
        """
        if config_file is None:
            config_file = os.environ.get("KP_MONITOR_CONFIG", "config.yaml")

        config_path = Path(config_file)

        if not config_path.exists():
            raise FileNotFoundError(f"Configuration file not found: {config_path}")

        try:
            with open(config_path, "r") as file:
                data = yaml.safe_load(file)
        except yaml.YAMLError as e:
            raise yaml.YAMLError(f"Invalid YAML in configuration file: {e}")

        if not data:
            raise ValueError("Configuration file is empty or contains no valid data")

        # Extract only fields that exist in the dataclass
        load_data = {key: value for key, value in data.items() if key in MonitorConfig.__annotations__}
        config = MonitorConfig(**load_data)
        config.validate()

        return config

    def validate(self) -> None:
        """
        Validate configuration values.

        Raises
        ------
        ValueError
            If any configuration value is invalid
        """
        errors = []

        # Validate Kp alert threshold
        if not (0 <= self.kp_alert_threshold <= 9):
            errors.append("kp_alert_threshold must be between 0 and 9")

        # Validate check interval
        if self.check_interval_hours <= 0:
            errors.append("check_interval_hours must be positive")

        # Validate alert recipients
        if not self.recipients:
            errors.append("recipients cannot be empty")

        # Validate email addresses
        email_pattern = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")
        for email in self.recipients:
            if not email_pattern.match(email):
                errors.append(f"Invalid email address: {email}")

        # Validate log file path
        if not self.log_folder:
            errors.append("log_folder cannot be empty")

        if errors:
            raise ValueError("Configuration validation failed:\n" + "\n".join(f"  - {error}" for error in errors))
