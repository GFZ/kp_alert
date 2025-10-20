# Kp Index Space Weather Monitor

A Python-based monitoring system that tracks the Kp geomagnetic index from GFZ Potsdam and sends automated email alerts when space weather conditions exceed specified thresholds.

## Features

- **Real-time monitoring** of Kp geomagnetic index from GFZ ensemble forecast data
- **Configurable alert thresholds** with YAML-based configuration
- **Email notifications** via local SMTP with HTML formatting and embedded forecast images
- **Multiple operation modes**: single check (`--once`) and continuous monitoring (`--continuous`)
- **Comprehensive logging** with configurable levels and log folder management
- **Smart alert management** to prevent spam (6-hour cooldown between alerts)
- **Rich HTML emails** with detailed space weather information, probability tables, and forecast charts
- **Aurora watch notifications** for Kp ≥ 6+ conditions
- **NOAA scale integration** for geomagnetic storm classification

## Quick Start

## Installation

### Option 1: Development Installation

```bash
git clone https://github.com/GFZ/kp_alert.git
cd kp_alert
pip install -r requirements.txt
```

### Option 2: Package Installation

```bash
pip install -e .
```

This installs the `kp-alert` command-line tool globally.

### 1. Configure Settings

Copy `config.yaml.template` to customize your monitoring setup:

```bash
cp config.yaml.template config.yaml
```

```yaml
# Alert settings
kp_alert_threshold: 6.0 # Kp value to trigger alerts (0-9 scale)
check_interval_hours: 1 # Hours between checks in continuous mode

# Email recipients
recipients:
  - "spaceweather@yourorg.com"
  - "alerts@yourorg.com"

# Logging configuration
log_folder: "./logs" # Path to log folder
log_level: "INFO" # DEBUG, INFO, WARNING, ERROR

# Debug settings
debug_with_swpc: false # Use SWPC overplot images if true
```

### 2. Run Monitoring

**Single check:**

```bash
python -m src.kp_index_monitor --once
```

**Continuous monitoring:**

```bash
python -m src.kp_index_monitor --continuous
```

**Using the installed command-line tool (after `pip install`):**

```bash
kp-alert --once
kp-alert --continuous
```

## Configuration

### Configuration File

The system uses YAML configuration files for easy management. You can specify a custom config file using the `KP_MONITOR_CONFIG` environment variable:

```bash
export KP_MONITOR_CONFIG=/path/to/custom_config.yaml
python -m src.kp_index_monitor --once
```

### Configuration Options

| Parameter              | Type   | Description                | Valid Range              |
| ---------------------- | ------ | -------------------------- | ------------------------ |
| `kp_alert_threshold`   | float  | Kp value triggering alerts | 0.0 - 9.0                |
| `check_interval_hours` | float  | Hours between checks       | > 0.0                    |
| `recipients`           | list   | Email addresses for alerts | Valid email format       |
| `log_folder`           | string | Path to log folder         | Valid directory path     |
| `log_level`            | string | Logging verbosity          | DEBUG/INFO/WARNING/ERROR |
| `debug_with_swpc`      | bool   | Use SWPC comparison images | true/false               |

### Example Configurations

**Research Station (High Sensitivity):**

```yaml
kp_alert_threshold: 4.0
check_interval_hours: 1.0
recipients: ["operations@station.gov"]
log_folder: "./logs"
log_level: "DEBUG"
debug_with_swpc: false
```

**Power Grid Monitoring (Critical Events Only):**

```yaml
kp_alert_threshold: 6.0
check_interval_hours: 0.5
recipients: ["grid-ops@utility.com", "duty-manager@utility.com"]
log_folder: "./logs_production"
log_level: "INFO"
debug_with_swpc: true
```

## Operation Modes

### Single Check Mode

Run one monitoring check and exit:

```bash
python -m src.kp_index_monitor --once
# or
kp-alert --once
```

_Perfect for cron jobs or testing_

### Continuous Monitoring Mode

Run continuously with scheduled checks:

```bash
python -m src.kp_index_monitor --continuous
# or
kp-alert --continuous
```

_Ideal for dedicated monitoring servers_

## Email System Requirements

This system uses the **local Linux mail system** (localhost SMTP) to send emails. This approach is more reliable for server deployments than external SMTP.

### Setup Local Mail System

**Ubuntu/Debian:**

```bash
sudo apt-get install postfix mailutils
sudo dpkg-reconfigure postfix
```

**CentOS/RHEL:**

```bash
sudo yum install postfix mailx
sudo systemctl enable postfix
sudo systemctl start postfix
```

### Alternative: External SMTP

If you prefer external SMTP, modify the `send_alert()` method in `kp_index_monitor.py` to use your preferred SMTP server and authentication.

## Data Source and Format

### Source Information

- **Provider**: GFZ Helmholtz Centre for Geosciences
- **URL**: Internal GFZ data paths for ensemble forecast data
- **Update Frequency**: Every 3 hours (GFZ updates their forecast data)
- **Format**: CSV with ensemble forecast data

### Data Paths Used

The system accesses GFZ internal data paths:

- **CSV Data**: `/PAGER/FLAG/data/published/products/Kp/kp_product_file_SWIFT_LAST.csv`
- **Forecast Image**: `/PAGER/FLAG/data/published/kp_swift_ensemble_LAST.png`
- **SWPC Comparison Image**: `/PAGER/FLAG/data/published/kp_swift_ensemble_with_swpc_LAST.png`

### Forecast Data Structure

The latest ensemble predictions contain the following information:

#### Time Format

- **Time (UTC)**: Forecast time in dd-mm-yyyy HH:MM format

#### Statistical Measures

- **minimum**: Minimum forecasted Kp value
- **0.25-quantile**: Value such that 25% of forecasts are below this level
- **median**: Median forecasted Kp value
- **0.75-quantile**: Value such that 75% of forecasts are below this level
- **maximum**: Maximum forecasted Kp value

#### Probability Ranges

- **prob 4-5**: Probability of 4 ≤ Kp ≤ 5
- **prob 5-6**: Probability of 5 ≤ Kp ≤ 6
- **prob 6-7**: Probability of 6 ≤ Kp ≤ 7
- **prob 7-8**: Probability of 7 ≤ Kp ≤ 8
- **prob ≥ 8**: Probability of Kp ≥ 8

#### Ensemble Members

- **Individual ensemble members**: Indexed as `kp_i`, where i is a progressive integer number
- **Current ensemble size**: Varies between 12 and 20 members
- **Used for probability calculations**: Percentage of ensemble members exceeding thresholds

## Alert System

### Geomagnetic Storm Classification

The Kp index scale and corresponding geomagnetic storm levels:

| Kp Range | Classification      | NOAA Scale | Impact Level                             |
| -------- | ------------------- | ---------- | ---------------------------------------- |
| Kp 0-2   | Quiet               | -          | No impact                                |
| Kp 3-4   | Unsettled to Active | -          | Minor impact                             |
| Kp 5     | Minor Storm         | G1         | Weak power grid fluctuations             |
| Kp 6     | Moderate Storm      | G2         | High-latitude power systems affected     |
| Kp 7     | Strong Storm        | G3         | Power systems voltage corrections needed |
| Kp 8     | Severe Storm        | G4         | Widespread voltage control problems      |
| Kp 9     | Extreme Storm       | G5         | Complete power system blackouts possible |

### Sample Email

[Sample Email](http://htmlpreview.github.io/?https://github.com/GFZ/kp_alert/blob/main/assets/index.html)

## Server Deployment

### Using Cron for Automation

Add to crontab for automatic execution:

```bash
crontab -e

# Run single check every hour
0 * * * * cd /path/to/kp_alert && /usr/bin/python3 -m src.kp_index_monitor --once

# Or using the installed command
0 * * * * cd /path/to/kp_alert && kp-alert --once
```

### As a Systemd Service

Create `/etc/systemd/system/kp-monitor.service`:

```ini
[Unit]
Description=Kp Index Space Weather Monitor
After=network.target

[Service]
Type=simple
User=kp-monitor
WorkingDirectory=/opt/kp-alert
ExecStart=/usr/bin/python3 -m src.kp_index_monitor --continuous
Restart=always
RestartSec=300
Environment=KP_MONITOR_CONFIG=/opt/kp-alert/config.yaml

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl enable kp-monitor
sudo systemctl start kp-monitor
sudo systemctl status kp-monitor
```

## Testing and Verification

### Initial Setup Testing

1. **Test single monitoring check**:

   ```bash
   python -m src.kp_index_monitor --once
   ```

2. **Validate configuration**:
   ```bash
   python -c "from src.config import MonitorConfig; config = MonitorConfig.from_yaml(); print('Configuration valid!')"
   ```

### Troubleshooting

#### Common Issues

1. **Email sending fails**:

   - Check if local mail system (postfix) is running: `sudo systemctl status postfix`
   - Test mail system: `echo "Test" | mail -s "Test Subject" your-email@domain.com`
   - Check mail logs: `sudo tail -f /var/log/mail.log`

2. **Data fetch fails**:

   - Check GFZ internal network connectivity
   - Verify access to internal data paths
   - Check logs for specific error messages

3. **Configuration errors**:

   - Validate YAML syntax: `python -c "import yaml; yaml.safe_load(open('config.yaml'))"`
   - Check file permissions: `ls -la config.yaml`
   - Verify email format in recipients list

4. **Permission errors on server**:
   - Ensure proper file permissions: `chmod 644 config.yaml`
   - Run as appropriate user
   - Check systemd service user permissions

#### Log Files

Monitor system activity with timestamped log files:

```bash
# Watch real-time logs (adjust date as needed)
tail -f ./logs/kp_monitor_once_20251510.log

# Check for errors
grep ERROR ./logs/kp_monitor_*.log

# View recent activity
tail -50 ./logs/kp_monitor_*.log
```

### Configuration Validation

The system automatically validates configuration on startup:

- **Kp threshold**: Must be between 0-9
- **Check interval**: Must be positive
- **Email addresses**: Must be valid format
- **Log file**: Must be accessible path

Error messages will indicate specific validation failures.

## Security Considerations

- **Configuration files**: Keep `config.yaml` secure with appropriate file permissions (644 or 600)
- **Email security**: Uses local mail system to avoid storing external credentials
- **Service accounts**: Use dedicated user accounts for production deployment
- **Log management**: Monitor log files and implement log rotation
- **Network security**: Firewall rules for production servers

## Development and Contribution

### Project Structure

```
kp_alert/
├── src/
│   ├── __init__.py           # Package initialization
│   ├── config.py             # Configuration management with YAML support
│   └── kp_index_monitor.py   # Main monitoring application with typer CLI
├── config.yaml               # Main configuration file
├── config.yaml.template      # Configuration template
├── pyproject.toml            # Python project configuration
├── requirements.txt          # Python dependencies
└── README.md                 # Documentation
```

### Key Features

- **YAML Configuration**: Type-safe configuration with validation
- **Robust Error Handling**: Graceful handling of network and data issues
- **Smart Alert Logic**: 6-hour cooldown to prevent alert spam
- **Local SMTP**: No external credentials required
- **Rich HTML Emails**: Embedded forecast images and probability tables
- **Aurora Notifications**: Special alerts for Kp ≥ 6+ conditions
- **CLI Interface**: Typer-based command line interface with `--once` and `--continuous` modes
- **Flexible Installation**: Can be installed as a pip package with `kp-alert` command

## License and Attribution

This project is for educational and research purposes.

**Data Attribution**: Kp data provided by GFZ Helmholtz Centre for Geosciences.

**Authors**: Sahil Jhawar, Infant Ronald Reagan Johnson Amalraj

## Support

For issues and questions:

- GitHub Issues:
- Mail to the authors at (provided in `pyproject.toml`)
