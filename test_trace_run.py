"""One-off: exercise a full traced report run through the Flask test client."""
import os
from dotenv import load_dotenv
load_dotenv()

from app import app

c = app.test_client()
pw = os.environ.get("APP_PASSWORD", "")
if pw:
    r = c.post('/login', data={'password': pw})
    print("login:", r.status_code)

r = c.post('/view_report', data={
    'report-type': 'stu_teacher',
    'student-name': 'demo02',
    'assessment-date': '2026-10-20',
    'what-to-assess': 'Overall progress, strengths and areas to support',
    'stu_role': 'You are an experienced robotics educator writing a progress report for parents.',
    'save_checkbox': '1',
})
print("view_report:", r.status_code, len(r.data), "bytes")

import pipeline_trace as pt
runs = pt.list_traces()
print("traces:", [(x['run_id'], x['kind'], x['status'], x['summary']) for x in runs[:3]])
