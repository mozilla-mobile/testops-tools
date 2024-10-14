# Browser Performance Testing

## Project Description

The Browser Performance Testing project is dedicated to accurately measuring and analyzing the performance metrics of major web browsers, specifically Chrome and Firefox. By leveraging the Chrome DevTools Protocol (CDP) and similar protocols for Firefox, this project aims to provide comprehensive insights into both network and Document Object Model (DOM) activities. The ultimate goal is to identify performance bottlenecks, optimize resource loading, and enhance user experiences across different browser environments.

## Quick Start Guide

Follow the steps below to set up and run the browser performance tests locally on your Mac using a physical device.

### Prerequisites

Mac Computer: Ensure you are running macOS.

Physical Device: An Android device connected to your Mac via USB.

Python 3.8+ installed on your Mac.

Chrome and Firefox Browsers: Latest versions installed on your device.

Developer Tools Enabled: Enable developer options and USB debugging on your Android device.

### Installation Steps

#### Clone the Repository:

```bash

git clone https://github.com/mozilla-mobile/testops-tools/browser-performance-testing.git

cd browser-performance-testing
```
#### Set Up a Virtual Environment:

It's recommended to use a virtual environment to manage dependencies.

```bash

python3 -m venv venv

source venv/bin/activate
```
#### Install Dependencies:

```bash

pip install -r requirements.txt
```

**Please note:**

    This is temporarily being testing with physical devices connected to
    a local host, but this is only while verifying the methodology and
    approach used for gathering these metrics.

    Once they are approved, a reverse-proxy will be hosted in GCP to
    tunnel the Websocket requests, which will be accessible through our
    Github Actions.

#### Configure Device Connection:

Connect your Android device to your Mac via USB.

Authorize USB debugging if prompted on your device.

Run Performance Tests:

Chrome Tests:

```bash

python ./android-performance/scripts/chrome_cdp.py --network 5g --timestamp 2024-10-10
```
Firefox Tests:

```bash

python ./android-performance/scripts/firefox_cdp.py --network 5g --timestamp 2024-10-10
```
## View Results:

Test results are saved as CSV files in the data/chrome/ and data/firefox/ directories.

Visualizations and analysis can be found in the notebooks/ and visualizations/ directories.

## Please note:

To load the CSV data into the Jupyter Notebook, you will need to enter the `timestamp` you used for the tests into the cell under `Loading the Data`.

Once this is complete, you can generate all the visualizations you would like from the CSV data.