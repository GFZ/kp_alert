# Kp Index Space Weather Monitor

A Python-based monitoring system that tracks the Kp geomagnetic index from GFZ Space weather and sends automated email alerts when space weather conditions exceed specified thresholds.

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure Email Settings

Copy and edit the configuration file:

```bash
cp config.py my_config.py
```

### 3. Test Email Functionality

```bash
python kp_index_monitor.py --test
```

### 4. Run Single Check

```bash
python kp_index_monitor.py --once
```

### 5. Start Continuous Monitoring

```bash
python kp_index_monitor.py --continuous
```

## Configuration

Edit `config.py` to customize system settings:

### Email Settings

**For Gmail:**
```python
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
EMAIL_USER = "your_email@gmail.com"
EMAIL_PASSWORD = "your_app_password"  # Use App Password, not regular password
```

**For Outlook:**
```python
SMTP_SERVER = "smtp-mail.outlook.com"
SMTP_PORT = 587
EMAIL_USER = "your_email@outlook.com"
EMAIL_PASSWORD = "your_password"
```

### Alert Recipients
```python
ALERT_RECIPIENTS = [
    "spaceweather-team@institution.edu",
    "alert1@institution.edu",
    "alert2@institution.edu"
]
```

### Monitoring Settings
```python
KP_ALERT_THRESHOLD = 5.0  # Alert when Kp exceeds this value
CHECK_INTERVAL_HOURS = 3  # Check interval in hours
```

## Operation Modes

### Single Check Mode
Run one monitoring check and exit:
```bash
python kp_index_monitor.py --once
```

### Continuous Monitoring Mode
Run continuously with scheduled checks:
```bash
python kp_index_monitor.py --continuous
```

### Test Mode
Test email functionality:
```bash
python kp_index_monitor.py --test
```

### Summary Email Mode
Send current space weather summary to a specific email:
```bash
python kp_index_monitor.py --summary --email scientist@university.edu
```

## Data Source and Format

### Source Information
- **Provider**: GFZ German Research Centre for Geosciences
- **URL**: https://spaceweather.gfz.de/fileadmin/Kp-Forecast/CSV/
- **Update Frequency**: Every 3 hours. ##todo check the code for this use
- **Format**: CSV with ensemble forecast data

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
- **Individual ensemble members**: Indexed by _i, where i is a progressive integer number
- **Current ensemble size**: Varies between 12 and 20 members

## Alert System

### Geomagnetic Storm Classification

The Kp index scale and corresponding geomagnetic storm levels:

| Kp Range | Classification | NOAA Scale | Impact Level |
|----------|---------------|------------|--------------|
| Kp 0-2   | Quiet         | -          | No impact    |
| Kp 3-4   | Unsettled to Active | -    | Minor impact |
| Kp 5     | Minor Storm   | G1         | Weak power grid fluctuations |
| Kp 6     | Moderate Storm | G2        | High-latitude power systems affected |
| Kp 7     | Strong Storm  | G3         | Power systems voltage corrections needed |
| Kp 8     | Severe Storm  | G4         | Widespread voltage control problems |
| Kp 9     | Extreme Storm | G5         | Complete power system blackouts possible |

### Sample Alert Email

```
SPACE WEATHER ALERT - High Kp Index Detected

ALERT SUMMARY:
• Current Maximum Kp Index: 6.33
• Alert Threshold: 5.0
• Alert Time: 2025-01-10 15:30:00 UTC

HIGH Kp PERIODS DETECTED:
• 2025-01-10 15:00:00 UTC: Kp = 6.33
• 2025-01-10 18:00:00 UTC: Kp = 5.67

GEOMAGNETIC STORM LEVELS:
• Kp 5: Minor geomagnetic storm (G1)
• Kp 6: Moderate geomagnetic storm (G2)
• Kp 7: Strong geomagnetic storm (G3)
• Kp 8: Severe geomagnetic storm (G4)
• Kp 9: Extreme geomagnetic storm (G5)

POTENTIAL IMPACTS:
• Satellite operations may be affected
• Radio communications may experience disruption
• Aurora activity may be visible at lower latitudes
• Power grid fluctuations possible
```

### Sample Summary Email

```
SPACE WEATHER SUMMARY REPORT

CURRENT STATUS: MODERATE STORM CONDITIONS [G2]
• Report Time: 2025-01-10 15:30:00 UTC
• Current Maximum Kp: 6.2
• Alert Threshold: 5.0

FORECAST DATA SUMMARY:
The latest ensemble predictions contain the following information:
• Time in UTC format: dd-mm-yyyy HH:MM
• Minimum, 0.25-quantile, median, 0.75-quantile, maximum forecasted values
• Probability ranges for different Kp levels
• Individual ensemble members (currently varies between 12-20 members)

NEXT 24 HOURS FORECAST:
• 2025-01-10 15:00:00 UTC: Kp = 6.2 [ALERT]
• 2025-01-10 18:00:00 UTC: Kp = 5.8 [ALERT]
• 2025-01-10 21:00:00 UTC: Kp = 4.3 [ACTIVE]
• 2025-01-11 00:00:00 UTC: Kp = 3.1 [QUIET]

GEOMAGNETIC ACTIVITY SCALE:
• Kp 0-2: Quiet conditions
• Kp 3-4: Unsettled to Active conditions
• Kp 5: Minor Storm (G1) - Weak power grid fluctuations
• Kp 6: Moderate Storm (G2) - High-latitude power systems affected
• Kp 7: Strong Storm (G3) - Power systems voltage corrections
• Kp 8: Severe Storm (G4) - Widespread voltage control problems
• Kp 9: Extreme Storm (G5) - Complete power system blackouts possible
```

## Server Deployment

### Using Linux Mail Command

1. Install mail utilities:
```bash
# Ubuntu/Debian
sudo apt-get install mailutils

# CentOS/RHEL
sudo yum install mailx
```

2. Configure system mail (optional):
```bash
sudo dpkg-reconfigure exim4-config
```

3. The script automatically uses Linux mail command on Unix systems.

### Using Cron for Automation

Add to crontab for automatic execution:
```bash
crontab -e

# Run every 3 hours
0 */3 * * * /usr/bin/python3 /path/to/kp_index_monitor.py --once
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
WorkingDirectory=/opt/kp-monitor
ExecStart=/usr/bin/python3 /opt/kp-monitor/kp_index_monitor.py --continuous
Restart=always
RestartSec=300

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl enable kp-monitor
sudo systemctl start kp-monitor
```

## Testing and Verification

### Initial Setup Testing

1. **Test data fetching**:
   ```bash
   python test_kp_fetch.py
   ```

2. **Test email functionality**:
   ```bash
   python kp_index_monitor.py --test
   ```

3. **Run single monitoring check**:
   ```bash
   python kp_index_monitor.py --once
   ```

### Troubleshooting

#### Common Issues

1. **Email sending fails**:
   - Check SMTP settings and credentials
   - For Gmail: Enable 2FA and use App Password
   - Test with `--test` mode first

2. **Data fetch fails**:
   - Check internet connectivity
   - Verify GFZ website is accessible
   - Check logs for specific error messages

3. **Permission errors on server**:
   - Ensure proper file permissions
   - Run as appropriate user
   - Check mail system configuration

#### Log Files

Check `kp_monitor.log` for detailed information:
```bash
tail -f kp_monitor.log
```

## Security Considerations

- **Never commit passwords** to version control
- Use **app passwords** for Gmail (not account password)
- Consider using **environment variables** for sensitive data
- Restrict **file permissions** on configuration files (600 or 644)
- Use **dedicated service accounts** for production deployment

## Gmail App Password Setup

1. Enable 2-Factor Authentication on your Google account
2. Go to Google Account settings → Security → 2-Step Verification
3. Scroll down to "App passwords"
4. Generate an app password for "Mail"
5. Use this 16-character password in your configuration

## Development and Contribution

### Project Structure
```
space_weather/
├── kp_index_monitor.py    # Main monitoring application
├── test_kp_fetch.py       # Data fetching test script
├── config.py              # Configuration template
├── requirements.txt       # Python dependencies
├── README.md             # Documentation
└── kp_index/             # Data directory
    └── *.csv             # Downloaded forecast data
```

### Contributing
- Follow PEP 8 style guidelines
- Add appropriate docstrings and comments
- Test changes with both single and continuous modes
- Update documentation for new features

## License and Attribution

This project is for educational and research purposes.

**Data Attribution**: Space weather data provided by GFZ German Research Centre for Geosciences (https://spaceweather.gfz.de/).

## Support

For issues and questions:
1. Check the troubleshooting section
2. Review log files for error details
3. Verify configuration settings
4. Test individual components using provided test scripts 