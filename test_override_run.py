"""One-off: Educator Override full cycle + demo09 baseline insight card."""
import os, re
from dotenv import load_dotenv
load_dotenv()

import app as app_module
from app import app
import pipeline_trace as pt

app_module.REQUIRE_APPROVAL = True

c = app.test_client()
c.post('/login', data={'password': os.environ.get('APP_PASSWORD', '')})

# 1. Generate with save -> should be STAGED (dry-run), not saved
r = c.post('/view_report', data={
    'report-type': 'stu_teacher',
    'student-name': 'demo02',
    'assessment-date': '2026-10-20',
    'what-to-assess': 'Readiness for the next level',
    'stu_role': 'You are an experienced robotics educator writing for parents.',
    'save_checkbox': '1',
})
body = r.data.decode('utf-8')
print('staged page:', r.status_code, 'Your decision is required' in body)
m = re.search(r'/approve/([0-9a-f]+)', body)
token = m.group(1)
print('token:', token)

# 2. Approve -> writes happen now, decision appended to the trace
r = c.post(f'/approve/{token}', data={'action': 'approve'})
print('approve:', r.status_code, 'Report saved' in r.data.decode('utf-8'))

# 3. Verify the audit trail in the original trace
pend = [e for e in [pt.append_event.__module__] ]  # noop
traces = pt.list_traces()
t = pt.load_trace(traces[0]['run_id'])
for e in t['events']:
    if e['stage'] == 'save' or (e['stage'] == 'note' and e.get('kind') == 'educator_override'):
        print('TRACE', e['stage'], {k: v for k, v in e.items() if k in ('blocked', 'educator_decision', 'reason', 'message', 'type', 'entity')})

# 4. demo09 baseline: real generation with save (approval off for this one)
app_module.REQUIRE_APPROVAL = False
r = c.post('/view_report', data={
    'report-type': 'stu_teacher',
    'student-name': 'demo09',
    'assessment-date': '2026-10-20',
    'what-to-assess': 'Engagement and progress concerns',
    'stu_role': 'You are an experienced robotics educator writing for the school counselor.',
    'save_checkbox': '1',
})
print('demo09 baseline:', r.status_code, len(r.data))
