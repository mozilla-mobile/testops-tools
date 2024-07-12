import argparse
import json

import requests


def get_github_directories(owner, repo, path, token):
    url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json"
    }
    response = requests.get(url, headers=headers)

    if response.status_code != 200:
        raise Exception(f"Error fetching directories: {response.status_code} {response.text}")

    return response.json()


def extract_locales(directories):
    locales = []
    for directory in directories:
        if directory['type'] == 'dir' and directory['name'].startswith('values-'):
            locale = directory['name'].replace('values-', '')
            locales.append(locale)
    return locales

def remove_r_prefix(locales):
    cleaned_locales = []
    for locale in locales:
        if "-r" in locale:
            cleaned_locales.append(locale.replace("-r", "-"))
        else:
            cleaned_locales.append(locale)
    return cleaned_locales


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract locales from GitHub directory listing.")
    parser.add_argument("token", help="GitHub personal access token")
    args = parser.parse_args()

    owner = "mozilla-l10n"
    repo = "android-l10n"
    path = "mozilla-mobile/fenix/app/src/main/res"

    try:
        directories = get_github_directories(owner, repo, path, args.token)
        locales = extract_locales(directories)

        filtered_locales = remove_r_prefix(locales)

        with open("shipping_locales.json", "w") as f:
            json.dump(filtered_locales, f)

    except Exception as e:
        print(e)
