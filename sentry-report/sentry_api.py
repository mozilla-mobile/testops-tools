#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import json
import os
import sys
import time

import requests

class Sentry:
    def __init__(self, organization_slug, project_slug):
        self.api_token = os.environ['SENTRY_API_TOKEN']
        self.sentry_url = os.environ['SENTRY_URL']
        self.organization_slug = organization_slug
        self.project_slug = project_slug
        self.headers = {
            'Authorization': f'Bearer {self.api_token}',
            'Content-Type': 'application/json'
        }
        
    def _get(self, url):
        response = requests.get(url, headers=self.headers)
        response.raise_for_status()  # Raise an error for bad status codes
        return response.json()
        
    # Public
    def get_project_events(self):
        # https://sentry.io/api/0/projects/{{organization_slug}}/:project_slug/events/
        url = f"{self.sentry_url}/{self.organization_slug}/{self.project_slug}/events/"
        return self._get(url)
    
    def get_issues(self):
        # https://sentry.io/api/0/projects/{{organization_slug}}/:project_id/issues/
        url = f"{self.sentry_url}/{self.organization_slug}/{self.project_slug}/issues/"
        return self._get(url)
    
# Playground
def main():
    sentry = Sentry(os.environ['SENTRY_ORGANIZATION_SLUG'], os.environ['SENTRY_PROJECT_SLUG'])
    events = sentry.get_project_events()
    print(json.dumps(events, indent=2)) 
        
if __name__ == '__main__':
    main()