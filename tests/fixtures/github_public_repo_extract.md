<!-- The extract searchts read produced on 2026-10-18 from the live
     https://github.com/psf/requests page: 6,414 characters, 845 words, every rung
     refusing with login-wall. Saved verbatim, not edited. -->
GitHub - psf/requests: A simple, yet elegant, HTTP library. · GitHub

Skip to content

Navigation Menu

Sign in

Appearance settings

Platform

AI CODE CREATION

GitHub Copilot

Write better code with AI

GitHub Copilot app

Direct agents from issue to merge

MCP Registry

Integrate external tools

DEVELOPER WORKFLOWS

Actions

Automate any workflow

Codespaces

Instant dev environments

Issues

Plan and track work

Code Review

Manage code changes

Code Quality

Enforce quality at merge

APPLICATION SECURITY

GitHub Advanced Security

Find and fix vulnerabilities

Code security

Secure your code as you build

Secret protection

Stop leaks before they start

EXPLORE

Why GitHub

Documentation

Blog

Changelog

Marketplace

View all features

Solutions

BY COMPANY SIZE

Enterprises

Small and medium teams

Startups

Nonprofits

BY USE CASE

App Modernization

DevSecOps

DevOps

CI/CD

View all use cases

BY INDUSTRY

Healthcare

Financial services

Manufacturing

Government

View all industries

View all solutions

Resources

EXPLORE BY TOPIC

AI

Software Development

DevOps

Security

View all topics

EXPLORE BY TYPE

Customer stories

Events & webinars

Ebooks & reports

Business insights

GitHub Skills

SUPPORT & SERVICES

Documentation

Customer support

Community forum

Trust center

Partners

View all resources

Open Source

COMMUNITY

GitHub Sponsors

Fund open source developers

PROGRAMS

Security Lab

Maintainer Community

GitHub Stars

Archive Program

REPOSITORIES

Topics

Trending

Collections

Enterprise

ENTERPRISE SOLUTIONS

Enterprise platform

AI-powered developer platform

AVAILABLE ADD-ONS

GitHub Advanced Security

Enterprise-grade security features

Copilot for Business

Enterprise-grade AI features

Premium Support

Enterprise-grade 24/7 support

Pricing

Search

/

Sign in

Sign up

Appearance settings

You signed in with another tab or window. 
Reload
 to refresh your session.

You signed out in another tab or window. 
Reload
 to refresh your session.

You switched accounts on another tab or window. 
Reload
 to refresh your session.

Dismiss alert

{{ message }}

psf

requests

Repository navigation

Code

Issues

156

 (
156
)

Pull requests

88

 (
88
)

Only collaborators can create PRs

Actions

Wiki

Security and quality

4

 (
4
)

Insights

More
 items

requests

Public

Sponsor

Notifications

You must be signed in to change notification settings

Fork

13.2k

 (
13.2k
)

Star

54.5k

 (
54.5k
)

You must be signed in to star a repository

About

A simple, yet elegant, HTTP library.

requests.readthedocs.io/en/latest/

Topics

client

cookies

forhumans

http

humans

python

python-requests

requests

Resources

Readme

Apache-2.0 license

Code of conduct

Code of conduct

Contributing

Contributing

Security policy

Security policy

Activity

Custom properties

Stars

54.5k
 stars

Watchers

1.3k
 watching

Forks

13.2k

 forks

Report repository

main

Branches

Tags

Go to file

Code

Open more actions menu

Latest commit

History

6,495 Commits

6,495 Commits

Folders and files

Name

Name

Last commit message

Last commit date

.github

.github

docs

docs

ext

ext

src/

requests

src/

requests

tests

tests

.coveragerc

.coveragerc

.git-blame-ignore-revs

.git-blame-ignore-revs

.gitignore

.gitignore

.pre-commit-config.yaml

.pre-commit-config.yaml

.readthedocs.yaml

.readthedocs.yaml

AUTHORS.rst

AUTHORS.rst

HISTORY.md

HISTORY.md

LICENSE

LICENSE

MANIFEST.in

MANIFEST.in

Makefile

Makefile

NOTICE

NOTICE

README.md

README.md

pyproject.toml

pyproject.toml

requirements-dev.txt

requirements-dev.txt

setup.py

setup.py

tox.ini

tox.ini

View all files

Repository files navigation

README

Code of conduct

Contributing

Apache-2.0 license

Security

More
 items

Requests

Requests
 is a simple, yet elegant, HTTP library.

>

>>

import

requests

>

>>

r

=

requests
.
get
(
'https://httpbin.org/basic-auth/user/pass'
, 
auth

=
(
'user'
, 
'pass'
))

>

>>

r
.
status_code

200

>

>>

r
.
headers
[
'content-type'
]

'application/json; charset=utf8'

>

>>

r
.
encoding

'utf-8'

>

>>

r
.
text

'{"authenticated": true, ...'

>

>>

r
.
json
()
{
'authenticated'
: 
True
, ...}

Requests allows you to send HTTP/1.1 requests extremely easily. There’s no need to manually add query strings to your URLs, or to form-encode your 
PUT
 & 
POST
 data — but nowadays, just use the 
json
 method!

Requests is one of the most downloaded Python packages today, pulling in around 
300M downloads / week
 — according to GitHub, Requests is currently 
depended upon
 by 
4,000,000+
 repositories.

Installing Requests and Supported Versions

Requests is available on PyPI:

$ 
python -m pip install requests

Requests officially supports Python 3.10+.

Supported Features & Best–Practices

Requests is ready for the demands of building robust and reliable HTTP–speaking applications, for the needs of today.

Keep-Alive & Connection Pooling

International Domains and URLs

Sessions with Cookie Persistence

Browser-style TLS/SSL Verification

Basic & Digest Authentication

Familiar 
dict
–like Cookies

Automatic Content Decompression and Decoding

Multi-part File Uploads

SOCKS Proxy Support

Connection Timeouts

Streaming Downloads

Automatic honoring of 
.netrc

Chunked HTTP Requests

Cloning the repository

When cloning the Requests repository, you may need to add the 
-c fetch.fsck.badTimezone=ignore
 flag to avoid an error about a bad commit timestamp (see

this issue
 for more background):

git clone -c fetch.fsck.badTimezone=ignore https://github.com/psf/requests.git

You can also apply this setting to your global Git config:

git config --global fetch.fsck.badTimezone ignore

About

A simple, yet elegant, HTTP library.

requests.readthedocs.io/en/latest/

Topics

client

cookies

forhumans

http

humans

python

python-requests

requests

Resources

Readme

Apache-2.0 license

Code of conduct

Code of conduct

Contributing

Contributing

Security policy

Security policy

Activity

Custom properties

Stars

54.5k
 stars

Watchers

1.3k
 watching

Forks

13.2k

 forks

Report repository

Releases

Sponsor this project

Used by

Contributors

Languages

Footer

 © 2026 GitHub, Inc.

Footer navigation

Terms

Privacy

Security

Status

Community

Docs

Contact

 Manage cookies

 Do not share my personal information

 You can’t perform that action at this time.
