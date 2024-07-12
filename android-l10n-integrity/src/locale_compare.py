import json
import os
import sys


def load_json(file_path):
    with open(file_path, 'r') as file:
        return json.load(file)


def check_missing_locales(shipping_locales, apk_locales):
    missing_locales = [locale for locale in shipping_locales if locale not in apk_locales]
    return missing_locales


if __name__ == "__main__":
    shipping_locales_path = 'shipping_locales.json'
    apk_locales_path = 'apk_locales.json'

    log_file = 'check_locales.log'
    with open(log_file, 'w') as log:
        try:
            shipping_locales = load_json(shipping_locales_path)
            apk_locales = load_json(apk_locales_path)

            missing_locales = check_missing_locales(shipping_locales, apk_locales)

            if missing_locales:
                log.write(f"Missing locales: {missing_locales}\n")
                print(f"Missing locales: {missing_locales}")

                # Write to $GITHUB_STEP_SUMMARY
                summary_file = os.getenv('GITHUB_STEP_SUMMARY')
                if summary_file:
                    with open(summary_file, 'a') as summary:
                        summary.write("## Missing Locales\n")
                        summary.write("| Missing Locales |\n")
                        summary.write("|-----------------|\n")
                        for locale in missing_locales:
                            summary.write(f"| {locale} |\n")

                    # Write to $GITHUB_ENV
                    # Set the missing locales as an environment variable
                    with open(os.getenv('GITHUB_ENV'), 'a') as env_file:
                        env_file.write(f"LOCALES_MISSING={','.join(missing_locales)}\n")

                sys.exit(1)
            else:
                log.write("All locales are present.\n")
                print("All locales are present.")
                sys.exit(0)
        except Exception as e:
            log.write(f"Error: {e}\n")
            print(f"Error: {e}")
            sys.exit(1)
