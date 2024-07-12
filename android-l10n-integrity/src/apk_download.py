import argparse

import requests


def download_apk(url, output_path):
    response = requests.get(url, stream=True)
    if response.status_code == 200:
        with open(output_path, 'wb') as file:
            for chunk in response.iter_content(chunk_size=8192):
                file.write(chunk)
        print(f"APK downloaded successfully and saved to {output_path}")
    else:
        raise Exception(f"Error downloading APK: {response.status_code} {response.text}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Download APK from a given URL.")
    parser.add_argument("output_path", help="Path to save the downloaded APK")
    args = parser.parse_args()

    apk_url = "https://firefox-ci-tc.services.mozilla.com/api/index/v1/task/gecko.v2.mozilla-central.latest.mobile.fenix-nightly/artifacts/public%2Fbuild%2Ftarget.arm64-v8a.apk"

    try:
        download_apk(apk_url, args.output_path)
    except Exception as e:
        print(e)
