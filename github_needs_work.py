#!/usr/bin/env python3
# -*- encoding:utf-8 -*-
"""
github_needs_work.py

Print pull requests in Github which have needs-work label despite
having updated commits. Creates a cache file ``gh_cache.json`` in
the current directory.

"""

import os
import re
import sys
import json
import time
import datetime
import argparse
import tempita
import tempfile

from urllib.request import urlopen, Request, HTTPError, quote

HTML_TEMPLATE = """\
<!DOCTYPE html>
<html>
<head>
  <title>{{project}} backlog</title>
</head>
<body>
  <h1>Project <a href="https://github.com/{{project}}/pulls">{{project}}</a> pull requests</h1>
  <p>Updated {{date}}</p>
  <h2>Updated PRs (new commits but old needs-work label) [{{len(backlog)}}]</h2>
  <ul>
  {{for pull in backlog}}
    <li><a href="{{pull['html_url']}}">gh-{{pull['number']}}</a>: {{pull['title']}}</li>
  {{endfor}}
  {{if not backlog}}
    <li>No such pull requests</li>
  {{endif}}
  </ul>
  <h2>Needs review [{{len(needs_review)}}]</h2>
  <ul>
  {{for pull in needs_review}}
    <li><a href="{{pull['html_url']}}">gh-{{pull['number']}}</a>: {{pull['title']}}</li>
  {{endfor}}
  {{if not needs_review}}
    <li>No such pull requests</li>
  {{endif}}
  </ul>
  <p>Same as <a href="https://github.com/{{project}}/pulls?q=is%3Apr+is%3Aopen+-label%3A{{label_needs_work}}+-label%3A{{label_needs_decision}}">this github search</a>, with updated PRs, WIPs, and review:changes-requested excluded.</p>
  <h2>Needs decision [{{len(decision)}}]</h2>
  <ul>
  {{for pull in decision}}
    <li><a href="{{pull['html_url']}}">gh-{{pull['number']}}</a>: {{pull['title']}}</li>
  {{endfor}}
  {{if not decision}}
    <li>No such pull requests</li>
  {{endif}}
  </ul>
  <p>Same as <a href="https://github.com/{{project}}/pulls?q=is%3Apr+is%3Aopen+label%3A{{label_needs_decision}}">this github search</a>, with updated PRs and WIPs excluded.</p>
  <h2>Needs work etc. [{{len(other)}}]</h2>
  <ul>
  {{for pull in other}}
    <li><a href="{{pull['html_url']}}">gh-{{pull['number']}}</a>: {{pull['title']}}</li>
  {{endfor}}
  {{if not other}}
    <li>No such pull requests</li>
  {{endif}}
  </ul>
  <p>Same as <a href="https://github.com/{{project}}/pulls?q=is%3Apr+is%3Aopen+label%3A{{label_needs_work}}+-label%3A{{label_needs_decision}}">this</a> and <a href="https://github.com/{{project}}/pulls?q=is%3Apr+is%3Aopen+review%3Achanges-requested+-label%3A{{label_needs_decision}}">this</a> github search, with updated PRs excluded and WIPs included.</p>
  <h2>Needs champion [{{len(champion)}}]</h2>
  <ul>
  {{for pull in champion}}
    <li><a href="{{pull['html_url']}}">gh-{{pull['number']}}</a>: {{pull['title']}}</li>
  {{endfor}}
  {{if not champion}}
    <li>No such pull requests</li>
  {{endif}}
  </ul>
  <p>Same as <a href="https://github.com/{{project}}/pulls?q=is%3Apr+label%3A{{label_needs_champion}}">this github search</a>.</p>
  <h2>Needs backport [{{len(backport)}}]</h2>
  <ul>
  {{for pull in backport}}
    <li><a href="{{pull['html_url']}}">gh-{{pull['number']}}</a>: {{pull['title']}}</li>
  {{endfor}}
  {{if not backport}}
    <li>No such pull requests</li>
  {{endif}}
  </ul>
  <p>Same as <a href="https://github.com/{{project}}/pulls?q=is%3Apr+label%3A{{label_needs_backport}}">this github search</a>.</p>
  <hr style="margin-top: 2em;">
  <p>
  Generated by <a href="https://github.com/pv/github-needs-work">github-needs-work</a>
  </p>
</body>
"""


def main():
    p = argparse.ArgumentParser(usage=__doc__.lstrip())
    p.add_argument('--project', default='scipy/scipy')
    p.add_argument('--auth', action='store_true',
                   help="Authenticate to Github (increases rate limits)")
    p.add_argument('--label-needs-work', default='needs-work')
    p.add_argument('--label-needs-decision', default='needs-decision')
    p.add_argument('--label-needs-champion', default='needs-champion')
    p.add_argument('--label-needs-backport', default='backport-candidate')
    args = p.parse_args()

    lock = LockFile('gh_cache.json.lock')

    if lock.acquire(block=False):
        try:
            getter = GithubGet(auth=args.auth)
            pull_cache = PullCache('gh_cache.json', args.project, getter)
            try:
                process(pull_cache, args.project, args.label_needs_work, args.label_needs_decision, args.label_needs_champion, args.label_needs_backport)
            finally:
                pull_cache.save()
        finally:
            lock.release()
    else:
        print("Another process already running")
        return 1

    return 0


def process(pull_cache, project, label_needs_work, label_needs_decision, label_needs_champion,
            label_needs_backport):
    pull_cache.update()
    pulls = pull_cache.values()

    backlog = []
    needs_review = []
    decision = []
    other = []
    champion = []
    backport = []

    for pull in sorted(pulls,
                       key=lambda x: parse_time(x['created_at']),
                       reverse=True):

        needs_champion = any(label['name'] == label_needs_champion for label in pull['labels'])
        if needs_champion:
            champion.append(pull)
            continue

        needs_backport = any(label['name'] == label_needs_backport for label in pull['labels'])
        if needs_backport:
            backport.append(pull)
            continue

        if pull['state'] != 'open':
            continue

        if not pull['commits']:
            continue

        needs_work = any(label['name'] == label_needs_work for label in pull['labels'])
        needs_decision = any(label['name'] == label_needs_decision for label in pull['labels'])

        if pull['title'].startswith('WIP') or pull['title'].endswith('WIP'):
            needs_work = True

        labelings = [event for event in pull['events']
                     if event['event'] == 'labeled' and event['label']['name'] == label_needs_work]
        if labelings:
            needs_work_label_date = max(parse_time(event['created_at']) for event in labelings)
        else:
            needs_work_label_date = None
            
        last_commit_date = max(max(parse_time(commit['commit']['author']['date']),
                                   parse_time(commit['commit']['committer']['date']))
                               for commit in pull['commits'])

        if (needs_work and
                needs_work_label_date is not None and
                last_commit_date > needs_work_label_date):
            backlog.append(pull)
        elif needs_decision:
            decision.append(pull)
        elif not needs_work:
            needs_review.append(pull)
        else:
            other.append(pull)

    ns = dict(backlog=backlog,
              needs_review=needs_review,
              decision=decision,
              other=other,
              champion=champion,
              backport=backport,
              project=project,
              date=datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC'),
              label_needs_work=quote('"{0}"'.format(label_needs_work)),
              label_needs_decision=quote('"{0}"'.format(label_needs_decision)),
              label_needs_champion=quote('"{0}"'.format(label_needs_champion)),
              label_needs_backport=quote('"{0}"'.format(label_needs_backport))
              )
    t = tempita.Template(HTML_TEMPLATE)
    print(t.substitute(ns))


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


class PullCache(object):
    def __init__(self, filename, project, getter):
        self.filename = filename
        self.project = project
        self.getter = getter

        if os.path.isfile(filename):
            print("[gh] using {0} as cache (remove it if you want fresh data)".format(filename),
                  file=sys.stderr)
            with open(filename, 'r', encoding='utf-8') as f:
                self.cache = json.load(f)
        else:
            self.cache = {}

    def values(self):
        return self.cache['pulls'].values()

    def update(self):
        self.cache.setdefault('last_updated', '1970-1-1T00:00:00Z')
        self.cache.setdefault('pulls', {})

        pulls = self.cache['pulls']

        # Get changed pull requests
        prev_time = parse_time(self.cache['last_updated'])
        new_time = datetime.datetime.utcnow()
        new_pulls = self._get(prev_time)
        self.cache['last_updated'] = format_time(new_time)

        # Update pulls
        for pull in new_pulls:
            k = "{0}".format(pull['number'])
            pulls[k] = pull

    def _get(self, since):
        url = "https://api.github.com/repos/{project}/issues?sort=updated&direction=desc&since={since}&state=all"
        url = url.format(project=self.project, since=format_time(since))

        data = self.getter.get_multipage(url)
        pulls = [pull for pull in data if pull.get('pull_request')]

        for pull in pulls:
            if pull.get('state') != 'open':
                continue

            data, info = self.getter.get(pull['events_url'])
            pull[u'events'] = data

            commits_url = pull['pull_request']['url'] + '/commits'
            data, info = self.getter.get(commits_url)
            pull[u'commits'] = data

            commits_url = pull['pull_request']['url'] + '/reviews'
            data, info = self.getter.get(commits_url)
            pull[u'reviews'] = data

        return pulls

    def save(self):
        print("[gh] saving cache...", file=sys.stderr)
        fd, tmp = tempfile.mkstemp(prefix=os.path.basename(self.filename) + '.new-',
                                   dir=os.path.dirname(self.filename))
        os.close(fd)
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(self.cache, f)
        os.rename(tmp, self.filename)


class GithubGet(object):
    def __init__(self, auth=False):
        self.headers = {'User-Agent': 'github_needs_work.py'}

        if auth:
            self.authenticate()

        req = self.urlopen('https://api.github.com/rate_limit')
        try:
            if req.getcode() != 200:
                raise RuntimeError()
            info = json.loads(req.read().decode('utf-8'))
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
        token = input()
        self.headers['Authorization'] = 'token {0}'.format(token.strip())

    def urlopen(self, url, auth=None):
        assert url.startswith('https://')
        req = Request(url, headers=self.headers)
        return urlopen(req, timeout=60)

    def get_multipage(self, url):
        data = []
        while url:
            page_data, info = self.get(url)
            data += page_data
            url = info['Next']
        return data

    def get(self, url):
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
            try:
                req = self.urlopen(url)
                try:
                    code = req.getcode()
                    info = dict(req.info())
                    data = json.loads(req.read().decode('utf-8'))
                finally:
                    req.close()
            except HTTPError as err:
                code = err.getcode()
                info = err.info()
                data = None

            if code not in (200, 403):
                raise RuntimeError()

            # Parse reply
            info['Next'] = None
            if 'Link' in info:
                m = re.search('<(.*?)>; rel="next"', info['Link'])
                if m:
                    info['Next'] = m.group(1)

            # Update rate limit info
            if 'X-RateLimit-Remaining' in info:
                self.ratelimit_remaining = int(info['X-RateLimit-Remaining'])
            if 'X-RateLimit-Reset' in info:
                self.ratelimit_reset = float(info['X-RateLimit-Reset'])

            # Deal with rate limit exceeded
            if code != 200 or data is None:
                if self.ratelimit_remaining == 0:
                    continue
                else:
                    raise RuntimeError()

            # Done.
            return data, info


class LockFile(object):
    # XXX: posix-only

    def __init__(self, filename):
        self.filename = filename
        self.pid = os.getpid()
        self.count = 0

    def __enter__(self):
        self.acquire()

    def __exit__(self, exc_type, exc_value, traceback):
        self.release()

    def acquire(self, block=True):
        if self.count > 0:
            self.count += 1
            return True

        while True:
            try:
                lock_pid = os.readlink(self.filename)
                if not os.path.isdir('/proc/%s' % lock_pid):
                    # dead lock; delete under lock to avoid races
                    sublock = LockFile(self.filename + '.lock')
                    sublock.acquire()
                    try:
                        os.unlink(self.filename)
                    finally:
                        sublock.release()
            except OSError as exc:
                pass

            try:
                os.symlink(repr(self.pid), self.filename)
                break
            except OSError as exc:
                if exc.errno != 17: raise

            if not block:
                return False
            time.sleep(1)

        self.count += 1
        return True

    def release(self):
        if self.count == 1:
            if os.path.islink(self.filename):
                os.unlink(self.filename)
        elif self.count < 1:
            raise RuntimeError('Invalid lock nesting')
        self.count -= 1


if __name__ == "__main__":
    sys.exit(main())
