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
import re
import shutil
import smtplib
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from io import StringIO
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import requests

from src.config import KP_CSV_URL, MonitorConfig


@dataclass
class AnalysisResults:
    current_max_kp: float
    threshold_exceeded: bool
    high_kp_records: pd.DataFrame
    next_24h_forecast: pd.DataFrame
    alert_worthy: bool
    probability_df: pd.DataFrame

    def __getitem__(self, key):
        return getattr(self, key)


# fmt: off
KP_TO_DECIMAL = {
    "0": 0.00, "0+": 0.33,
    "1-": 0.67, "1": 1.00, "1+": 1.33,
    "2-": 1.67, "2": 2.00, "2+": 2.33,
    "3-": 2.67, "3": 3.00, "3+": 3.33,
    "4-": 3.67, "4": 4.00, "4+": 4.33,
    "5-": 4.67, "5": 5.00, "5+": 5.33,
    "6-": 5.67, "6": 6.00, "6+": 6.33,
    "7-": 6.67, "7": 7.00, "7+": 7.33,
    "8-": 7.67, "8": 8.00, "8+": 8.33,
    "9-": 8.67, "9": 9.00
}
# fmt: on
DECIMAL_TO_KP = {v: k for k, v in KP_TO_DECIMAL.items()}


class KpMonitor:
    """
    Main monitoring class for Kp index space weather data.

    Handles data fetching, analysis, alerting, and email notifications
    for geomagnetic activity monitoring.
    """

    IMAGE_PATH = "/PAGER/FLAG/data/published/kp_swift_ensemble_LAST.png"

    def __init__(self, config: MonitorConfig):
        self.last_alert_time = None
        self.last_max_kp = 0
        self.config = config
        self.log_folder = Path(self.config.log_folder)
        self.log_folder.mkdir(parents=True, exist_ok=True)
        self.config.kp_alert_threshold = np.round(self.config.kp_alert_threshold, 2)
        self.kp_threshold_str = DECIMAL_TO_KP[self.config.kp_alert_threshold]
        self.LOCAL_IMAGE_PATH = shutil.copy2(self.IMAGE_PATH, "./kp_swift_ensemble_LAST.png")
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
            handlers=[
                logging.FileHandler(
                    self.log_folder / f"kp_monitor_{datetime.now(timezone.utc).strftime('%Y%d%mT%H%M00')}.log"
                ),
                logging.StreamHandler(),
            ],
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
            self.logger.error(f"Error fetching data: {e}", exc_info=True)
            return None
        except pd.errors.EmptyDataError:
            self.logger.error("Received empty CSV file")
            return None
        except Exception as e:
            self.logger.error(f"Unexpected error: {e}", exc_info=True)
            return None

    def analyze_kp_data(self, df: pd.DataFrame) -> AnalysisResults:
        """
        Analyze Kp forecast data for alert conditions.

        Parameters
        ----------
        df : pd.DataFrame
            DataFrame containing Kp forecast data from GFZ

        Returns
        -------
        AnalysisResults
            AnalysisResults containing analysis results with keys:
            - current_max_kp: Maximum Kp value in current forecast
            - threshold_exceeded: Boolean indicating if threshold exceeded
            - high_kp_records: Records above alert threshold
            - next_24h_forecast: Forecast for next 24 hours
            - alert_worthy: Boolean indicating if alert should be sent
        """
        try:
            # Get current maximum values
            max_values = df["maximum"].astype(float)
            current_max = np.round(max_values.max(), 2)

            self.ensembles = [col for col in df.columns if re.match(r"kp_\d+", col)]
            self.total_ensembles = len(self.ensembles)
            probability = np.sum(df[self.ensembles] >= self.config.kp_alert_threshold, axis=1) / self.total_ensembles

            df["Time (UTC)"] = pd.to_datetime(df["Time (UTC)"], format="%d-%m-%Y %H:%M", dayfirst=True, utc=True)
            df["Time (UTC)"] = df["Time (UTC)"].dt.tz_convert("UTC")

            high_kp_records = df[df["maximum"].astype(float) >= self.config.kp_alert_threshold].copy()
            high_kp_records = high_kp_records[high_kp_records["Time (UTC)"] >= pd.Timestamp.now(tz="UTC")].copy()
            next_24h = df[df["Time (UTC)"] >= pd.Timestamp.now(tz="UTC")].head(8).copy()

            high_kp_records["Time (UTC)"] = pd.to_datetime(high_kp_records["Time (UTC)"], utc=True)
            next_24h["Time (UTC)"] = pd.to_datetime(next_24h["Time (UTC)"], utc=True)

            probability_df = pd.DataFrame({"Time (UTC)": df["Time (UTC)"], "Probability": probability})
            probability_df.index = probability_df["Time (UTC)"]
            probability_df.drop(columns=["Time (UTC)"], inplace=True)

            analysis = AnalysisResults(
                current_max_kp=current_max,
                threshold_exceeded=current_max > self.config.kp_alert_threshold,
                high_kp_records=high_kp_records.round(2),
                next_24h_forecast=next_24h.round(2),
                alert_worthy=len(high_kp_records) > 0,
                probability_df=probability_df.round(2),
            )

            self.logger.info(
                f"Analysis complete - Current Kp: {DECIMAL_TO_KP[current_max]}, Alert: {analysis['alert_worthy']}, Threshold: {self.kp_threshold_str}"
            )
            return analysis

        except Exception as e:
            self.logger.error(f"Error analyzing data: {e}", exc_info=True)
            return {"alert_worthy": False, "current_max_kp": 0}

    def create_alert_message(self, analysis: AnalysisResults) -> str:
        """
        Create formatted alert message for high Kp conditions.

        Parameters
        ----------
        analysis : AnalysisResults
            AnalysisResults containing analysis results from analyze_kp_data

        Returns
        -------
        str
            Formatted HTML alert message string ready for email
        """
        max_kp = analysis["current_max_kp"]
        high_records = analysis["high_kp_records"]
        probability_df = analysis["probability_df"]
        current_kp = analysis.next_24h_forecast["median"].iloc[0]
        status, _, color = self.get_status_level_color(current_kp)

        message = f"""<html><body>
                    <h2><strong>SPACE WEATHER ALERT - Kp Index >= {self.kp_threshold_str} Predicted</strong></h2>
                    <h3><strong>ALERT SUMMARY</strong></h3>
                    <ul>
                        <li><strong>Current Status: </strong> <span style="color: {color};">  {status}</span></li>
                        <li><strong>Alert Time:</strong> {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")} UTC</li>
                        <li><strong>Maximum Kp for 72 hours window:</strong> {DECIMAL_TO_KP[max_kp]}</li>
                        <li><strong>Total number of ensembles:</strong> {self.total_ensembles}</li>
                    </ul>
                    <h3><strong>HIGH Kp INDEX PERIODS Predicted (Kp >= {self.kp_threshold_str})</strong></h3>
                    <ul>
                    """

        message += self._kp_html_table(high_records, probability_df)
        message += "</tbody></table>\n"
        message += '<br><img src="cid:forecast_image" style="max-width:100%;">'
        AURORA_KP = 6.33
        high_records_above_threshold = high_records[
            (high_records["minimum"].astype(float) >= AURORA_KP)
            | (high_records["median"].astype(float) >= AURORA_KP)
            | (high_records["maximum"].astype(float) >= AURORA_KP)
        ]
        message += "</ul>\n"
        if not high_records_above_threshold.empty:
            message += "<h3><strong>AURORA WATCH:</strong></h3>\n"
            message += f"<p>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;<strong>Note:</strong> Kp >= {DECIMAL_TO_KP[AURORA_KP]} indicate potential auroral activity at Berlin latitudes.\n"
        message += """<h3 id="note_act2"><strong>GEOMAGNETIC ACTIVITY SCALE<sup>[5]</sup></strong></h3><ul>"""
        message += self.get_storm_level_description_table()
        message += "</tbody></table>\n</ul>"
        message += self.footer()
        message += "</body></html>"

        return message.strip()

    def footer(self) -> str:
        return f"""
            <p><strong>DATA SOURCE:</strong> <a href='https://spaceweather.gfz-potsdam.de/'> https://spaceweather.gfz-potsdam.de/</a></p>
            <p><em>This is an automated alert from the Kp Index Monitoring System using GFZ Space Weather Forecast.</em></p>
            <hr>
            <p style="font-size: 12px; color: #888;">
            &copy; {datetime.now().year} GFZ Helmholtz Centre for Geosciences | GFZ Helmholtz-Zentrum für Geoforschung<br>
            The data/data products are provided “as-is” without warranty of any kind either expressed or implied, including but not limited to the implied warranties of merchantability, correctness and fitness for a particular purpose. The entire risk as to the quality and performance of the Data/data products is with the Licensee.

            In no event will GFZ be liable for any damages direct, indirect, incidental, or consequential, including damages for any lost profits, lost savings, or other incidental or consequential damages arising out of the use or inability to use the data/data products.

            """

    def _kp_html_table(self, record: pd.DataFrame, probabilities: pd.DataFrame) -> str:
        prev_message = ""
        prev_message += '<table style="border-collapse: collapse; margin: 5px 0; font-size: 16px;">\n'
        prev_message += '<thead><tr style="background-color: #f0f0f0;">'
        prev_message += '<th style="padding: 4px 6px; border: 1px solid #ddd; text-align: left; width: 120px; white-space: nowrap;">Time (UTC)</th>'
        prev_message += '<th style="padding: 4px 6px; border: 1px solid #ddd; text-align: center; width: 60px; white-space: nowrap;">Median Kp Index<a href="#note_median"><sub>[1]</sub></a></th>'
        prev_message += '<th style="padding: 4px 6px; border: 1px solid #ddd; text-align: center; width: 60px; white-space: nowrap;">Min Kp Index<a href="#note_min"><sub>[2]</sub></a></th>'
        prev_message += '<th style="padding: 4px 6px; border: 1px solid #ddd; text-align: center; width: 60px; white-space: nowrap;">Max Kp Index<a href="#note_max"><sub>[3]</sub></a></th>'
        prev_message += '<th style="padding: 4px 6px; border: 1px solid #ddd; text-align: center; width: 60px; white-space: nowrap;">Activity<a href="#note_act"><sub>[4]</sub></a><a href="#note_act2"><sub>[5]</sub></a></th>'
        prev_message += f'<th style="padding: 4px 6px; border: 1px solid #ddd; text-align: center; width: 80px; white-space: nowrap;">Probability (Kp &ge; {self.kp_threshold_str})</th>'
        prev_message += "</tr></thead>\n<tbody>\n"

        for _, record in record.iterrows():
            kp_val_max = np.round(record["maximum"], 2)
            kp_val_med = np.round(record["median"], 2)
            kp_val_min = np.round(record["minimum"], 2)
            _, level, color = self.get_status_level_color(kp_val_med)

            time_idx = record["Time (UTC)"]

            prev_message += "<tr>"
            prev_message += f'<td style="padding: 2px 4px; border: 1px solid #ddd; white-space: nowrap;"><strong>{record["Time (UTC)"].strftime("%Y-%m-%d %H:%M")}</strong></td>'
            prev_message += f'<td style="padding: 2px 4px; border: 1px solid #ddd; text-align: center; white-space: nowrap;"><strong>{DECIMAL_TO_KP[kp_val_med]}</strong></td>'
            prev_message += f'<td style="padding: 2px 4px; border: 1px solid #ddd; text-align: center; white-space: nowrap;"><strong>{DECIMAL_TO_KP[kp_val_min]}</strong></td>'
            prev_message += f'<td style="padding: 2px 4px; border: 1px solid #ddd; text-align: center; white-space: nowrap;"><strong>{DECIMAL_TO_KP[kp_val_max]}</strong></td>'
            prev_message += f'<td style="padding: 2px 4px; border: 1px solid #ddd; text-align: center; font-weight: bold; color: {color}; white-space: nowrap;">{level}</td>'
            prev_message += f'<td style="padding: 2px 4px; border: 1px solid #ddd; text-align: center; white-space: nowrap;"><strong>{probabilities.loc[time_idx, "Probability"]:.2f}</strong></td>'
            prev_message += "</tr>\n"
        prev_message += "</tbody></table>\n"
        prev_message += """
                        <div style="font-size: 14px; margin-top: 8px;">
                            <p id="note_median"><b>[1]</b> Median Kp Index: Median value of Kp Ensembles</p>
                            <p id="note_min"><b>[2]</b> Min Kp Index: Minimum value of Kp Ensembles</p>
                            <p id="note_max"><b>[3]</b> Max Kp Index: Maximum value of Kp Ensembles</p>
                            <p id="note_act"><b>[4]</b> Activity is based on Median Kp</p>
                        </div>
                        """

        return prev_message

    def create_summary_message(self, analysis: AnalysisResults) -> str:
        """
        Create formatted summary message for current Kp Index conditions.

        Parameters
        ----------
        analysis : AnalysisResults
            AnalysisResults containing analysis results from analyze_kp_data

        Returns
        -------
        str
            Formatted HTML summary message string ready for email
        """
        current_max = analysis["current_max_kp"]
        next_24h = analysis["next_24h_forecast"]
        probability_df = analysis["probability_df"]

        current_kp = analysis.next_24h_forecast["median"].iloc[0]
        status, _, color = self.get_status_level_color(current_kp)
        message = f"""<html><body>
        <h2><strong>SPACE WEATHER - Kp Index SUMMARY REPORT</strong></h2>

        <h3><strong>CURRENT STATUS:</strong> <span style="color: {color};">  {status}</span></h3>
        <ul>
            <li><strong>Report Time:</strong> {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")} UTC</li>
            <li><strong>Maximum Kp for 72 hours window:</strong> {DECIMAL_TO_KP[current_max]}</li>
            <li><strong>Total number of ensembles:</strong> {self.total_ensembles}</li>
        </ul>

        <h3><strong>NEXT 24 HOURS FORECAST:</strong></h3>
        <ul>
        """

        message += self._kp_html_table(next_24h, probability_df)

        message += "</tbody></table>\n"
        message += '<br><img src="cid:forecast_image" style="max-width:100%;">'
        message += """</ul><h3 id="note_act2"><strong>GEOMAGNETIC ACTIVITY SCALE<sup>[5]</sup></strong></h3><ul>"""
        message += self.get_storm_level_description_table()
        message += "</tbody></table>\n</ul>"
        message += self.footer()
        message += "</body></html>"

        return message.strip()

    def get_storm_level_description_table(self) -> str:
        table_html = ""
        table_html += '<table style="border-collapse: collapse; margin: 5px 0; font-size: 16px;">\n'
        table_html += '<thead><tr style="background-color: #f0f0f0;">'
        table_html += '<th style="padding: 4px 6px; border: 1px solid #ddd; text-align: left; width: 120px; white-space: nowrap;">Level</th>'
        table_html += '<th style="padding: 4px 6px; border: 1px solid #ddd; text-align: center; width: 60px; white-space: nowrap;">Kp Value</th>'
        table_html += '<th style="padding: 4px 6px; border: 1px solid #ddd; text-align: left; width: 400px; white-space: nowrap;">Description</th>'
        table_html += "</tr></thead>\n<tbody>\n"

        rows = [
            ("Quiet", "0-2", "Quiet conditions"),
            ("Unsettled to Active", "3-4", "Unsettled to Active conditions"),
            ("Minor Storm (G1)", "5", "Weak power grid fluctuations"),
            ("Moderate Storm (G2)", "6", "High-latitude power systems affected"),
            ("Strong Storm (G3)", "7", "Power systems may experience voltage corrections"),
            ("Severe Storm (G4)", "8", "Possible widespread voltage control problems"),
            ("Extreme Storm (G5)", "9", "Widespread power system voltage control problems"),
        ]

        for level, kp_value, desc in rows:
            table_html += "<tr>"
            table_html += f'<td style="padding: 2px 4px; border: 1px solid #ddd; white-space: nowrap;"><strong>{level}</strong></td>'
            table_html += f'<td style="padding: 2px 4px; border: 1px solid #ddd; text-align: center; white-space: nowrap;"><strong>{kp_value}</strong></td>'
            table_html += f'<td style="padding: 2px 4px; border: 1px solid #ddd; white-space: nowrap;">{desc}</td>'
            table_html += "</tr>\n"

        table_html += "</tbody></table>\n"
        return table_html

    def get_status_level_color(self, kp: float) -> tuple[str, str, str]:
        """Get geomagnetic status, level, and color based on Kp value.

        Parameters
        ----------
        kp : float
            Kp index value

        Returns
        -------
        status : str
            Geomagnetic activity status description
        level : str
            Geomagnetic storm level (e.g., [G1], [G2], etc.)
        color : str
            Hex color code representing severity
        """
        status = "UNKNOWN"
        level = "[?]"
        color = "#000000"
        if kp == 9:
            status = "EXTREME STORM CONDITIONS"
            level = "G5"
            color = "#FE0004"
        elif kp >= 8:
            status = "SEVERE STORM CONDITIONS"
            level = "G4"
            color = "#FE0004"
        elif kp >= 7:
            status = "STRONG STORM CONDITIONS"
            level = "G3"
            color = "#FD0007"
        elif kp >= 6:
            status = "MODERATE STORM CONDITIONS"
            level = "G2"
            color = "#FF4612"
        elif kp >= 5:
            status = "MINOR STORM CONDITIONS"
            level = "G1"
            color = "#FE801D"
        elif kp >= 4:
            status = "ACTIVE CONDITIONS"
            level = "ACTIVE"
            color = "#FFFA3D"
        else:
            status = "QUIET CONDITIONS"
            level = "QUIET"
            color = "#5cb85c"
        return status, level, color

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
            self.construct_and_send_email(recipients, subject, message)

            self.logger.info(f"Mail sent successfully to {len(recipients)} recipients")
            return True

        except Exception as e:
            self.logger.error(f"Error sending mail: {e}", exc_info=True)
            return False

    def should_send_alert(self, analysis: AnalysisResults) -> bool:
        """
        Determine if alert should be sent to avoid spam.

        Parameters
        ----------
        analysis : AnalysisResults
            AnalysisResults containing analysis results from analyze_kp_data

        Returns
        -------
        bool
            True if alert should be sent, False otherwise
        """
        if not analysis["alert_worthy"]:
            return False
        return True

        # # Avoid sending multiple alerts for the same high Kp period
        # current_time = pd.Timestamp.now(tz="UTC")
        # if self.last_alert_time:
        #     time_since_last_alert = (current_time - self.last_alert_time).total_seconds() / 3600
        #     if time_since_last_alert < 6:  # Don't send alerts more than once every 6 hours
        #         self.logger.info("Skipping alert - too soon since last alert")
        #         return False

        # return True

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
        df = self.fetch_kp_data()
        if df is None:
            return False
        analysis = self.analyze_kp_data(df)

        # Check if alert should be sent
        if self.should_send_alert(analysis):
            max_kp = analysis["current_max_kp"]
            subject = f"SPACE WEATHER ALERT: Kp Index {analysis['high_kp_records']['maximum'].max():.1f} Predicted"
            message = self.create_alert_message(analysis)

            email_sent = self.send_alert(subject, message)
            message_for_file = message.replace("cid:forecast_image", self.LOCAL_IMAGE_PATH)
            with open("index.html", "w") as f:
                f.write(message_for_file)

            if email_sent:
                self.last_alert_time = pd.Timestamp.now(tz="UTC")
                self.last_max_kp = max_kp
        else:
            self.logger.info(
                f"No alert needed - Current Kp: {analysis['current_max_kp']:.2f}, Threshold: {self.kp_threshold_str}"
            )

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
        self.logger.info("Generating Kp summary")

        df = self.fetch_kp_data()
        if df is None:
            self.logger.error("Failed to fetch data for summary")
            return False
        analysis = self.analyze_kp_data(df)
        subject = (
            f"Space Weather Summary Report - Current Median Kp: {analysis.next_24h_forecast['median'].iloc[0]:.1f}"
        )
        message = self.create_summary_message(analysis)

        message_for_file = message.replace("cid:forecast_image", self.LOCAL_IMAGE_PATH)
        with open("index.html", "w") as f:
            f.write(message_for_file)

        try:
            self.construct_and_send_email(recipients, subject, message)

            self.logger.info(f"Summary mail sent successfully to {len(recipients)} recipients")
            return True

        except Exception as e:
            self.logger.error(f"Error sending mail: {e}", exc_info=True)
            return False

    def construct_and_send_email(self, recipients: list[str], subject: str, message: str) -> None:
        # root message as multipart/related
        msg_root = MIMEMultipart("related")
        msg_root["From"] = "pager"
        msg_root["Reply-To"] = "jhawar@gfz.de"
        if len(recipients) == 1:
            msg_root["To"] = recipients[0]
        else:
            msg_root["Bcc"] = ", ".join(recipients)
        msg_root["Subject"] = subject

        msg_alternative = MIMEMultipart("alternative")
        msg_root.attach(msg_alternative)

        plain_text = "Your email client does not support HTML."
        msg_alternative.attach(MIMEText(plain_text, "plain"))

        msg_alternative.attach(MIMEText(message, "html"))
        with open(self.LOCAL_IMAGE_PATH, "rb") as f:
            img = MIMEImage(f.read())
            img.add_header("Content-ID", "<forecast_image>")
            img.add_header("Content-Disposition", "inline", filename="forecast_image.png")
            msg_root.attach(img)

        with smtplib.SMTP("localhost") as smtp:
            smtp.send_message(msg_root)

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
                self.logger.error(f"Error in monitoring loop: {e}", exc_info=True)
                time.sleep(300)  # Wait 5 minutes before retrying

    def run_continuous_summary(self) -> None:
        """
        Run continuous summary email sending at specified intervals.

        Sends summary emails at configured intervals indefinitely.
        Can be stopped with Ctrl+C (KeyboardInterrupt).
        """
        self.logger.info("Starting continuous Kp index summary emailing")
        self.logger.info(f"Summary interval: {self.config.check_interval_hours} hours")

        while True:
            try:
                self.send_summary_email()

                # Wait for next summary
                sleep_seconds = self.config.check_interval_hours * 3600
                self.logger.info(f"Waiting {self.config.check_interval_hours} hours until next summary...")
                time.sleep(sleep_seconds)

            except KeyboardInterrupt:
                self.logger.info("Summary emailing stopped by user")
                break
            except Exception as e:
                self.logger.error(f"Error in summary emailing loop: {e}", exc_info=True)
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

    parser.add_argument("--summary", action="store_true", help="Send summary email (works with --continuous)")

    args = parser.parse_args()

    config = MonitorConfig.from_yaml()
    monitor = KpMonitor(config)

    if args.test:
        subject = "Kp Monitor Test Email"
        message = "This is a test email from the Kp Index Monitoring System."

        logging.info("Testing email functionality...")
        success = monitor.send_alert(subject, message)
        logging.info(f"Summary email: {'SUCCESS' if success else 'FAILED'}")

    elif args.once:
        if args.summary:
            monitor.send_summary_email()
        else:
            monitor.run_single_check()

    elif args.continuous:
        if args.summary:
            monitor.run_continuous_summary()
        else:
            monitor.run_continuous_monitoring()


if __name__ == "__main__":
    main()
