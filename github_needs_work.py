#!/usr/bin/env python
# -*- encoding:utf-8 -*-
"""
gh_lists.py MILESTONE

Functions for Github API requests.
"""
from __future__ import print_function, division, absolute_import

import os
import re
import sys
import json
import base64
import time
import datetime
import collections
import argparse
import tempita
import tempfile
import gzip

from urllib2 import urlopen, Request

HTML_TEMPLATE = """\
<!DOCTYPE html>
<html>
<head>
  <title>{{project}} backlog</title>
</head>
<body>
  <h1>Project <a href="https://github.com/{{project}}/pulls">{{project}}</a></h1>
  <h2>Pull requests with needs-work tag, but with new commits</h2>
  <ul>
  {{for pull in pulls}}
    <li><a href="{{pull['html_url']}}">gh-{{pull['number']}}</a>: {{pull['title']}}</li>
  {{endfor}}
  {{if not pulls}}
    <li>No pull requests in backlog!</li>
  {{endif}}
  </ul>
</body>
"""


def main():
    p = argparse.ArgumentParser(usage=__doc__.lstrip())
    p.add_argument('--project', default='scipy/scipy')
    p.add_argument('--auth', action='store_true',
                   help="Authenticate to Github (increases rate limits)")
    args = p.parse_args()

    getter = CachedGet('gh_cache.json.gz', auth=args.auth)
    try:
        process(getter, args.project)
    finally:
        getter.save()

    return 0


def process(getter, project):
    pulls = get_pulls_cached(getter, project)
        
    backlog = []

    pulls.sort(key=lambda x: x['number'])

    for pull in pulls:
        labelings = [event for event in pull['events']
                     if event['event'] == 'labeled' and event['label']['name'] == 'needs-work']
        if not labelings:
            continue
        if not pull['commits']:
            continue

        last_label_date = max(parse_time(event['created_at']) for event in labelings)
        last_commit_date = max(max(parse_time(commit['commit']['author']['date']),
                                   parse_time(commit['commit']['committer']['date']))
                               for commit in pull['commits'])

        if last_commit_date > last_label_date:
            backlog.append(pull)

    ns = dict(pulls=backlog, project=project)
    t = tempita.Template(HTML_TEMPLATE)
    print(t.substitute(ns))


def get_pulls_cached(getter, project):
    getter.info.setdefault('last_updated', '1970-1-1T00:00:00Z')

    # Get old pull requests (may be cached)
    pulls = get_pulls_needs_work(getter, project, parse_time('1970-1-1T00:00:00Z'))

    # Get new pull requests (update cached ones)
    new_update_time = datetime.datetime.utcnow()
    new_pulls = get_pulls_needs_work(getter, project, parse_time(getter.info['last_updated']), cache=False)

    # Update update time
    getter.info['last_updated'] = format_time(new_update_time)

    # Update pulls
    new_pull_dict = dict((pull['number'], pull) for pull in new_pulls)

    for j in range(len(pulls)):
        pulls[j] = new_pull_dict.pop(pulls[j]['number'], pulls[j])

    pulls.extend(new_pull_dict.values())
    return pulls


def get_pulls_needs_work(getter, project, since, cache=True):
    url = "https://api.github.com/repos/{project}/issues?state=open&sort=updated&direction=desc&since={since}&labels=needs-work"
    url = url.format(project=project, since=format_time(since))

    data = getter.get_multipage(url, cache=cache)
    pulls = [pull for pull in data if pull.get('pull_request')]

    for pull in pulls:
        data, info = getter.get(pull['events_url'], cache=cache)
        pull[u'events'] = data

        commits_url = pull['pull_request']['url'] + '/commits'
        data, info = getter.get(commits_url, cache=cache)
        pull[u'commits'] = data

    return pulls


def format_time(d):
    return d.strftime('%Y-%m-%dT%H:%M:%SZ')


def parse_time(s):
    """Parse a time string and convert to UTC"""

    # UTC time format
    if s.endswith('Z'):
        return datetime.datetime.strptime(s, '%Y-%m-%dT%H:%M:%SZ')

    # US time format
    m = re.match(r'^([0-9]+)/([0-9]+)/([0-9]+)\s*([0-9]+:[0-9]+:[0-9]+)\s*([+-][0-9][0-9][0-9][0-9])\s*$', s)
    if m:
        s = "%s-%s-%sT%s%s:%s" % (m.group(1), m.group(2), m.group(3),
                                  m.group(4), m.group(5)[:-2], m.group(5)[-2:])

    # TZ time format
    m = re.search(r'([+-])([0-9]+):([0-9]+)$', s)
    if m:
        t = datetime.datetime.strptime(s[:m.start()], '%Y-%m-%dT%H:%M:%S')
        dt = datetime.timedelta(hours=int(m.group(2)),
                                minutes=int(m.group(3)))
        if m.group(1) == '+':
            t -= dt
        else:
            t += dt
        return t

    # Fallbacks
    fmts = ["%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%Y-%m-%d",
            "%Y-%m",
            "%Y"]
    for fmt in fmts:
        try:
            return datetime.datetime.strptime(s, fmt)
        except ValueError:
            continue

    # Unknown
    raise ValueError("Failed to parse date %r" % s)


class CachedGet(object):
    def __init__(self, filename, auth=False):
        self.filename = filename
        if os.path.isfile(filename):
            print("[gh] using {0} as cache (remove it if you want fresh data)".format(filename),
                  file=sys.stderr)
            with gzip.open(filename, 'rb') as f:
                self.cache = json.load(f)
        else:
            self.cache = {}

        self.headers = {'User-Agent': 'github_needs_work.py'}

        if auth:
            self.authenticate()

        req = self.urlopen('https://api.github.com/rate_limit')
        try:
            if req.getcode() != 200:
                raise RuntimeError()
            info = json.loads(req.read())
        finally:
            req.close()

        self.ratelimit_remaining = int(info['rate']['remaining'])
        self.ratelimit_reset = float(info['rate']['reset'])

    def authenticate(self):
        print("Input a Github API access token.\n"
              "Personal tokens can be created at https://github.com/settings/tokens\n"
              "This script does not require any permissions (so don't give it any).",
              file=sys.stderr)
        print("Access token: ", file=sys.stderr, end='')
        token = raw_input()
        self.headers['Authorization'] = 'token {0}'.format(token.strip())

    def urlopen(self, url, auth=None):
        assert url.startswith('https://')
        req = Request(url, headers=self.headers)
        return urlopen(req)

    @property
    def info(self):
        return self.cache.setdefault('info', {})

    def get_multipage(self, url, cache=True):
        data = []
        while url:
            page_data, info = self.get(url, cache=cache)
            data += page_data
            url = info['next']
        return data

    def get(self, url, cache=True):
        url = unicode(url)
        if url not in self.cache or not cache:
            while True:
                # Wait until rate limit
                while self.ratelimit_remaining == 0 and self.ratelimit_reset > time.time():
                    s = self.ratelimit_reset + 5 - time.time()
                    if s <= 0:
                        break
                    print("[gh] rate limit exceeded: waiting until {0} ({1} s remaining)".format(
                             datetime.datetime.fromtimestamp(self.ratelimit_reset).strftime('%Y-%m-%d %H:%M:%S'),
                             int(s)),
                          file=sys.stderr)
                    time.sleep(min(5*60, s))

                # Get page
                print("[gh] get:", url, file=sys.stderr)
                req = self.urlopen(url)
                try:
                    data = json.load(req)

                    if req.getcode() not in (200, 403):
                        raise RuntimeError()

                    # Parse reply
                    info = dict(req.info())
                    info['next'] = None
                    if 'link' in info:
                        m = re.search('<(.*?)>; rel="next"', info['link'])
                        if m:
                            info['next'] = m.group(1)

                    # Update rate limit info
                    if 'x-ratelimit-remaining' in info:
                        self.ratelimit_remaining = int(info['x-ratelimit-remaining'])
                    if 'x-ratelimit-reset' in info:
                        self.ratelimit_reset = float(info['x-ratelimit-reset'])

                    # Deal with rate limit exceeded
                    if req.getcode() == 403:
                        if self.ratelimit_remaining == 0:
                            continue
                        else:
                            raise RuntimeError()

                    # Done.
                    self.cache[url] = (data, info)
                    break
                finally:
                    req.close()
        else:
            print("[gh] get (cached):", url, file=sys.stderr)

        return self.cache[url]

    def save(self):
        fd, tmp = tempfile.mkstemp(prefix=os.path.basename(self.filename) + '.new-',
                                   dir=os.path.dirname(self.filename))
        os.close(fd)
        with gzip.open(tmp, 'w', 1) as f:
            json.dump(self.cache, f)
        os.rename(tmp, self.filename)


if __name__ == "__main__":
    sys.exit(main())
