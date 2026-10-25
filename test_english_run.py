"""One-off: e2e parallel-run verification — regenerate demo09 report, timed."""
import os, re, time
from dotenv import load_dotenv
load_dotenv()

from app import app
import pipeline_trace as pt

c = app.test_client()
c.post('/login', data={'password': os.environ.get('APP_PASSWORD', '')})

t0 = time.time()
r = c.post('/view_report', data={
    'report-type': 'stu_teacher',
    'student-name': 'demo09',
    'assessment-date': '2026-10-21',
    'what-to-assess': 'Engagement and progress concerns',
    'stu_role': 'You are an experienced robotics educator writing for the school counselor.',
    'save_checkbox': '1',
})
elapsed = time.time() - t0
body = r.data.decode('utf-8')
greek = re.findall(r'[Α-Ωα-ω]{4,}', body)
print('status:', r.status_code, '| greek word runs (>=4):', len(greek), '| wall time: %.1fs' % elapsed)

# newest trace should be this run: check llm event count + duration
traces = pt.list_traces()
t = pt.load_trace(traces[0]['run_id'])
s = t['summary']
print('trace:', t['run_id'], '| llm calls:', s['llm_calls'], '| critic fails:',
      s['critic_fails'], '| alerts:', s['alerts'], '| duration: %.1fs' % (s['duration_ms']/1000))
