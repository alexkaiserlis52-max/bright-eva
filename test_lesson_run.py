"""One-off: reproduce the crashed lesson-report path after the null-content fix."""
import os, re, time
from dotenv import load_dotenv
load_dotenv()

from app import app
import pipeline_trace as pt

c = app.test_client()
c.post('/login', data={'password': os.environ.get('APP_PASSWORD', '')})

t0 = time.time()
r = c.post('/view_report', data={
    'report-type': 'less_teacher',
    'lesson-name': 'ΜΓ',
    'assessment-date-lesson': '2026-10-21',
    'what-to-assess-lesson': 'Overall teaching quality and engagement across groups',
    'less_role': 'You are an experienced head of education reviewing lesson delivery.',
})
elapsed = time.time() - t0
body = r.data.decode('utf-8')
greek = re.findall(r'[Α-Ωα-ω]{4,}', body)
print('status:', r.status_code, '| greek word runs (>=4):', len(greek), '| wall time: %.1fs' % elapsed)

traces = pt.list_traces()
t = pt.load_trace(traces[0]['run_id'])
s = t['summary']
print('trace:', t['run_id'], '| llm calls:', s['llm_calls'], '| errors:', s['errors'],
      '| duration: %.1fs' % (s['duration_ms'] / 1000))
