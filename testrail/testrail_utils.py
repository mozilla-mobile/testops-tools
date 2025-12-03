#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""
This script contains utility functions designed to support the integration of automated
testing processes with TestRail, a test case management tool. The primary focus is on
creating and managing milestones in TestRail based on automated smoke tests for product
releases. It includes functions for building milestone names and descriptions, determining
release types, and loading TestRail credentials.

Functions:
- build_milestone_name(product_type, release_type, version_number): Constructs a formatted
  milestone name based on the product type, release type, and version number.
- build_milestone_description(milestone_name): Generates a detailed description for the
  milestone, including the release date and placeholders for testing status and QA recommendations.
- get_release_version(): Reads and returns the release version number from a 'version.txt' file.
- get_release_type(version): Determines the release type (e.g., Alpha, Beta, RC) based on
  the version string.
- load_testrail_credentials(json_file_path): Loads TestRail credentials from a JSON file
  and handles potential errors during the loading process.
- get_release_version_ios(release_tag): Reads and returns the release version from the release tag.
- build_milestone_description_ios(milestone_name): Generates a detailed description for the
  milestonefor ios, including the release date and placeholders for testing status and QA recommendations.
"""

import json
import os
import textwrap
from datetime import datetime


def build_milestone_name(product_type, release_type, version_number):
    return f"Build Validation sign-off - {product_type} {release_type} {version_number}"


def build_milestone_description(milestone_name):
    current_date = datetime.now()
    formatted_date = current_date = current_date.strftime("%B %d, %Y")
    return textwrap.dedent(
        f"""
        RELEASE: {milestone_name}\n\n\
        RELEASE_TAG_URL: https://archive.mozilla.org/pub/fenix/releases/\n\n\
        RELEASE_DATE: {formatted_date}\n\n\
        TESTING_STATUS: [ TBD ]\n\n\
        QA_RECOMMENDATION:[ TBD ]\n\n\
        QA_RECOMENTATION_VERBOSE: \n\n\
        TESTING_SUMMARY\n\n\
        Known issues: n/a\n\
        New issue: n/a\n\
        Verified issue:
    """
    )


def get_release_version():
    # Check if version.txt was found
    version_file_path = os.path.join(
        os.environ.get("GECKO_PATH", "."), "mobile", "android", "version.txt"
    )
    if not os.path.isfile(version_file_path):
        raise FileNotFoundError(f"{version_file_path} not found.")

    # Read the version from the file
    with open(version_file_path, "r") as file:
        version = file.readline().strip()

    return version


def get_release_type(version):
    release_map = {"a": "Alpha", "b": "Beta"}
    # use generator expression to check each char for key else default to 'RC'
    product_type = next(
        (release_map[char] for char in version if char in release_map), "RC"
    )
    return product_type


def load_testrail_credentials(json_file_path):
    try:
        with open(json_file_path, "r") as file:
            credentials = json.load(file)
        return credentials
    except json.JSONDecodeError as e:
        raise ValueError(f"Failed to load TestRail credentials: {e}")

def get_release_version_ios(release_tag):
    if release_tag and 'v' in release_tag:
        version = release_tag.split('v')[-1]  # e.g., "140.0b2"
    else:
        version = None
    return version

def build_milestone_description_ios(milestone_name):
    current_date = datetime.now()
    formatted_date = current_date = current_date.strftime("%B %d, %Y")
    return textwrap.dedent(
        f"""
        RELEASE: {milestone_name}\n\n\
        RELEASE_TAG_URL: https://github.com/mozilla-mobile/firefox-ios/releases/\n\n\
        RELEASE_DATE: {formatted_date}\n\n\
        TESTING_STATUS: [ TBD ]\n\n\
        QA_RECOMMENDATION: [ TBD ]\n\n\
        QA_RECOMENTATION_VERBOSE: \n\n\
        TESTING_SUMMARY\n\n\
        Known issues: n/a\n\
        New issue: n/a\n\
        Verified issue:
    """
    )

def trigger_jenkins_jobs(release_version, shipping_product):
    """
    Triggers Jenkins jobs after milestone creation
    
    Args:
        release_version: Release version number (e.g., "134")
        shipping_product: Product name ("firefox" or "focus")
    """
    jenkins_ssh_host = os.environ.get("JENKINS_SSH_HOST")
    jenkins_ssh_user = os.environ.get("JENKINS_SSH_USER")
    jenkins_ssh_key_path = os.environ.get("JENKINS_SSH_KEY_PATH")
    
    if not all([jenkins_ssh_host, jenkins_ssh_user, jenkins_ssh_key_path]):
        print("WARNING: Jenkins SSH configuration not found. Skipping job triggers.")
        print(f"  JENKINS_SSH_HOST: {jenkins_ssh_host}")
        print(f"  JENKINS_SSH_USER: {jenkins_ssh_user}")
        print(f"  JENKINS_SSH_KEY_PATH: {jenkins_ssh_key_path}")
        return
    
    # Define jobs based on product
    if shipping_product == "firefox":
        jobs = [
            "Firefox-ios-TAE",
            "Firefox-ios-Performance-Tests"  # Ajusta al nombre real si es diferente
        ]
    elif shipping_product == "focus":
        jobs = [
            "Focus-ios-TAE",
            "Focus-ios-Performance-Tests"  # Ajusta al nombre real si es diferente
        ]
    else:
        print(f"WARNING: Unknown product '{shipping_product}'. No jobs triggered.")
        return
    
    branch = f"origin/releases_v{release_version}"
    
    print(f"\n{'='*60}")
    print(f"Triggering Jenkins jobs for {shipping_product}")
    print(f"Release version: {release_version}")
    print(f"Branch: {branch}")
    print(f"{'='*60}\n")
    
    for job in jobs:
        try:
            ssh_command = [
                "ssh",
                "-i", jenkins_ssh_key_path,
                "-o", "StrictHostKeyChecking=no",
                "-o", "UserKnownHostsFile=/dev/null",
                f"{jenkins_ssh_user}@{jenkins_ssh_host}",
                f"~/jenkins-trigger.sh {job} BRANCH={branch}"
            ]
            
            print(f"Triggering job: {job}")
            print(f"  Command: {' '.join(ssh_command)}")
            
            result = subprocess.run(
                ssh_command,
                capture_output=True,
                text=True,
                timeout=120  # 2 minutos timeout
            )
            
            if result.returncode == 0:
                print(f"✓ Job '{job}' triggered successfully")
                if result.stdout:
                    print(f"  Output: {result.stdout.strip()}")
            else:
                print(f"✗ Failed to trigger job '{job}'")
                print(f"  Return code: {result.returncode}")
                if result.stderr:
                    print(f"  Error: {result.stderr.strip()}")
                if result.stdout:
                    print(f"  Output: {result.stdout.strip()}")
                    
        except subprocess.TimeoutExpired:
            print(f"✗ Timeout triggering job '{job}' (exceeded 120 seconds)")
        except FileNotFoundError:
            print(f"✗ SSH command not found. Is SSH installed?")
            break
        except Exception as e:
            print(f"✗ Unexpected error triggering job '{job}': {str(e)}")
    
    print(f"\n{'='*60}\n")