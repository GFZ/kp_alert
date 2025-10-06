#!/usr/bin/env python3
"""
Kp Data Fetch Test Script

Simple test script to verify Kp data fetching and parsing functionality.
Run this first to ensure everything is working before setting up email alerts.

Data Source: GFZ German Research Centre for Geosciences
"""

from io import StringIO

import pandas as pd
import requests


def test_kp_data_fetch():
    """
    Test fetching and parsing Kp data from GFZ website.

    Downloads Kp forecast data from the GFZ CSV endpoint and performs
    basic validation and analysis of the data format.

    Returns
    -------
    bool
        True if test passed successfully, False otherwise
    """

    url = "https://spaceweather.gfz.de/fileadmin/Kp-Forecast/CSV/kp_product_file_FORECAST_PAGER_SWIFT_LAST.csv"

    print("Testing Kp Data Fetch from GFZ...")
    print(f"URL: {url}")
    print("-" * 60)

    try:
        # Fetch data with browser-like headers
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

        print("Fetching data...")
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()

        print(f"[SUCCESS] Data fetched ({len(response.text)} characters)")

        # Parse CSV data
        print("Parsing CSV data...")
        df = pd.read_csv(StringIO(response.text))

        print(f"[SUCCESS] CSV parsed ({len(df)} records)")
        print(f"Date range: {df['Time (UTC)'].iloc[0]} to {df['Time (UTC)'].iloc[-1]}")

        # Analyze current conditions
        max_values = df["maximum"].astype(float)
        current_max = max_values.max()

        print(f"Current maximum Kp: {current_max:.2f}")

        # Check for high Kp values
        high_kp_records = df[df["maximum"].astype(float) > 5.0]

        if len(high_kp_records) > 0:
            print(f"[ALERT] HIGH Kp DETECTED! {len(high_kp_records)} periods above 5.0:")
            for _, record in high_kp_records.iterrows():
                print(f"   • {record['Time (UTC)']} UTC: Kp = {record['maximum']:.2f}")
        else:
            print("[OK] No high Kp values (>5.0) detected")

        # Display forecast data structure information
        print("\nForecast Data Information:")
        print("- Time format: UTC (dd-mm-yyyy HH:MM)")
        print("- Contains ensemble predictions with statistical summaries")
        print("- Includes probability ranges for different Kp levels")
        print("- Number of ensemble members varies between 12-20")

        # Show sample data structure
        print("\nSample data (first 5 records):")
        display_columns = ["Time (UTC)", "minimum", "median", "maximum"]
        if all(col in df.columns for col in display_columns):
            print(df[display_columns].head().to_string(index=False))
        else:
            print(df.head().to_string(index=False))

        print("\n[SUCCESS] Test completed successfully!")
        return True

    except requests.RequestException as e:
        print(f"[ERROR] Failed to fetch data: {e}")
        return False
    except Exception as e:
        print(f"[ERROR] Failed to process data: {e}")
        return False


def test_local_csv():
    """
    Test reading local CSV file if available.

    Attempts to read a local CSV file for testing purposes if it exists.
    This is optional functionality for offline testing.

    Returns
    -------
    bool
        True if local CSV was read successfully, False if file not found or error
    """

    local_file = "kp_index/kp_product_file_FORECAST_PAGER_SWIFT_LAST.csv"

    print(f"\nTesting Local CSV File: {local_file}")
    print("-" * 60)

    try:
        df = pd.read_csv(local_file)
        print(f"[SUCCESS] Local CSV read ({len(df)} records)")

        max_kp = df["maximum"].astype(float).max()
        print(f"Maximum Kp in local data: {max_kp:.2f}")

        # Display basic statistics
        print("\nLocal data statistics:")
        print(f"- Records: {len(df)}")
        print(f"- Date range: {df['Time (UTC)'].iloc[0]} to {df['Time (UTC)'].iloc[-1]}")

        return True

    except FileNotFoundError:
        print("[INFO] Local CSV file not found (this is OK)")
        return False
    except Exception as e:
        print(f"[ERROR] Failed to read local CSV: {e}")
        return False


def display_data_format_info():
    """
    Display information about the expected data format.

    Prints detailed information about the structure and contents of the
    GFZ Kp forecast CSV file format to help users understand the data.
    """
    print("\nData Format Information:")
    print("=" * 60)
    print("The CSV file contains the following columns:")
    print("- Time (UTC): Forecast time in dd-mm-yyyy HH:MM format")
    print("- minimum: Minimum forecasted Kp value")
    print("- 0.25-quantile: 25th percentile value")
    print("- median: Median forecasted value")
    print("- 0.75-quantile: 75th percentile value")
    print("- maximum: Maximum forecasted Kp value")
    print("- prob 4-5: Probability of 4 <= Kp <= 5")
    print("- prob 5-6: Probability of 5 <= Kp <= 6")
    print("- prob 6-7: Probability of 6 <= Kp <= 7")
    print("- prob 7-8: Probability of 7 <= Kp <= 8")
    print("- prob >= 8: Probability of Kp >= 8")
    print("- Individual ensemble members (indexed by _i)")


if __name__ == "__main__":
    print("=" * 60)
    print("Kp Index Data Fetch Test")
    print("=" * 60)

    # Display data format information
    display_data_format_info()

    # Test online data fetch
    online_success = test_kp_data_fetch()

    # Test local data if available
    local_success = test_local_csv()

    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    print(f"Online data fetch: {'[PASS]' if online_success else '[FAIL]'}")
    print(f"Local data test:   {'[PASS]' if local_success else '[SKIP]'}")

    if online_success:
        print("\n[SUCCESS] Ready to set up email alerts!")
        print("Next steps:")
        print("1. Edit config.py with your email settings")
        print("2. Run: python kp_index_monitor.py --test")
        print("3. Run: python kp_index_monitor.py --once")
    else:
        print("\n[WARNING] Please check your internet connection and try again.")
