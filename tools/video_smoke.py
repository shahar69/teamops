import os
import sys
import time
import json
import requests
import urllib.request
import urllib.error

BASE = os.environ.get('BASE_URL', 'http://127.0.0.1:8001')

def post(path, payload):
    r = requests.post(BASE + path, json=payload)
    return r.status_code, r.text, (r.headers.get('content-type') or ''), r

# 1) Ensure at least one profile (optional)
try:
    post('/ai/profiles', {'name': 'SmokeDemo'})
except Exception as e:
    print('profiles warn:', e, file=sys.stderr)

# 2) Generate content (video-script)
code, txt, ct, r = post('/ai/content', {
    'title': 'Minecraft Viral Tips',
    'content_type': 'video-script',
    'brief': '3 fast tips to grow'
})
print('content status:', code)
if code != 200:
    print(txt)
    sys.exit(1)
job = r.json().get('job', {})
job_id = job.get('id')
print('job id:', job_id)

# 3) Render video with subtitles
code, txt, ct, r = post('/ai/video', {
    'job_id': job_id,
    'subtitles': True,
})
print('video status:', code)
print(txt)
if code != 200:
    sys.exit(0)

try:
    data = r.json()
    url = data['video']['url']
    print('video url:', url)
    # Perform a HEAD request using urllib
    head_req = urllib.request.Request(BASE + url, method='HEAD')
    try:
        with urllib.request.urlopen(head_req, timeout=10) as hresp:
            print('HEAD:', hresp.getcode())
    except urllib.error.HTTPError as he:
        print('HEAD HTTPError:', he.code, file=sys.stderr)
    except Exception as e:
        print('HEAD warn:', e, file=sys.stderr)
except Exception as e:
    print('post-verify warn:', e, file=sys.stderr)
