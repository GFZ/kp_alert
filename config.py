# Space Weather Monitor Configuration
# Copy this file and customize with your settings

# Data Source
KP_CSV_URL = "https://spaceweather.gfz.de/fileadmin/Kp-Forecast/CSV/kp_product_file_FORECAST_PAGER_SWIFT_LAST.csv"

# Alert Settings
KP_ALERT_THRESHOLD = 5.0  # Kp value that triggers alerts
CHECK_INTERVAL_HOURS = 0.001  # How often to check (hours)

# Email Configuration
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
EMAIL_USER = "sahil.jhawar448@gmail.com"
EMAIL_PASSWORD = "sopc yzsx iwis ersb"

# Alert Recipients
ALERT_RECIPIENTS = ["sahil.jhawar448@gmail.com"]

# Logging
LOG_FILE = "kp_monitor.log"

# NOTE: Add this file to .gitignore to keep your credentials private!
