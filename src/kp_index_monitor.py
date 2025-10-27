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
from datetime import datetime, timedelta, timezone
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional, Tuple

import markdown
import numpy as np
import pandas as pd
import requests
import typer

from src.config import MonitorConfig


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

        def log_uncaught_exceptions(exc_type, exc_value, exc_traceback):
            if issubclass(exc_type, KeyboardInterrupt):
                sys.__excepthook__(exc_type, exc_value, exc_traceback)
                return
            logging.error("Uncaught exception", exc_info=(exc_type, exc_value, exc_traceback))

        sys.excepthook = log_uncaught_exceptions

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
            self.logger.info(f"Current UTC Time: {self.current_utc_time}")
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
            probability_df = probability_df.replace({"Probability": {1.0: 0.95}})
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
*This is an automated alert from the Kp Index Monitoring System using GFZ Space Weather Forecast.*

---

<small>
© {datetime.now().year} GFZ Helmholtz Centre for Geosciences | GFZ Helmholtz-Zentrum für Geoforschung  
The data/data products are provided "as-is" without warranty of any kind either expressed or implied, including but not limited to the implied warranties of merchantability, correctness and fitness for a particular purpose. The entire risk as to the quality and performance of the Data/data products is with the Licensee.
In no event will GFZ be liable for any damages direct, indirect, incidental, or consequential, including damages for any lost profits, lost savings, or other incidental or consequential damages arising out of the use or inability to use the data/data products.
</small>
            """

    def _kp_html_table(self, record: pd.DataFrame, probabilities: pd.DataFrame) -> str:
        """Generate markdown table for Kp index records."""
        table = f"""
| Time (UTC) | Probability (Kp ≥ {self.kp_threshold_str}) | Min Kp Index<sup>[<a href="#fn1">1</a>]</sup> | Max Kp Index<sup>[<a href="#fn2">2</a>]</sup> | Median Kp Index<sup>[<a href="#fn3">3</a>]</sup> | Activity<sup>[<a href="#fn4">4</a>][<a href="#fn5">5</a>]</sup> |
|------------|-------------------------------------------|------------------|------------------|---------------------|------------------|
"""
        for _, row in record.iterrows():
            kp_val_max = np.round(row["maximum"], 2)
            kp_val_med = np.round(row["median"], 2)
            kp_val_min = np.round(row["minimum"], 2)
            _, level_min, color_min = self.get_status_level_color(kp_val_min)
            _, level_max, color_max = self.get_status_level_color(kp_val_max)

            time_idx = row["Time (UTC)"]
            prob = probabilities.loc[time_idx, "Probability"]

            time_str = row["Time (UTC)"].strftime("%Y-%m-%d %H:%M")
            prob_str = f"{prob * 100:.0f}%"
            activity_str = f'<span style="color: {color_min};">{level_min}</span> - <span style="color: {color_max};">{level_max}</span>'

            table += f"| **{time_str}** | **{prob_str}** | **{DECIMAL_TO_KP[kp_val_min]}** | **{DECIMAL_TO_KP[kp_val_max]}** | **{DECIMAL_TO_KP[kp_val_med]}** | {activity_str} |\n"

        table += """
<a id="fn1"></a><sup>1</sup> Min Kp Index: Minimum value of Kp Ensembles  
<a id="fn2"></a><sup>2</sup> Max Kp Index: Maximum value of Kp Ensembles  
<a id="fn3"></a><sup>3</sup> Median Kp Index: Median value of Kp Ensembles  
<a id="fn4"></a><sup>4</sup> Geomagnetic Activity Level based on Min-Max range
"""
        return table

    def get_observed_kp(self, start: pd.Timestamp) -> Tuple[str, float] | None:
        """
        Fetch observed Kp index data from GFZ API.

        Parameters
        ----------
        start : pd.Timestamp
            Start time for fetching observed Kp data

        Returns
        -------
        Tuple[str, float] or None
            Tuple with datetime and Kp value if found, None otherwise

        """
        try:
            max_attempts = 8  # search back up to 24 hours (8 * 3-hou)
            attempts = 0

            while attempts < max_attempts:
                start_date_str = start.strftime("%Y-%m-%dT%H:%M:%SZ")
                end_date_str = (start + timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
                url = f"https://kp.gfz.de/app/json/?start={start_date_str}&end={end_date_str}&index=Kp"

                self.logger.info(f"Fetching observed Kp data from {start_date_str} to {end_date_str}")

                response = requests.get(url)
                response.raise_for_status()

                data = response.json()

                if len(data.get("Kp", [])) > 0:
                    self.logger.info(f"Observed Kp data found for {data['datetime'][0]} : {data['Kp'][0]}")
                    return data["datetime"][0], data["Kp"][0]

                else:
                    self.logger.warning(f"No observed Kp data found for {start_date_str}, shifting 3 hours back")
                    start -= timedelta(hours=3)
                    attempts += 1

            self.logger.warning("No observed Kp data found after multiple shifts")
            return None

        except Exception as e:
            self.logger.error(f"Error fetching observed Kp data: {e}", exc_info=True)
            return None

    def create_message(self, analysis: AnalysisResults) -> str:
        """
        Create formatted alert message for high Kp conditions using Markdown.

        Parameters
        ----------
        analysis : `AnalysisResults`
            `AnalysisResults` containing analysis results from analyze_kp_data

        Returns
        -------
        message : str
            Formatted Markdown alert message
        """
        high_records = analysis["high_kp_records"]
        probability_df = analysis["probability_df"]
        probability_df = probability_df[probability_df.index >= self.current_utc_time]
        current_kp = analysis.next_24h_forecast["median"].iloc[0]
        status, _, _ = self.get_status_level_color(current_kp)

        max_values = analysis["max_df"]

        prob_at_time = 24  # hours
        target_time = self.current_utc_time + pd.Timedelta(hours=prob_at_time)
        nearest_idx = target_time.round("3h")
        high_prob_value = probability_df[:nearest_idx]["Probability"].max()

        threshold_status, threshold_level, _ = self.get_status_level_color(self.config.kp_alert_threshold)

        max_kp_at_finite_time = np.round(max_values.max(), 2)

        max_kp_at_finite_time_status, _, _ = self.get_status_level_color(max_kp_at_finite_time)
        mask = probability_df["Probability"] >= 0.4
        if mask.any():
            start_time = probability_df.index[mask][0]
            end_time = probability_df.index[mask][-1]
        else:
            start_time = high_records["minimum"].idxmax()
            end_time = high_records["maximum"].idxmax()

        observed_time, observed_kp = self.get_observed_kp(analysis.next_24h_forecast.index[0])
        prob_at_start_time = probability_df.loc[start_time]["Probability"]

        if observed_kp is not None:
            observed_status, _, _ = self.get_status_level_color(observed_kp)
        else:
            observed_status = "DATA NOT AVAILABLE YET"

        start_time_kp_min_status, _, _ = self.get_status_level_color(high_records.loc[start_time]["minimum"].min())
        end_time_kp_max_status, _, _ = self.get_status_level_color(high_records.loc[end_time]["maximum"].max())

        if start_time == end_time:
            message_prefix = f"""At {start_time.strftime("%Y-%m-%d %H:%M")} UTC"""
        else:
            message_prefix = (
                f"""From {start_time.strftime("%Y-%m-%d %H:%M")} UTC to {end_time.strftime("%Y-%m-%d %H:%M")} UTC"""
            )
        if observed_time != analysis.next_24h_forecast.index[0]:
            obs_message_prefix = f""" (Observed Kp data available up to {datetime.strptime(observed_time.strip(), "%Y-%m-%dT%H:%M:%SZ").strftime("%Y-%m-%d %H:%M")} UTC)"""
        else:
            obs_message_prefix = ""

        message = f"""<h2 style="color: #d9534f;">SPACE WEATHER ALERT - {threshold_status} ({threshold_level}) Predicted</h2>


### {message_prefix} Kp is expected to be above {self.config.kp_alert_threshold} ({threshold_level}) with ≥ {prob_at_start_time * 100:.0f}% probability with {start_time_kp_min_status.replace("CONDITIONS", "")} to {end_time_kp_max_status}.

**Current Predicted Conditions:** {status.replace("CONDITIONS", "")}
**Current Observed Conditions:** {observed_status.replace("CONDITIONS", "")} {obs_message_prefix}

## **ALERT SUMMARY**

- **Alert sent at:** {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")} UTC
- **Maximum Kp ≥ {DECIMAL_TO_KP[max_kp_at_finite_time]} with {max_kp_at_finite_time_status} may occur** {max_values.idxmax().strftime("%Y-%m-%d %H:%M")} UTC onwards
- **{high_prob_value * 100:.0f}% Probability of {threshold_status} ({threshold_level}) within next {prob_at_time} hours**

![Forecast Image](cid:forecast_image)

## **HIGH Kp INDEX PERIODS Predicted (Kp ≥ {threshold_level})**

"""
        message += self._kp_html_table(high_records, probability_df)

        AURORA_KP = 6.33
        high_records_above_threshold = high_records[
            (high_records["minimum"].astype(float) >= AURORA_KP)
            | (high_records["median"].astype(float) >= AURORA_KP)
            | (high_records["maximum"].astype(float) >= AURORA_KP)
        ]

        if not high_records_above_threshold.empty:
            message += f"""
## **AURORA WATCH:**

**Note:** Kp ≥ {DECIMAL_TO_KP[AURORA_KP]} indicate potential auroral activity at Berlin latitudes.

"""

        message += """## GEOMAGNETIC ACTIVITY SCALE <a id="fn5"></a><sup>5</sup>"""
        message += self.get_storm_level_description_table()
        message += "\n"
        message += self.footer()

        return message.strip()

    def create_subject(self, analysis: AnalysisResults) -> str:
        """
        Create email subject line based on analysis results.

        Parameters
        ----------
        analysis : `AnalysisResults`
            `AnalysisResults` containing analysis results from analyze_kp_data

        Returns
        -------
        subject : str
            Email subject line
        """
        _, level_min, _ = self.get_status_level_color(analysis["high_kp_records"]["minimum"].max())
        _, level_max, _ = self.get_status_level_color(analysis["high_kp_records"]["maximum"].max())

        subject = f"Predicted Geomagnetic Activity from {level_min} - {level_max}"
        return subject.strip()

    def get_storm_level_description_table(self) -> str:
        """Generate markdown table for geomagnetic storm levels."""
        G1 = "[NOAA [G1]](https://www.swpc.noaa.gov/noaa-scales-explanation#:~:text=G%201)"
        G2 = "[NOAA [G2]](https://www.swpc.noaa.gov/noaa-scales-explanation#:~:text=G%202)"
        G3 = "[NOAA [G3]](https://www.swpc.noaa.gov/noaa-scales-explanation#:~:text=G%203)"
        G4 = "[NOAA [G4]](https://www.swpc.noaa.gov/noaa-scales-explanation#:~:text=G%204)"
        G5 = "[NOAA [G5]](https://www.swpc.noaa.gov/noaa-scales-explanation#:~:text=G%205)"

        rows = [
            ("Quiet", "0-3", "Quiet conditions"),
            ("Active", "4", "Moderate geomagnetic activity"),
            ("Minor Storm (G1)", "5", f"Weak power grid fluctuations. For more details see {G1}"),
            ("Moderate Storm (G2)", "6", f"High-latitude power systems affected. For more details see {G2}"),
            ("Strong Storm (G3)", "7", f"Power systems may need voltage corrections. For more details see {G3}"),
            ("Severe Storm (G4)", "8", f"Possible widespread voltage control problems. For more details see {G4}"),
            ("Extreme Storm (G5)", "9", f"Widespread power system voltage control problems. For more details see {G5}"),
        ]

        table = """
| Level | Kp Value | Description |
|-------|----------|-------------|
"""
        for level, kp_value, desc in rows:
            table += f"| **{level}** | **{kp_value}** | {desc} |\n"

        return table

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
        current_time = pd.Timestamp.now(tz="UTC")
        if self.last_alert_time:
            time_since_last_alert = (current_time - self.last_alert_time).total_seconds() / 3600
            if time_since_last_alert < 6:
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

            message = self.create_message(analysis)
            subject = self.create_subject(analysis)

            email_sent = self.send_alert(subject, message)
            _ = self.copy_image()
            message_for_file = markdown.markdown(
                message.replace("cid:forecast_image", self.LOCAL_IMAGE_PATH),
                extensions=["tables", "fenced_code", "footnotes", "nl2br"],
            )
            html_output = self.basic_html_format(message_for_file)
            with open("index.html", "w") as f:
                f.write(html_output)

            if email_sent:
                self.last_alert_time = pd.Timestamp.now(tz="UTC")
                self.last_max_kp = max_kp
        else:
            self.logger.info(
                f"No alert needed - Current Kp: {analysis['max_kp']:.2f}, Threshold: {self.kp_threshold_str}"
            )

        return True

    def construct_and_send_email(self, recipients: list[str], subject: str, message: str) -> None:
        """Construct and send an email with HTML content and embedded image.

        Parameters
        ----------
        recipients : list[str]
            List of recipient email addresses
        subject : str
            Email subject line
        message : str
            Email message content (Markdown formatted, will be converted to HTML)
        """
        html_message = markdown.markdown(
            message,
            extensions=[
                "tables",
                "fenced_code",
                "footnotes",
                "nl2br",
            ],
        )
        html_message = self.basic_html_format(html_message)

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

        msg_alternative.attach(MIMEText(html_message, "html"))
        with open(self.LOCAL_IMAGE_PATH, "rb") as f:
            img = MIMEImage(f.read())
            img.add_header("Content-ID", "<forecast_image>")
            img.add_header("Content-Disposition", "inline", filename="forecast_image.png")
            msg_root.attach(img)

        with smtplib.SMTP("localhost") as smtp:
            smtp.send_message(msg_root)

    def basic_html_format(self, message: str) -> str:
        formatting = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <style>
                    body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #000000; max-width: 1200px; margin: 0 auto; padding: 20px; }}
                    table {{ border-collapse: collapse; margin: 20px 0; width: 100%; }}
                    th, td {{ padding: 8px 12px; border: 1px solid #ddd; text-align: left; }}
                    th {{ background-color: #f0f0f0; font-weight: bold; }}
                    img {{ max-width: 100%; height: auto; }}
                    h1 {{ color: #d9534f; }}
                    h2 {{ color: #5bc0de; margin-top: 30px; }}
                    h3 {{ color: #000000; }}
                    small {{ font-size: 12px; color: #333; }}
                    hr {{ border: 0; border-top: 1px solid #ddd; margin: 20px 0; }}
                </style>
            </head>
            <body>
            {message}
            </body>
            </html>
            """
        return formatting

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


app = typer.Typer(help="Kp Index Space Weather Monitor", add_completion=False, pretty_exceptions_enable=False)


@app.command()
def main(
    once: bool = typer.Option(False, "--once", help="Run single check and exit"),
    continuous: bool = typer.Option(False, "--continuous", help="Run continuous monitoring"),
):
    """
    Main function with command line interface.
    """
    selected = [flag for flag in (once, continuous) if flag]
    if len(selected) == 0:
        raise typer.BadParameter("One of --once or --continuous must be specified")
    if len(selected) > 1:
        raise typer.BadParameter(
            "Options --once and --continuous are mutually exclusive i.e., only one can be selected."
        )

    config = MonitorConfig.from_yaml()
    log_suffix = "once" if once else "continuous"
    monitor = KpMonitor(config, log_suffix=log_suffix)

    if once:
        monitor.run_single_check()

    elif continuous:
        monitor.run_continuous_monitoring()


if __name__ == "__main__":
    app()
