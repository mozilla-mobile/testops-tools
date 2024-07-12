import argparse
import json
import os
import subprocess


def is_aapt_available(sdk_root):
    aapt_path = os.path.join(sdk_root, "build-tools", "34.0.0", "aapt")
    try:
        result = subprocess.run([aapt_path, "version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        return result.returncode == 0, aapt_path
    except FileNotFoundError:
        return False, None


def get_locales_from_apk(apk_path, aapt_path):
    try:
        result = subprocess.run([aapt_path, "dump", "badging", apk_path], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode != 0:
            raise Exception(f"Error running aapt: {result.stderr}")

        for line in result.stdout.splitlines():
            if "locales:" in line:
                return line.split("locales:")[1].strip().split("'")[1::2]

        return []
    except Exception as e:
        raise Exception(f"Error getting locales from APK: {str(e)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract locales from APK using aapt.")
    parser.add_argument("apk_path", help="Path to the APK file")
    args = parser.parse_args()

    sdk_root = os.getenv('ANDROID_SDK_ROOT')
    if not sdk_root:
        print("Error: ANDROID_SDK_ROOT environment variable is not set.")
        exit(1)

    is_available, aapt_path = is_aapt_available(sdk_root)
    if not is_available:
        print("Error: aapt tool is not available. Please ensure the Android SDK is installed and aapt is in your PATH.")
        exit(1)

    try:
        locales = get_locales_from_apk(args.apk_path, aapt_path)
        with open("apk_locales.json", "w") as json_file:
            json.dump(locales, json_file)
        print("Locales have been written to apk_locales.json")
    except Exception as e:
        print(e)
