#!/usr/bin/env python3
"""
Kp Index Space Weather Monitor

A monitoring system that tracks the Kp geomagnetic index from GFZ Potsdam
and sends automated email alerts when space weather conditions exceed specified thresholds.

Data Source: GFZ German Research Centre for Geosciences

"""

import logging
import re
import shutil
import smtplib
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import typer

from src.config import MonitorConfig


def log_uncaught_exceptions(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    logging.error("Uncaught exception", exc_info=(exc_type, exc_value, exc_traceback))


sys.excepthook = log_uncaught_exceptions


@dataclass
class AnalysisResults:
    """
    AnalysisResults containing analysis results with keys:

    Parameters
    ----------
    max_kp : float
        Maximum Kp value in current forecast
    threshold_exceeded: bool
        Boolean indicating if threshold exceeded
    high_kp_records : pd.DataFrame
        Records above alert threshold
    next_24h_forecast : pd.DataFrame
        Forecast for next 24 hours
    alert_worthy : bool
        Boolean indicating if alert should be sent
    probability_df : pd.DataFrame
        DataFrame containing probability of Kp exceeding threshold
    """

    max_kp: float
    max_df: pd.Series
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
    IMAGE_PATH_SWPC = "/PAGER/FLAG/data/published/kp_swift_ensemble_with_swpc_LAST.png"
    CSV_PATH = "/PAGER/FLAG/data/published/products/Kp/kp_product_file_SWIFT_LAST.csv"

    def __init__(self, config: MonitorConfig, log_suffix: str = "") -> None:
        self.last_alert_time = None
        self.last_max_kp = 0
        self.config = config
        self.log_folder = Path(self.config.log_folder)
        self.debug_with_swpc = self.config.debug_with_swpc
        self.log_folder.mkdir(parents=True, exist_ok=True)
        self.config.kp_alert_threshold = np.round(self.config.kp_alert_threshold, 2)
        self.kp_threshold_str = DECIMAL_TO_KP[self.config.kp_alert_threshold]
        self.LOCAL_IMAGE_PATH = self.copy_image()
        self.current_utc_time = pd.Timestamp(datetime.now(timezone.utc))
        self.log_suffix = log_suffix
        self.setup_logging()

    def copy_image(self) -> str:
        """
        Copies the appropriate Kp forecast image to the current directory.

        Returns
        -------
        str
            Path to the copied image file.
        """
        if self.debug_with_swpc:
            return shutil.copy2(self.IMAGE_PATH_SWPC, "./kp_swift_ensemble_with_swpc_LAST.png")
        return shutil.copy2(self.IMAGE_PATH, "./kp_swift_ensemble_LAST.png")

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
                    self.log_folder
                    / f"kp_monitor_{self.log_suffix}_{datetime.now(timezone.utc).strftime('%Y%d%m')}.log"
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
            df = pd.read_csv(self.CSV_PATH)

            df["Time (UTC)"] = pd.to_datetime(df["Time (UTC)"], format="%d-%m-%Y %H:%M", dayfirst=True, utc=True)
            df.index = df["Time (UTC)"]
            self.logger.info(f"Successfully fetched {len(df)} records")
            return df

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
        `AnalysisResults`
            `AnalysisResults` containing analysis results with keys as described in the `AnalysisResults` dataclass
        """
        try:
            # Get current maximum values
            max_values = df[df.index >= self.current_utc_time]["maximum"]
            max: float = np.round(max_values.max(), 2)

            self.ensembles = [col for col in df.columns if re.match(r"kp_\d+", col)]
            self.total_ensembles = len(self.ensembles)
            probability = np.sum(df[self.ensembles] >= self.config.kp_alert_threshold, axis=1) / self.total_ensembles
            high_kp_records = df[df["maximum"].astype(float) >= self.config.kp_alert_threshold].copy()
            high_kp_records = high_kp_records[high_kp_records["Time (UTC)"] >= self.current_utc_time].copy()
            next_24h = df[df["Time (UTC)"] >= self.current_utc_time].head(9).copy()

            high_kp_records["Time (UTC)"] = pd.to_datetime(high_kp_records["Time (UTC)"], utc=True)
            next_24h["Time (UTC)"] = pd.to_datetime(next_24h["Time (UTC)"], utc=True)

            probability_df = pd.DataFrame({"Time (UTC)": df["Time (UTC)"], "Probability": probability})
            probability_df.index = probability_df["Time (UTC)"]
            probability_df.drop(columns=["Time (UTC)"], inplace=True)

            analysis = AnalysisResults(
                max_kp=max,
                max_df=max_values,
                threshold_exceeded=max > self.config.kp_alert_threshold,
                high_kp_records=high_kp_records.round(2),
                next_24h_forecast=next_24h.round(2),
                alert_worthy=len(high_kp_records) > 0,
                probability_df=probability_df.round(2),
            )

            self.logger.info(
                f"Analysis complete - Current Kp: {DECIMAL_TO_KP[max]}, Alert: {analysis['alert_worthy']}, Threshold: {self.kp_threshold_str}"
            )
            return analysis

        except Exception as e:
            self.logger.error(f"Error analyzing data: {e}", exc_info=True)
            return {"alert_worthy": False, "max_kp": 0}

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
        prev_message += f'<th style="padding: 4px 6px; border: 1px solid #ddd; text-align: center; width: 80px; white-space: nowrap;">Probability (Kp &ge; {self.kp_threshold_str})</th>'

        prev_message += '<th style="padding: 4px 6px; border: 1px solid #ddd; text-align: center; width: 60px; white-space: nowrap;">Min Kp Index<a href="#note_min"><sub>[1]</sub></a></th>'

        prev_message += '<th style="padding: 4px 6px; border: 1px solid #ddd; text-align: center; width: 60px; white-space: nowrap;">Max Kp Index<a href="#note_max"><sub>[2]</sub></a></th>'

        prev_message += '<th style="padding: 4px 6px; border: 1px solid #ddd; text-align: center; width: 60px; white-space: nowrap;">Median Kp Index<a href="#note_median"><sub>[3]</sub></a></th>'

        prev_message += '<th style="padding: 4px 6px; border: 1px solid #ddd; text-align: center; width: 60px; white-space: nowrap;">Median Activity<a href="#note_act"><sub>[4]</sub></a></th>'
        prev_message += "</tr></thead>\n<tbody>\n"

        for _, record in record.iterrows():
            kp_val_max = np.round(record["maximum"], 2)
            kp_val_med = np.round(record["median"], 2)
            kp_val_min = np.round(record["minimum"], 2)
            _, level, color = self.get_status_level_color(kp_val_med)

            time_idx = record["Time (UTC)"]

            prev_message += "<tr>"
            prev_message += f'<td style="padding: 2px 4px; border: 1px solid #ddd; white-space: nowrap;"><strong>{record["Time (UTC)"].strftime("%Y-%m-%d %H:%M")}</strong></td>'
            prev_message += f'<td style="padding: 2px 4px; border: 1px solid #ddd; text-align: center; white-space: nowrap;"><strong>{probabilities.loc[time_idx, "Probability"]:.2f}</strong></td>'
            prev_message += f'<td style="padding: 2px 4px; border: 1px solid #ddd; text-align: center; white-space: nowrap;"><strong>{DECIMAL_TO_KP[kp_val_min]}</strong></td>'
            prev_message += f'<td style="padding: 2px 4px; border: 1px solid #ddd; text-align: center; white-space: nowrap;"><strong>{DECIMAL_TO_KP[kp_val_max]}</strong></td>'
            prev_message += f'<td style="padding: 2px 4px; border: 1px solid #ddd; text-align: center; white-space: nowrap;"><strong>{DECIMAL_TO_KP[kp_val_med]}</strong></td>'
            prev_message += f'<td style="padding: 2px 4px; border: 1px solid #ddd; text-align: center; font-weight: bold; color: {color}; white-space: nowrap;">{level}</td>'
            prev_message += "</tr>\n"
        prev_message += "</tbody></table>\n"
        prev_message += """
                        <div style="font-size: 14px; margin-top: 8px;">
                            <p id="note_min"><b>[1]</b> Min Kp Index: Minimum value of Kp Ensembles</p>
                            <p id="note_max"><b>[2]</b> Max Kp Index: Maximum value of Kp Ensembles</p>
                            <p id="note_median"><b>[3]</b> Median Kp Index: Median value of Kp Ensembles</p>
                        </div>
                        """

        return prev_message

    def create_alert_message(self, analysis: AnalysisResults) -> str:
        """
        Create formatted alert message for high Kp conditions.

        Parameters
        ----------
        analysis : `AnalysisResults`
            `AnalysisResults` containing analysis results from analyze_kp_data

        Returns
        -------
        str
            Formatted HTML alert message s944059tring ready for email
        """
        high_records = analysis["high_kp_records"]
        probability_df = analysis["probability_df"]
        current_kp = analysis.next_24h_forecast["median"].iloc[0]
        status, _, color = self.get_status_level_color(current_kp)

        max_values = analysis["max_df"]
        time_diff = np.ceil((max_values.idxmax() - self.current_utc_time).total_seconds() / 3600)

        prob_at_time = 24  # hours
        target_time = self.current_utc_time + pd.Timedelta(hours=prob_at_time)
        nearest_idx = probability_df.index.get_indexer([target_time], method="bfill")[0]
        prob_value = probability_df.iloc[nearest_idx]["Probability"]

        message = f"""<html><body>
                    <h2><strong>SPACE WEATHER ALERT - Kp Index &ge; {self.kp_threshold_str} Predicted</strong></h2>
                    <h3><strong>ALERT SUMMARY</strong></h3>
                    <ul>
                        <li><strong>Current Status: <span style="color: {color};">  {status}</span> </strong></li>
                        <li><strong>Alert Time:</strong> {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")} UTC</li>
                        <li><strong>Maximum Kp for next {time_diff} hours:</strong> {DECIMAL_TO_KP[np.round(max_values.max(), 2)]}</li>
                        <li><strong>{prob_value * 100:.2f}% Probability of Kp &ge; {self.kp_threshold_str} in next {prob_at_time} hours</strong></li>
                    </ul>
                    <h3><strong>HIGH Kp INDEX PERIODS Predicted (Kp &ge; {self.kp_threshold_str})</strong></h3>
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
            message += f"<p>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;<strong>Note:</strong> Kp &ge; {DECIMAL_TO_KP[AURORA_KP]} indicate potential auroral activity at Berlin latitudes.\n"
        message += """<h3 id="note_act"><strong>GEOMAGNETIC ACTIVITY SCALE<sup>[4]</sup></strong></h3><ul>"""
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

        G1 = "<a href='https://www.swpc.noaa.gov/noaa-scales-explanation#:~:text=G%201'>NOAA [G1]</a>"
        G2 = "<a href='https://www.swpc.noaa.gov/noaa-scales-explanation#:~:text=G%202'>NOAA [G2]</a>"
        G3 = "<a href='https://www.swpc.noaa.gov/noaa-scales-explanation#:~:text=G%203'>NOAA [G3]</a>"
        G4 = "<a href='https://www.swpc.noaa.gov/noaa-scales-explanation#:~:text=G%204'>NOAA [G4]</a>"
        G5 = "<a href='https://www.swpc.noaa.gov/noaa-scales-explanation#:~:text=G%205'>NOAA [G5]</a>"

        rows = [
            ("Quiet", "0-3", "Quiet conditions"),
            ("Active", "4", "Moderate geomagnetic activity"),
            ("Minor Storm (G1)", "5", f"Weak power grid fluctuations. For more details see {G1}"),
            ("Moderate Storm (G2)", "6", f"High-latitude power systems affected. For more details see {G2}"),
            ("Strong Storm (G3)", "7", f"Power systems may need voltage corrections. For more details see {G3}"),
            ("Severe Storm (G4)", "8", f"Possible widespread voltage control problems. For more details see {G4}"),
            ("Extreme Storm (G5)", "9", f"Widespread power system voltage control problems. For more details see {G5}"),
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
            status = "MODERATE CONDITIONS"
            level = "MODERATE"
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
        # # Avoid sending multiple alerts for the same high Kp period
        current_time = pd.Timestamp.now(tz="UTC")
        if self.last_alert_time:
            time_since_last_alert = (current_time - self.last_alert_time).total_seconds() / 3600
            if time_since_last_alert < 6:  # Don't send alerts more than once every 6 hours
                self.logger.warning("Skipping alert - too soon since last alert")
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
        self.logger.info("Kp Index check")
        df = self.fetch_kp_data()
        if df is None:
            return False
        analysis = self.analyze_kp_data(df)

        if self.should_send_alert(analysis):
            max_kp = analysis["max_kp"]
            subject = (
                f"SPACE WEATHER ALERT: Kp Index {DECIMAL_TO_KP[analysis['high_kp_records']['maximum'].max()]} Predicted"
            )
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
                f"No alert needed - Current Kp: {analysis['max_kp']:.2f}, Threshold: {self.kp_threshold_str}"
            )

        return True

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
                time.sleep(300)


app = typer.Typer(help="Kp Index Space Weather Monitor", add_completion=False)


@app.command()
def main(
    once: bool = typer.Option(False, "--once", help="Run single check and exit"),
    continuous: bool = typer.Option(False, "--continuous", help="Run continuous monitoring"),
    test: bool = typer.Option(False, "--test", help="Test email functionality"),
):
    """
    Main function with command line interface.
    """
    selected = [flag for flag in (once, continuous, test) if flag]
    if len(selected) == 0:
        raise typer.BadParameter("One of --once, --continuous, or --test must be specified")
    if len(selected) > 1:
        raise typer.BadParameter(
            "Options --once, --continuous, and --test are mutually exclusive i.e., only one can be selected."
        )

    config = MonitorConfig.from_yaml()
    log_suffix = "once" if once else "continuous" if continuous else "test"
    monitor = KpMonitor(config, log_suffix=log_suffix)

    if test:
        subject = "Kp Monitor Test Email"
        message = "This is a test email from the Kp Index Monitoring System."
        logging.info("Testing email functionality...")
        success = monitor.send_alert(subject, message)
        logging.info(f"Summary email: {'SUCCESS' if success else 'FAILED'}")

    elif once:
        monitor.run_single_check()

    elif continuous:
        monitor.run_continuous_monitoring()


if __name__ == "__main__":
    app()
