#!/usr/bin/env python3
"""
Kp Index Space Weather Monitor

A monitoring system that tracks the Kp geomagnetic index from GFZ Potsdam
and sends automated email alerts when space weather conditions exceed specified thresholds.

Data Source: GFZ German Research Centre for Geosciences
URL: https://spaceweather.gfz.de/fileadmin/Kp-Forecast/CSV/kp_product_file_FORECAST_PAGER_SWIFT_LAST.csv

"""

import argparse
import logging
import smtplib
import time
from datetime import datetime, timezone
from email.message import EmailMessage
from io import StringIO
from typing import Dict, Optional

import pandas as pd
import requests

from src.config import KP_CSV_URL, MonitorConfig


class KpMonitor:
    """
    Main monitoring class for Kp index space weather data.

    Handles data fetching, analysis, alerting, and email notifications
    for geomagnetic activity monitoring.
    """

    def __init__(self, config: MonitorConfig):
        self.last_alert_time = None
        self.last_max_kp = 0
        self.config = config
        self.setup_logging()

    def setup_logging(self) -> None:
        """
        Configure logging to file and console.

        Sets up logging handlers for both file and console output with
        appropriate formatting and log levels from configuration.
        """
        logging.basicConfig(
            level=self.config.log_level,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            handlers=[logging.FileHandler(self.config.log_file), logging.StreamHandler()],
        )
        self.logger = logging.getLogger(__name__)

    def fetch_kp_data(self) -> Optional[pd.DataFrame]:
        """
        Fetch current Kp index forecast data from GFZ website.

        Returns
        -------
        pd.DataFrame or None
            DataFrame containing forecast data or None if fetch fails
        """
        try:
            self.logger.info(f"Fetching Kp data from {KP_CSV_URL}")
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            response = requests.get(KP_CSV_URL, headers=headers, timeout=30)
            response.raise_for_status()
            df = pd.read_csv(StringIO(response.text))

            self.logger.info(f"Successfully fetched {len(df)} records")
            return df

        except requests.RequestException as e:
            self.logger.error(f"Error fetching data: {e}")
            return None
        except pd.errors.EmptyDataError:
            self.logger.error("Received empty CSV file")
            return None
        except Exception as e:
            self.logger.error(f"Unexpected error: {e}")
            return None

    def analyze_kp_data(self, df: pd.DataFrame) -> Dict:
        """
        Analyze Kp forecast data for alert conditions.

        Parameters
        ----------
        df : pd.DataFrame
            DataFrame containing Kp forecast data from GFZ

        Returns
        -------
        Dict
            Dictionary containing analysis results with keys:
            - current_max_kp: Maximum Kp value in current forecast
            - threshold_exceeded: Boolean indicating if threshold exceeded
            - high_kp_records: Records above alert threshold
            - next_24h_forecast: Forecast for next 24 hours
            - alert_worthy: Boolean indicating if alert should be sent
        """
        try:
            # Get current maximum values
            max_values = df["maximum"].astype(float)
            current_max = max_values.iloc[0]

            # Find records above threshold
            high_kp_records = df[df["maximum"].astype(float) > self.config.kp_alert_threshold]

            # Get upcoming forecast periods (next 24 hours)
            df["Time (UTC)"] = pd.to_datetime(df["Time (UTC)"], format="%d-%m-%Y %H:%M", dayfirst=True, utc=True)
            now = pd.Timestamp.now(tz="UTC")
            next_24h = df[df["Time (UTC)"] >= now].head(8)  # Next 8 periods (24 hours)

            analysis = {
                "current_max_kp": current_max,
                "threshold_exceeded": current_max > self.config.kp_alert_threshold,
                "high_kp_records": high_kp_records,
                "next_24h_forecast": next_24h,
                "alert_worthy": len(high_kp_records) > 0,
            }

            self.logger.info(f"Analysis complete - Max Kp: {current_max:.2f}, Alert: {analysis['alert_worthy']}")
            return analysis

        except Exception as e:
            self.logger.error(f"Error analyzing data: {e}")
            return {"alert_worthy": False, "current_max_kp": 0}

    def create_alert_message(self, analysis: Dict) -> str:
        """
        Create formatted alert message for high Kp conditions.

        Parameters
        ----------
        analysis : Dict
            Dictionary containing analysis results from analyze_kp_data

        Returns
        -------
        str
            Formatted HTML alert message string ready for email
        """
        max_kp = analysis["current_max_kp"]
        high_records = analysis["high_kp_records"]

        message = f"""<html><body>
<h2><strong>SPACE WEATHER ALERT - High Kp Index Detected</strong></h2>

<h3><strong>ALERT SUMMARY:</strong></h3>
<ul>
<li><strong>Current Maximum Kp Index:</strong> {max_kp:.2f}</li>
<li><strong>Alert Threshold:</strong> {self.config.kp_alert_threshold}</li>
            <li><strong>Alert Time:</strong> {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")} UTC</li>
</ul>

<h3><strong>HIGH KP INDEX PERIODS DETECTED:</strong></h3>
<ul>
"""

        for _, record in high_records.iterrows():
            message += f"<li><strong>{record['Time (UTC)']} UTC:</strong> Kp = {record['maximum']:.2f}</li>\n"

        message += f"""</ul>

<h3><strong>GEOMAGNETIC STORM LEVELS:</strong></h3>
<ul>
<li><strong>Kp 5:</strong> Minor geomagnetic storm (G1)</li>
<li><strong>Kp 6:</strong> Moderate geomagnetic storm (G2)</li>
<li><strong>Kp 7:</strong> Strong geomagnetic storm (G3)</li>
<li><strong>Kp 8:</strong> Severe geomagnetic storm (G4)</li>
<li><strong>Kp 9:</strong> Extreme geomagnetic storm (G5)</li>
</ul>


<p><strong>DATA SOURCE:</strong> {KP_CSV_URL}</p>

<p><em>This is an automated alert from the Kp Index Monitoring System.</em></p>
</body></html>"""

        return message.strip()

    def create_summary_message(self, analysis: Dict) -> str:
        """
        Create formatted summary message for current KP Index conditions.

        Parameters
        ----------
        analysis : Dict
            Dictionary containing analysis results from analyze_kp_data

        Returns
        -------
        str
            Formatted HTML summary message string ready for email
        """
        current_max = analysis["current_max_kp"]
        next_24h = analysis["next_24h_forecast"]

        # Determine current geomagnetic activity level
        if current_max >= 8:
            status = "SEVERE STORM CONDITIONS"
            level = "[G4]"
        elif current_max >= 7:
            status = "STRONG STORM CONDITIONS"
            level = "[G3]"
        elif current_max >= 6:
            status = "MODERATE STORM CONDITIONS"
            level = "[G2]"
        elif current_max >= 5:
            status = "MINOR STORM CONDITIONS"
            level = "[G1]"
        elif current_max >= 4:
            status = "ACTIVE CONDITIONS"
            level = "[ACTIVE]"
        else:
            status = "QUIET CONDITIONS"
            level = "[QUIET]"

        message = f"""<html><body>
<h2><strong>SPACE WEATHER - KP Index SUMMARY REPORT</strong></h2>

<h3><strong>CURRENT STATUS:</strong> {status} {level}</h3>
<ul>
            <li><strong>Report Time:</strong> {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")} UTC</li>
<li><strong>Current Maximum KP:</strong> {current_max:.2f}</li>
<li><strong>Alert Threshold:</strong> {self.config.kp_alert_threshold}</li>
</ul>

<h3><strong>NEXT 24 HOURS FORECAST:</strong></h3>
<ul>
"""

        for _, record in next_24h.iterrows():
            kp_val = float(record["maximum"])
            if kp_val >= 5:
                indicator = "(ALERT)"
            elif kp_val >= 4:
                indicator = "(ACTIVE)"
            else:
                indicator = "(QUIET)"
            message += f"<li><strong>{record['Time (UTC)']} UTC:</strong> Kp = {kp_val:.2f} {indicator}</li>\n"
        # Add interpretation guide
        message += f"""</ul>

<h3><strong>GEOMAGNETIC ACTIVITY SCALE:</strong></h3>
<ul>
<li><strong>Kp 0-2:</strong> Quiet conditions</li>
<li><strong>Kp 3-4:</strong> Unsettled to Active conditions</li>
<li><strong>Kp 5:</strong> Minor Storm (G1) - Weak power grid fluctuations</li>
<li><strong>Kp 6:</strong> Moderate Storm (G2) - High-latitude power systems affected</li>
<li><strong>Kp 7:</strong> Strong Storm (G3) - Power systems may experience voltage corrections</li>
<li><strong>Kp 8:</strong> Severe Storm (G4) - Possible widespread voltage control problems</li>
<li><strong>Kp 9:</strong> Extreme Storm (G5) - Widespread power system voltage control problems</li>
</ul>

<h3><strong>FORECAST DATA SUMMARY:</strong></h3>
<p>The latest ensemble predictions contain the following information:</p>
<ul>
<li>Time in UTC format: dd-mm-yyyy HH:MM</li>
<li>Minimum, 0.25-quantile, median, 0.75-quantile, maximum forecasted values</li>
<li>Probability ranges for different Kp levels</li>
<li>Individual ensemble members (currently varies between 12-20 members)</li>
</ul>

<p><strong>DATA SOURCE:</strong> {KP_CSV_URL}</p>

<p><em>This is an automated summary from the Kp Index Monitoring System using GFZ Space Weather Forecast.</em></p>
</body></html>"""

        return message.strip()

    def send_alert(self, subject: str, message: str) -> bool:
        """
        Send email using the system's configured SMTP (without calling `mail`).

        Parameters
        ----------
        subject : str
            Email subject line
        message : str
            Email message content (HTML formatted)

        Returns
        -------
        bool
            True if email sent successfully, False otherwise
        """
        try:
            recipients = self.config.recipients

            # Construct email
            msg = EmailMessage()
            msg["Subject"] = subject
            msg["From"] = "pager"
            msg["Bcc"] = ", ".join(recipients)
            msg.add_alternative(message, subtype="html")

            # Connect to local MTA (usually localhost:25)
            with smtplib.SMTP("localhost") as smtp:
                smtp.send_message(msg)

            self.logger.info(f"Mail sent successfully to {len(recipients)} recipients")
            return True

        except Exception as e:
            self.logger.error(f"Error sending mail: {e}")
            return False

    def should_send_alert(self, analysis: Dict) -> bool:
        """
        Determine if alert should be sent to avoid spam.

        Parameters
        ----------
        analysis : Dict
            Dictionary containing analysis results from analyze_kp_data

        Returns
        -------
        bool
            True if alert should be sent, False otherwise
        """
        if not analysis["alert_worthy"]:
            return False

        # Avoid sending multiple alerts for the same high Kp period
        current_time = pd.Timestamp.now(tz="UTC")
        if self.last_alert_time:
            time_since_last_alert = (current_time - self.last_alert_time).total_seconds() / 3600
            if time_since_last_alert < 6:  # Don't send alerts more than once every 6 hours
                self.logger.info("Skipping alert - too soon since last alert")
                return False

        return True

    def run_single_check(self) -> bool:
        """
        Execute a single monitoring check cycle.

        Fetches Kp data, analyzes it, and sends alerts if necessary.

        Returns
        -------
        bool
            True if check completed successfully, False otherwise
        """
        self.logger.info("=" * 50)
        self.logger.info("Starting Kp index monitoring check")

        # Fetch data
        df = self.fetch_kp_data()
        if df is None:
            return False

        # Analyze data
        analysis = self.analyze_kp_data(df)

        # Check if alert should be sent
        if self.should_send_alert(analysis):
            max_kp = analysis["current_max_kp"]
            subject = f"SPACE WEATHER ALERT: High Kp Index ({max_kp:.1f}) Detected"
            message = self.create_alert_message(analysis)

            email_sent = self.send_alert(subject, message)

            if email_sent:
                self.last_alert_time = pd.Timestamp.now(tz="UTC")
                self.last_max_kp = max_kp
        else:
            self.logger.info(f"No alert needed - Max Kp: {analysis['current_max_kp']:.2f}")

        return True

    def send_summary_email(self) -> bool:
        """
        Fetch current data and send summary email to configured recipients.

        Generates and sends a comprehensive summary of current Kp conditions
        and 24-hour forecast to all configured email recipients.

        Returns
        -------
        bool
            True if email sent successfully, False otherwise
        """
        recipients = self.config.recipients
        self.logger.info(f"Generating Kp summary for {recipients}")

        # Fetch data
        df = self.fetch_kp_data()
        if df is None:
            self.logger.error("Failed to fetch data for summary")
            return False

        # Analyze data
        analysis = self.analyze_kp_data(df)

        # Create summary message
        max_kp = analysis["current_max_kp"]
        subject = f"Space Weather Summary Report - Current Kp: {max_kp:.1f}"
        message = self.create_summary_message(analysis)

        try:
            msg = EmailMessage()
            msg["From"] = "pager"
            msg["Bcc"] = ", ".join(recipients)
            msg["Subject"] = subject

            # Attach message body as HTML
            msg.add_alternative(message, subtype="html")

            with smtplib.SMTP("localhost") as smtp:
                smtp.send_message(msg)

            self.logger.info(f"Summary email sent successfully to {', '.join(recipients)}")
            return True

        except Exception as e:
            self.logger.error(f"Error sending mail: {e}")
            return False

    def run_continuous_monitoring(self) -> None:
        """
        Run continuous monitoring with specified check intervals.

        Runs indefinitely, checking Kp data at configured intervals and
        sending alerts when thresholds are exceeded. Can be stopped with
        Ctrl+C (KeyboardInterrupt).
        """
        self.logger.info("Starting continuous Kp index monitoring")
        self.logger.info(f"Check interval: {self.config.check_interval_hours} hours")
        self.logger.info(f"Alert threshold: {self.config.kp_alert_threshold}")

        while True:
            try:
                self.run_single_check()

                # Wait for next check
                sleep_seconds = self.config.check_interval_hours * 3600
                self.logger.info(f"Waiting {self.config.check_interval_hours} hours until next check...")
                time.sleep(sleep_seconds)

            except KeyboardInterrupt:
                self.logger.info("Monitoring stopped by user")
                break
            except Exception as e:
                self.logger.error(f"Error in monitoring loop: {e}")
                time.sleep(300)  # Wait 5 minutes before retrying


def main():
    """
    Main function with command line interface.
    """

    parser = argparse.ArgumentParser(description="Kp Index Space Weather Monitor")
    group = parser.add_mutually_exclusive_group(required=True)

    group.add_argument("--once", action="store_true", help="Run single check and exit")
    group.add_argument("--continuous", action="store_true", help="Run continuous monitoring")
    group.add_argument("--test", action="store_true", help="Test email functionality")
    group.add_argument("--summary", action="store_true", help="Send current Kp summary via email")

    args = parser.parse_args()

    config = MonitorConfig.from_yaml()

    monitor = KpMonitor(config)

    if args.test:
        subject = "Kp Monitor Test Email"
        message = "This is a test email from the Kp Index Monitoring System."

        logging.info("Testing email functionality...")
        success = monitor.send_alert(subject, message)
        logging.info(f"Summary email: {'SUCCESS' if success else 'FAILED'}")

    elif args.summary:
        success = monitor.send_summary_email()
        logging.info(f"Summary email: {'SUCCESS' if success else 'FAILED'}")

    elif args.once:
        monitor.run_single_check()

    elif args.continuous:
        monitor.run_continuous_monitoring()


if __name__ == "__main__":
    main()
