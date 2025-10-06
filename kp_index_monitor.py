#!/usr/bin/env python3
"""
Kp Index Space Weather Monitor

A monitoring system that tracks the Kp geomagnetic index from GFZ Potsdam
and sends automated email alerts when space weather conditions exceed specified thresholds.

Data Source: GFZ German Research Centre for Geosciences
URL: https://spaceweather.gfz.de/fileadmin/Kp-Forecast/CSV/
"""

import logging
import os
import smtplib
import time
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Dict, Optional

import pandas as pd
import requests

# Configuration setup
try:
    import config
except ImportError:
    config = None
    print("Warning: config.py not found. Using default configuration.")
    print("Please copy and edit config.py for your settings.")


class Config:
    """Configuration class containing all system settings"""

    KP_CSV_URL = (
        getattr(
            config,
            "KP_CSV_URL",
            "https://spaceweather.gfz.de/fileadmin/Kp-Forecast/CSV/kp_product_file_FORECAST_PAGER_SWIFT_LAST.csv",
        )
        if config
        else "https://spaceweather.gfz.de/fileadmin/Kp-Forecast/CSV/kp_product_file_FORECAST_PAGER_SWIFT_LAST.csv"
    )
    KP_ALERT_THRESHOLD = getattr(config, "KP_ALERT_THRESHOLD", 4.0) if config else 4.0
    SMTP_SERVER = getattr(config, "SMTP_SERVER", "smtp.gmail.com") if config else "smtp.gmail.com"
    SMTP_PORT = getattr(config, "SMTP_PORT", 587) if config else 587
    EMAIL_USER = getattr(config, "EMAIL_USER", "your_email@gmail.com") if config else "your_email@gmail.com"
    EMAIL_PASSWORD = getattr(config, "EMAIL_PASSWORD", "your_app_password") if config else "your_app_password"
    ALERT_RECIPIENTS = (
        getattr(config, "ALERT_RECIPIENTS", ["spaceweather@institution.edu"])
        if config
        else ["spaceweather@institution.edu"]
    )
    CHECK_INTERVAL_HOURS = getattr(config, "CHECK_INTERVAL_HOURS", 3) if config else 3
    LOG_FILE = getattr(config, "LOG_FILE", "kp_monitor.log") if config else "kp_monitor.log"


class KpMonitor:
    """
    Main monitoring class for Kp index space weather data.

    Handles data fetching, analysis, alerting, and email notifications
    for geomagnetic activity monitoring.
    """

    def __init__(self):
        self.setup_logging()
        self.last_alert_time = None
        self.last_max_kp = 0

    def setup_logging(self):
        """Configure logging to file and console"""
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(levelname)s - %(message)s",
            handlers=[logging.FileHandler(Config.LOG_FILE), logging.StreamHandler()],
        )
        self.logger = logging.getLogger(__name__)

    def fetch_kp_data(self) -> Optional[pd.DataFrame]:
        """
        Fetch current Kp index forecast data from GFZ website.

        Returns:
            DataFrame containing forecast data or None if fetch fails
        """
        try:
            self.logger.info(f"Fetching Kp data from {Config.KP_CSV_URL}")

            # Add headers to mimic browser request
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

            response = requests.get(Config.KP_CSV_URL, headers=headers, timeout=30)
            response.raise_for_status()

            # Read CSV data
            from io import StringIO

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


        Returns:
            Dictionary containing analysis results
        """
        try:
            # Get current maximum values
            max_values = df["maximum"].astype(float)
            current_max = max_values.max()

            # Find records above threshold
            high_kp_records = df[df["maximum"].astype(float) > Config.KP_ALERT_THRESHOLD]

            # Get upcoming forecast periods (next 24 hours)
            df["Time (UTC)"] = pd.to_datetime(df["Time (UTC)"], format="%d-%m-%Y %H:%M", dayfirst=True, utc=True)
            now = pd.Timestamp.now(tz="UTC")
            next_24h = df[df["Time (UTC)"] >= now].head(8)  # Next 8 periods (24 hours)

            analysis = {
                "current_max_kp": current_max,
                "threshold_exceeded": current_max > Config.KP_ALERT_THRESHOLD,
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

        Args:
            analysis: Dictionary containing analysis results

        Returns:
            Formatted alert message string
        """
        max_kp = analysis["current_max_kp"]
        high_records = analysis["high_kp_records"]

        message = f"""<html><body>
<h2><strong>SPACE WEATHER ALERT - High Kp Index Detected</strong></h2>

<h3><strong>ALERT SUMMARY:</strong></h3>
<ul>
<li><strong>Current Maximum Kp Index:</strong> {max_kp:.2f}</li>
<li><strong>Alert Threshold:</strong> {Config.KP_ALERT_THRESHOLD}</li>
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


<p><strong>DATA SOURCE:</strong> {Config.KP_CSV_URL}</p>

<p><em>This is an automated alert from the Kp Index Monitoring System.</em></p>
</body></html>"""

        return message.strip()

    def create_summary_message(self, df: pd.DataFrame, analysis: Dict) -> str:
        """
        Create formatted summary message for current KP Index conditions.

        Args:
            df: DataFrame containing forecast data
            analysis: Dictionary containing analysis results

        Returns:
            Formatted summary message string
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
<li><strong>Alert Threshold:</strong> {Config.KP_ALERT_THRESHOLD}</li>
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

<p><strong>DATA SOURCE:</strong> {Config.KP_CSV_URL}</p>

<p><em>This is an automated summary from the Kp Index Monitoring System using GFZ Space Weather Forecast.</em></p>
</body></html>"""

        return message.strip()

    def send_email_alert(self, subject: str, message: str) -> bool:
        """
        Send email alert using SMTP configuration.

        Args:
            subject: Email subject line
            message: Email message content

        Returns:
            True if email sent successfully, False otherwise
        """
        try:
            self.logger.info("Preparing to send email alert")

            # Create message
            msg = MIMEMultipart()
            msg["From"] = Config.EMAIL_USER
            msg["To"] = ", ".join(Config.ALERT_RECIPIENTS)
            msg["Subject"] = subject

            # Attach message body as HTML
            msg.attach(MIMEText(message, "html"))

            # Send email
            with smtplib.SMTP(Config.SMTP_SERVER, Config.SMTP_PORT) as server:
                server.starttls()
                server.login(Config.EMAIL_USER, Config.EMAIL_PASSWORD)
                server.send_message(msg)

            self.logger.info(f"Alert email sent to {len(Config.ALERT_RECIPIENTS)} recipients")
            return True

        except Exception as e:
            self.logger.error(f"Failed to send email: {e}")
            return False
        



    def send_linux_mail(self, subject: str, message: str) -> bool:
        """
        Send email using the system's configured SMTP (without calling `mail`).

        Args:
            subject: Email subject line
            message: Email message content

        Returns:
            True if email sent successfully, False otherwise
        """
        try:
            recipients = Config.ALERT_RECIPIENTS
            import smtplib
            from email.message import EmailMessage

            # Construct email
            msg = EmailMessage()
            msg["Subject"] = subject
            msg["From"] = "pager"  # should be a valid sender on your server
            msg["To"] = ", ".join(recipients)
            msg.add_alternative(message, subtype="html")

            # Connect to local MTA (usually localhost:25)
            with smtplib.SMTP("localhost") as smtp:
                smtp.send_message(msg)

            self.logger.info(f"Linux mail sent successfully to {len(recipients)} recipients")
            return True

        except Exception as e:
            self.logger.error(f"Error sending mail: {e}")
            return False


    def should_send_alert(self, analysis: Dict) -> bool:
        """
        Determine if alert should be sent to avoid spam.

        Args:
            analysis: Dictionary containing analysis results

        Returns:
            True if alert should be sent, False otherwise
        """
        if not analysis["alert_worthy"]:
            return False

        # Avoid sending multiple alerts for the same high Kp period
        # current_time = pd.Timestamp.now(tz="UTC")
        # if self.last_alert_time:
        #     time_since_last_alert = (current_time - self.last_alert_time).total_seconds() / 3600
        #     if time_since_last_alert < 6:  # Don't send alerts more than once every 6 hours
        #         self.logger.info("Skipping alert - too soon since last alert")
        #         return False

        return True

    def run_single_check(self) -> bool:
        """
        Execute a single monitoring check cycle.

        Returns:
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

            # Try to send email (Gmail SMTP as default, Linux mail as fallback)
            email_sent = False

            # Try Gmail SMTP first
            email_sent = False

            # Fallback to Linux mail if SMTP fails
            if not email_sent and os.name == "posix":  # Linux/Unix fallback
                email_sent = self.send_linux_mail(subject, message)

            if email_sent:
                self.last_alert_time = pd.Timestamp.now(tz="UTC")
                self.last_max_kp = max_kp
        else:
            self.logger.info(f"No alert needed - Max Kp: {analysis['current_max_kp']:.2f}")

        return True

    def send_summary_email(self, recipient: str) -> bool:
        """
        Fetch current data and send summary email to specified recipient.

        Args:
            recipient: Email address to send summary to

        Returns:
            True if email sent successfully, False otherwise
        """
        self.logger.info("=" * 50)
        self.logger.info(f"Generating Kp summary for {recipient}")

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
        message = self.create_summary_message(df, analysis)

        # Send email to specific recipient
        try:
            # Create message
            msg = MIMEMultipart()
            msg["From"] = Config.EMAIL_USER
            msg["To"] = recipient
            msg["Subject"] = subject

            # Attach message body as HTML
            msg.attach(MIMEText(message, "html"))

            # Send email
            with smtplib.SMTP(Config.SMTP_SERVER, Config.SMTP_PORT) as server:
                server.starttls()
                server.login(Config.EMAIL_USER, Config.EMAIL_PASSWORD)
                server.send_message(msg)

            self.logger.info(f"Summary email sent successfully to {recipient}")
            return True

        except Exception as e:
            self.logger.error(f"Failed to send summary email: {e}")

            # Try Linux mail as fallback
            try:
                import subprocess

                cmd = f'echo "{message}" | mail -s "{subject}" {recipient}'
                result = subprocess.run(cmd, shell=True, capture_output=True, text=True)

                if result.returncode == 0:
                    self.logger.info(f"Summary sent via Linux mail to {recipient}")
                    return True
                else:
                    self.logger.error(f"Linux mail also failed: {result.stderr}")
                    return False

            except Exception as e2:
                self.logger.error(f"Both email methods failed: {e2}")
                return False

    def run_continuous_monitoring(self):
        """Run continuous monitoring with specified check intervals"""
        self.logger.info("Starting continuous Kp index monitoring")
        self.logger.info(f"Check interval: {Config.CHECK_INTERVAL_HOURS} hours")
        self.logger.info(f"Alert threshold: {Config.KP_ALERT_THRESHOLD}")

        while True:
            try:
                self.run_single_check()

                # Wait for next check
                sleep_seconds = Config.CHECK_INTERVAL_HOURS * 3600
                self.logger.info(f"Waiting {Config.CHECK_INTERVAL_HOURS} hours until next check...")
                time.sleep(sleep_seconds)

            except KeyboardInterrupt:
                self.logger.info("Monitoring stopped by user")
                break
            except Exception as e:
                self.logger.error(f"Error in monitoring loop: {e}")
                time.sleep(300)  # Wait 5 minutes before retrying


def main():
    """Main function with command line interface"""
    import argparse

    parser = argparse.ArgumentParser(description="Kp Index Space Weather Monitor")
    parser.add_argument("--once", action="store_true", help="Run single check and exit")
    parser.add_argument("--continuous", action="store_true", help="Run continuous monitoring")
    parser.add_argument("--test", action="store_true", help="Test email functionality")
    parser.add_argument("--summary", action="store_true", help="Send current Kp summary via email")
    parser.add_argument("--email", type=str, help="Email address for summary (required with --summary)")

    args = parser.parse_args()

    monitor = KpMonitor()

    if args.test:
        # Test email functionality
        subject = "Kp Monitor Test Email"
        message = "This is a test email from the Kp Index Monitoring System."

        print("Testing email functionality...")
        # Try Gmail SMTP first, then Linux mail as fallback
        success = False
        if not success and os.name == "posix":
            success = monitor.send_linux_mail(subject, message)

        print("Email test:", "SUCCESS" if success else "FAILED")

    elif args.summary:
        # Send summary email
        if not args.email:
            print("Error: --email argument is required when using --summary")
            print("Example: python kp_index_monitor.py --summary --email scientist@university.edu")
            return

        print(f"Sending Kp summary to {args.email}...")
        success = monitor.send_summary_email(args.email)
        print("Summary email:", "SUCCESS" if success else "FAILED")

    elif args.once:
        # Single check
        monitor.run_single_check()

    elif args.continuous:
        # Continuous monitoring
        monitor.run_continuous_monitoring()

    else:
        print("Usage: python kp_index_monitor.py [--once|--continuous|--test|--summary]")
        print("  --once                    : Run single check")
        print("  --continuous              : Run continuous monitoring")
        print("  --test                    : Test email functionality")
        print("  --summary --email <addr>  : Send current Kp summary to specified email")


if __name__ == "__main__":
    main()
