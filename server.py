#!/usr/bin/env python3
"""Vietnamese TTS Human Annotation — dependency-free local/LAN web server.

Run: python server.py --host 127.0.0.1 --port 8765
On first run, set TTS_ADMIN_PASSWORD environment variable or use generated password printed once.
"""
from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import hmac
import io
import json
import os
import re
import secrets
import sqlite3
import sys
import threading
import time
import urllib.parse
from datetime import datetime, timezone
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get('TTS_DATA_DIR', str(ROOT / 'data'))).resolve()
MEDIA = DATA / 'media'
DBPATH = DATA / 'annotations.db'
HTML = ROOT / 'index.html'
LOCK = threading.RLock()
MAX_UPLOAD = 60 * 1024 * 1024
MAX_JSON = 4 * 1024 * 1024
PHASES = {'pilot', 'main'}
WORKFLOWS = {'single'}
ACCURACY = {'no_error', 'has_error', 'unsure'}
ERRORS = {'omission', 'insertion', 'substitution', 'repetition'}
SCORES = ['pronunciation', 'intonation', 'pacing', 'audio_quality', 'naturalness']
CONFIDENCE = {'low', 'medium', 'high'}
SINGLE_EXPORT_COLUMNS = ['sample_id','username','workflow','phase','status','status_reason',
                         'text_accuracy','error_types',*SCORES,'confidence','note',
                         'started_at','submitted_at','duration_seconds']
USER_RE = re.compile(r'^[a-zA-Z0-9._-]{3,40}$')
ID_RE = re.compile(r'^[A-Za-z0-9._:-]{1,100}$')
AUDIO_EXT = {'.mp3', '.wav', '.ogg', '.m4a', '.aac', '.webm', '.flac', '.opus'}
AUDIO_MIME = {'.mp3': 'audio/mpeg', '.wav': 'audio/wav', '.ogg': 'audio/ogg',
              '.m4a': 'audio/mp4', '.aac': 'audio/aac', '.webm': 'audio/webm',
              '.flac': 'audio/flac', '.opus': 'audio/ogg'}
_SECRET = None


def utcnow():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def db():
    conn = sqlite3.connect(DBPATH, timeout=20)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    conn.execute('PRAGMA busy_timeout=20000')
    return conn


def json_dumps(v):
    return json.dumps(v, ensure_ascii=False, separators=(',', ':'))


def fail(message, status=400):
    raise ApiError(message, status)


class ApiError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def pw_hash(password, salt=None):
    salt = salt or secrets.token_bytes(16)
    key = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 350000)
    return f'pbkdf2_sha256$350000${salt.hex()}${key.hex()}'


def pw_verify(password, stored):
    try:
        algorithm, iterations, salt, expected = stored.split('$')
        if algorithm != 'pbkdf2_sha256':
            return False
        actual = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), bytes.fromhex(salt), int(iterations))
        return hmac.compare_digest(actual, bytes.fromhex(expected))
    except (ValueError, TypeError):
        return False


def setup():
    global _SECRET
    secret_file = DATA / '.server_secret'
    if DBPATH.is_file() and not secret_file.is_file():
        raise SystemExit('Existing annotations.db requires data/.server_secret. Restore both from the same backup to preserve open task tokens.')
    DATA.mkdir(parents=True, exist_ok=True)
    MEDIA.mkdir(parents=True, exist_ok=True)
    with db() as c:
        c.executescript('''
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS users (
          id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL,
          role TEXT NOT NULL CHECK(role IN ('admin','evaluator')), created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sessions (
          token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), expires REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS samples (
          sample_id TEXT PRIMARY KEY, target_text TEXT NOT NULL, audio_url TEXT NOT NULL,
          style_instruction TEXT NOT NULL DEFAULT '', reference_audio_url TEXT NOT NULL DEFAULT '',
          phase TEXT NOT NULL CHECK(phase IN ('pilot','main')), private_metadata TEXT NOT NULL DEFAULT '{}',
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS drafts (
          user_id INTEGER NOT NULL REFERENCES users(id), workflow TEXT NOT NULL,
          item_id TEXT NOT NULL, content TEXT NOT NULL DEFAULT '{}',
          started_at TEXT NOT NULL, updated_at TEXT NOT NULL,
          PRIMARY KEY (user_id,workflow,item_id)
        );
        CREATE TABLE IF NOT EXISTS submissions (
          id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
          workflow TEXT NOT NULL, item_id TEXT NOT NULL, phase TEXT NOT NULL,
          status TEXT NOT NULL CHECK(status IN ('completed','invalid','skipped')),
          labels_json TEXT NOT NULL, display_swapped INTEGER NOT NULL DEFAULT 0,
          status_reason TEXT NOT NULL DEFAULT '', started_at TEXT NOT NULL, submitted_at TEXT NOT NULL,
          duration_seconds INTEGER NOT NULL, UNIQUE(user_id,workflow,item_id)
        );
        CREATE INDEX IF NOT EXISTS idx_submissions_item ON submissions(workflow,item_id,status);
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        ''')
        c.execute('INSERT OR IGNORE INTO settings(key,value) VALUES (?,?)', ('target_annotations','3'))
        existing = c.execute('SELECT id FROM users WHERE role=? LIMIT 1', ('admin',)).fetchone()
        if not existing:
            pw = os.environ.get('TTS_ADMIN_PASSWORD')
            generated = not pw
            if not pw:
                pw = secrets.token_urlsafe(15)
            if len(pw) < 8:
                raise SystemExit('TTS_ADMIN_PASSWORD must be at least 8 characters')
            c.execute('INSERT INTO users (username,password_hash,role,created_at) VALUES (?,?,?,?)',
                      ('admin', pw_hash(pw), 'admin', utcnow()))
            print('\n' + '='*68, flush=True)
            print('First-run admin account: admin', flush=True)
            print('Admin password: ' + pw, flush=True)
            print('SAVE THIS PASSWORD NOW. It will not be displayed again.', flush=True)
            print('='*68 + '\n', flush=True)
    if secret_file.exists():
        _SECRET = secret_file.read_bytes()
    else:
        _SECRET = secrets.token_bytes(32)
        secret_file.write_bytes(_SECRET)
        try: secret_file.chmod(0o600)
        except OSError: pass


def get_target(c):
    return max(1, min(30, int(c.execute('SELECT value FROM settings WHERE key=?', ('target_annotations',)).fetchone()['value'])))


def auth(h, admin=False):
    raw = h.headers.get('Cookie','')
    cookie = SimpleCookie()
    try: cookie.load(raw)
    except Exception: pass
    if 'tts_session' not in cookie:
        fail('Cần đăng nhập.', 401)
    token = cookie['tts_session'].value
    digest = hashlib.sha256(token.encode('utf-8')).hexdigest()
    with db() as c:
        row = c.execute('''SELECT u.id, u.username, u.role FROM sessions s
          JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires>?''',
          (digest,time.time())).fetchone()
    if not row:
        fail('Phiên đăng nhập đã hết hạn.', 401)
    result = dict(row)
    if admin and result['role']!='admin':
        fail('Chỉ quản trị viên được thực hiện thao tác này.', 403)
    return result


def check_origin(h):
    origin = h.headers.get('Origin')
    if origin:
        expect = ('https' if h.headers.get('X-Forwarded-Proto')=='https' else 'http') + '://' + h.headers.get('Host','')
        if origin != expect:
            fail('Yêu cầu không cùng nguồn bị từ chối.',403)


def body_json(h):
    length = int(h.headers.get('Content-Length','0'))
    if length <= 0 or length > MAX_JSON:
        fail('JSON rỗng hoặc vượt quá giới hạn 4 MB.',413)
    data = h.rfile.read(length)
    try:
        obj = json.loads(data.decode('utf-8'))
        if not isinstance(obj,dict):
            fail('Body JSON phải là object.')
        return obj
    except (UnicodeDecodeError,json.JSONDecodeError):
        fail('JSON không hợp lệ.')


def normalize_sample(o):
    if not isinstance(o,dict): fail('Mỗi sample phải là object.')
    if not isinstance(o.get('sample_id'),str): fail('sample_id phải là chuỗi.')
    sid = o['sample_id'].strip()
    if not ID_RE.fullmatch(sid): fail('sample_id chỉ gồm chữ, số, dấu . _ : - và tối đa 100 ký tự.')
    if not isinstance(o.get('target_text'),str): fail('target_text phải là chuỗi.')
    target = o['target_text'].strip()
    if not target: fail('Thiếu target_text cho sample '+sid)
    if len(target)>20000: fail('Văn bản mục tiêu quá dài.')
    if not isinstance(o.get('audio_url'),str): fail('audio_url phải là chuỗi.')
    audio_url = o['audio_url'].strip()
    if not audio_url: fail('Thiếu audio_url cho '+sid)
    if not valid_audio_url(audio_url): fail('audio_url phải là /media/... hoặc URL HTTPS cho '+sid)
    if o.get('reference_audio_url') is not None and not isinstance(o['reference_audio_url'],str):
        fail('reference_audio_url phải là chuỗi.')
    ref = (o.get('reference_audio_url') or '').strip()
    if ref and not valid_audio_url(ref): fail('reference_audio_url phải là /media/... hoặc URL HTTPS')
    phase = str(o.get('phase','main')).strip()
    if phase not in PHASES: fail('phase phải là pilot hoặc main')
    if o.get('style_instruction') is not None and not isinstance(o['style_instruction'],str):
        fail('style_instruction phải là chuỗi.')
    style = (o.get('style_instruction') or '').strip()
    meta = o.get('private_metadata',{})
    if not isinstance(meta,dict): fail('private_metadata phải là object JSON')
    return (sid,target,audio_url,style,ref,phase,json_dumps(meta),utcnow())


def valid_audio_url(url):
    if url.startswith('/media/'):
        name=url[len('/media/'):]
        return bool(re.fullmatch(r'[a-f0-9]{32}\.(?:mp3|wav|ogg|m4a|aac|webm|flac|opus)',name)) and (MEDIA/name).is_file()
    parsed = urllib.parse.urlparse(url)
    return parsed.scheme=='https' and bool(parsed.hostname) and not parsed.username and not parsed.password


def looks_like_audio(content,ext):
    if ext=='.wav': return content.startswith(b'RIFF') and content[8:12]==b'WAVE'
    if ext=='.mp3': return content.startswith(b'ID3') or (len(content)>1 and content[0]==255 and content[1]&0xe0==0xe0)
    if ext=='.ogg': return content.startswith(b'OggS')
    if ext=='.opus': return content.startswith(b'OggS') and b'OpusHead' in content[:256]
    if ext=='.m4a': return content[4:8]==b'ftyp'
    if ext=='.aac': return content.startswith(b'ADIF') or (len(content)>1 and content[0]==255 and content[1]&0xf0==0xf0)
    if ext=='.webm': return content.startswith(b'\x1a\x45\xdf\xa3')
    if ext=='.flac': return content.startswith(b'fLaC')
    return False


def task_token(user_id,workflow,item_id):
    msg=f'task:{user_id}:{workflow}:{item_id}'.encode('utf-8')
    return hmac.new(_SECRET,msg,hashlib.sha256).hexdigest()


def draft_item_for_token(c,user_id,workflow,token):
    if not isinstance(token,str) or not re.fullmatch(r'[a-f0-9]{64}',token):
        fail('Mã phiếu không hợp lệ.')
    for row in c.execute('SELECT item_id FROM drafts WHERE user_id=? AND workflow=?',(user_id,workflow)):
        if hmac.compare_digest(task_token(user_id,workflow,row['item_id']),token):
            return row['item_id']
    fail('Phiếu chưa được mở hoặc đã gửi.',409)


def queue_next(user, workflow, phase):
    if user['role']!='evaluator': fail('Quản trị viên không phải tài khoản gắn nhãn.',403)
    if workflow not in WORKFLOWS: fail('Hiện chỉ hỗ trợ đánh giá Single Audio.',409)
    if phase not in PHASES: fail('phase không hợp lệ.')
    table, column = 'samples','sample_id'
    with LOCK, db() as c:
        target=get_target(c)
        # Resume a previously opened unfinished draft first.
        row=c.execute(f'''SELECT i.{column} AS item_id,
              (SELECT COUNT(*) FROM submissions s WHERE s.workflow=? AND s.item_id=i.{column} AND s.status='completed') AS done,
              CASE WHEN d.user_id IS NULL THEN 0 ELSE 1 END AS has_draft
          FROM {table} i
          LEFT JOIN drafts d ON d.item_id=i.{column} AND d.workflow=? AND d.user_id=?
          WHERE i.phase=?
            AND NOT EXISTS (SELECT 1 FROM submissions x WHERE x.user_id=? AND x.workflow=? AND x.item_id=i.{column})
            AND (SELECT COUNT(*) FROM submissions y WHERE y.workflow=? AND y.item_id=i.{column} AND y.status='completed') < ?
          ORDER BY has_draft DESC,done DESC,i.created_at,i.{column} LIMIT 1''',
          (workflow,workflow,user['id'],phase,user['id'],workflow,workflow,target)).fetchone()
        count_user=c.execute('''SELECT COUNT(*) AS n FROM submissions WHERE user_id=? AND workflow=? AND phase=? AND status='completed' ''',
                             (user['id'],workflow,phase)).fetchone()['n']
        item_total=c.execute(f'SELECT COUNT(*) AS n FROM {table} WHERE phase=?',(phase,)).fetchone()['n']
        if not row:
            return {'item':None,'progress':{'completed_by_you':count_user,'total_items':item_total,'target_per_item':target}}
        item_id=row['item_id']
        now=utcnow()
        c.execute('''INSERT OR IGNORE INTO drafts(user_id,workflow,item_id,content,started_at,updated_at)
              VALUES(?,?,?,'{}',?,?)''',(user['id'],workflow,item_id,now,now))
        draft=c.execute('SELECT content,started_at,updated_at FROM drafts WHERE user_id=? AND workflow=? AND item_id=?',
                        (user['id'],workflow,item_id)).fetchone()
        item=dict(c.execute('''SELECT sample_id,target_text,audio_url,phase
                              FROM samples WHERE sample_id=?''',(item_id,)).fetchone())
        item.pop('sample_id')
        return {'item':item,'task_token':task_token(user['id'],workflow,item_id),
                'draft':json.loads(draft['content']),
                'progress':{'completed_by_you':count_user,'total_items':item_total,'target_per_item':target}}


def normalize_submission(user,payload):
    workflow=str(payload.get('workflow','')).strip()
    item_id=str(payload.get('item_id','')).strip()
    status=str(payload.get('status','completed')).strip()
    if workflow not in WORKFLOWS or not ID_RE.fullmatch(item_id): fail('workflow hoặc item_id không hợp lệ.')
    if status not in {'completed','invalid','skipped'}: fail('status không hợp lệ.')
    status_reason=str(payload.get('status_reason') or '').strip()
    if status!='completed' and len(status_reason)<3:
        fail('Invalid/Skipped phải có lý do cụ thể (ít nhất 3 ký tự).')
    if len(status_reason)>2000: fail('Lý do quá dài.')
    labels={}
    if status=='completed':
        if 'expressiveness' in payload: fail('Single Audio hiện chỉ có năm điểm; không nhận expressiveness.')
        confidence = payload.get('confidence')
        if confidence is not None and confidence!='' and (not isinstance(confidence,str) or confidence not in CONFIDENCE):
            fail('confidence phải là low, medium, high hoặc để trống')
        labels['confidence'] = confidence or None
        labels['note']=str(payload.get('note') or '').strip()[:4000]
        acc=payload.get('text_accuracy')
        if not isinstance(acc,str) or acc not in ACCURACY: fail('Single: cần chọn text accuracy.')
        errors=payload.get('error_types',[])
        if not isinstance(errors,list) or any(not isinstance(x,str) or x not in ERRORS for x in errors): fail('Loại lỗi Single không hợp lệ.')
        if acc=='has_error' and not errors: fail('Single: has_error phải chọn ít nhất một loại lỗi.')
        if acc!='has_error' and errors: fail('Single: không chọn loại lỗi khi no_error/unsure.')
        labels['text_accuracy']=acc
        labels['error_types']=list(dict.fromkeys(errors))
        for score in SCORES:
            val=payload.get(score)
            if type(val) is not int or not (1<=val<=5):
                fail('Single: '+score+' phải là số nguyên từ 1 đến 5.')
            labels[score]=val
    else:
        confidence=payload.get('confidence')
        if confidence is not None and confidence!='' and (not isinstance(confidence,str) or confidence not in CONFIDENCE):
            fail('confidence phải là low, medium, high hoặc để trống')
        labels={'confidence':confidence or None,'note':str(payload.get('note') or '').strip()[:4000]}
    return workflow,item_id,status,status_reason,labels


def all_status(c,phase):
    rows=c.execute('''SELECT i.sample_id AS id,
      SUM(CASE WHEN s.status='completed' THEN 1 ELSE 0 END) AS done,
      SUM(CASE WHEN s.status='invalid' THEN 1 ELSE 0 END) AS invalid,
      SUM(CASE WHEN s.status='skipped' THEN 1 ELSE 0 END) AS skipped
      FROM samples i LEFT JOIN submissions s ON s.workflow='single' AND s.item_id=i.sample_id
      WHERE i.phase=? GROUP BY i.sample_id ORDER BY i.created_at,i.sample_id''',(phase,)).fetchall()
    return [{**dict(x),'done':x['done'] or 0,'invalid':x['invalid'] or 0,
             'skipped':x['skipped'] or 0} for x in rows]


def aggregate(c,phase):
    target=get_target(c)
    states=all_status(c,phase)
    rows=c.execute('''SELECT status,labels_json,item_id FROM submissions
                      WHERE workflow='single' AND phase=?''',(phase,)).fetchall()
    completed=[json.loads(x['labels_json']) for x in rows if x['status']=='completed']
    grouped={}
    for x in rows:
        if x['status']=='completed':
            grouped.setdefault(x['item_id'],[]).append(json.loads(x['labels_json']))
    repeated=[v for v in grouped.values() if len(v)>=2]
    data={
        'total_items':len(states),
        'items':states,
        'items_at_target':sum(x['done']>=target for x in states),
        'completed_items':sum(x['done']>=target for x in states),
        'needs_labels':sum(max(0,target-x['done']) for x in states),
        'status_counts':{k:sum(x['status']==k for x in rows) for k in ('completed','invalid','skipped')},
        'score_means':{s:round(sum(x[s] for x in completed)/len(completed),3) if completed else None for s in SCORES},
        'score_distributions':{s:{str(v):sum(x[s]==v for x in completed) for v in range(1,6)} for s in SCORES},
        'text_accuracy':{k:sum(x['text_accuracy']==k for x in completed) for k in ACCURACY},
        'error_types':{k:sum(k in x['error_types'] for x in completed) for k in sorted(ERRORS)},
        'items_with_3_labels':sum(len(v)>=3 for v in grouped.values()),
        'text_accuracy_full_agreement_at_3':sum(len(v)>=3 and len({t['text_accuracy'] for t in v})==1 for v in grouped.values()),
        'score_average_spread':{s:round(sum(max(t[s] for t in v)-min(t[s] for t in v) for v in repeated)/len(repeated),3) if repeated else None for s in SCORES},
    }
    return {'phase':phase,'target_annotations':target,'single':data}


def export_rows(c,kind):
    if kind=='samples':
        return [dict(x) for x in c.execute('SELECT * FROM samples ORDER BY created_at')]
    result=[]
    for x in c.execute('''SELECT s.*,u.username FROM submissions s JOIN users u ON u.id=s.user_id
                          WHERE s.workflow='single' ORDER BY s.phase,s.item_id,s.submitted_at'''):
        d=dict(x)
        labels=json.loads(d.pop('labels_json'))
        d.pop('user_id',None)
        d.pop('id',None)
        d.pop('display_swapped',None)
        d['sample_id']=d.pop('item_id')
        d.update(labels)
        result.append(d)
    return result


class Handler(BaseHTTPRequestHandler):
    server_version = 'TTSAnnotation/1.0'

    def log_message(self, fmt, *args):
        sys.stderr.write('[%s] %s\n' % (self.log_date_time_string(), fmt%args))

    def send_bytes(self,data,ctype='application/json; charset=utf-8',status=200,extra=None):
        self.send_response(status)
        self.send_header('Content-Type',ctype)
        self.send_header('Content-Length',str(len(data)))
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Referrer-Policy','no-referrer')
        self.send_header('X-Frame-Options','DENY')
        for key,value in (extra or {}).items(): self.send_header(key,str(value))
        self.end_headers()
        self.wfile.write(data)

    def send_json(self,o,status=200,extra=None):
        self.send_bytes(json_dumps(o).encode('utf-8'),status=status,extra=extra)

    def do_GET(self):
        try: self.route_get()
        except ApiError as e: self.send_json({'error':str(e)},e.status)
        except (sqlite3.IntegrityError,ValueError) as e: self.send_json({'error':str(e)},400)
        except Exception:
            import traceback; traceback.print_exc();self.send_json({'error':'Lỗi máy chủ.'},500)

    def do_POST(self):
        try: check_origin(self);self.route_post()
        except ApiError as e: self.send_json({'error':str(e)},e.status)
        except (sqlite3.IntegrityError,ValueError) as e: self.send_json({'error':str(e)},400)
        except Exception:
            import traceback;traceback.print_exc();self.send_json({'error':'Lỗi máy chủ.'},500)

    def parsed(self):
        p=urllib.parse.urlsplit(self.path)
        return p.path,urllib.parse.parse_qs(p.query)

    def route_get(self):
        path,qs=self.parsed()
        if path=='/':
            data=HTML.read_bytes()
            script=re.search(rb'<script>(.*?)</script>',data,re.DOTALL)
            if not script: fail('Thiếu JavaScript giao diện.',500)
            # HTML parsing normalizes CRLF before browsers verify CSP hashes.
            script_hash=base64.b64encode(hashlib.sha256(script.group(1).replace(b'\r\n',b'\n')).digest()).decode('ascii')
            csp=("default-src 'self'; script-src 'self' 'sha256-"+script_hash+"'; "
                 "style-src 'self' 'unsafe-inline'; media-src 'self' https:; "
                 "connect-src 'self'; img-src 'self' data:; object-src 'none'; "
                 "frame-ancestors 'none'; base-uri 'none'")
            self.send_bytes(data,'text/html; charset=utf-8',extra={'Content-Security-Policy':csp})
            return
        if path=='/favicon.ico':
            self.send_bytes(b'',status=204);return
        if path.startswith('/media/'):
            auth(self)
            name=path[len('/media/'):]
            if not re.fullmatch(r'[a-f0-9]{32}\.(?:mp3|wav|ogg|m4a|aac|webm|flac|opus)',name): fail('Audio không tồn tại',404)
            src=MEDIA/name
            if not src.is_file(): fail('Audio không tồn tại',404)
            self.send_media(src)
            return
        if path=='/api/me':
            user=auth(self);self.send_json({'user':user});return
        if path=='/api/next':
            user=auth(self)
            wf=qs.get('workflow',['single'])[0]
            phase=qs.get('phase',['main'])[0]
            self.send_json(queue_next(user,wf,phase));return
        if path=='/api/admin/data':
            auth(self,True)
            with db() as c:
                samples=[dict(x) for x in c.execute('SELECT * FROM samples ORDER BY created_at')]
                for x in samples: x['private_metadata']=json.loads(x['private_metadata'])
                self.send_json({'samples':samples,'target_annotations':get_target(c)})
            return
        if path=='/api/admin/users':
            auth(self,True)
            with db() as c:
                rows=[dict(x) for x in c.execute('SELECT username,role,created_at FROM users ORDER BY created_at')]
                target=get_target(c)
            self.send_json({'users':rows,'target_annotations':target});return
        if path=='/api/admin/quality':
            auth(self,True)
            phase=qs.get('phase',['main'])[0]
            if phase not in PHASES: fail('phase không hợp lệ.')
            with db() as c: self.send_json(aggregate(c,phase))
            return
        if path=='/api/admin/submissions':
            auth(self,True)
            phase=qs.get('phase',['main'])[0]
            if phase not in PHASES: fail('phase không hợp lệ.')
            with db() as c:
                rows=[]
                for x in c.execute('''SELECT s.*,u.username FROM submissions s JOIN users u ON u.id=s.user_id
                                      WHERE s.phase=? AND s.workflow='single' ORDER BY s.submitted_at DESC''',(phase,)):
                    item=dict(x);item.pop('user_id');item['labels']=json.loads(item.pop('labels_json'));rows.append(item)
            self.send_json({'submissions':rows});return
        if path=='/api/admin/export':
            auth(self,True)
            kind=qs.get('kind',[''])[0]
            if kind not in {'samples','single_annotations','single_annotations_csv'}:
                fail('Export không hợp lệ.')
            with db() as c:
                rawkind=kind.removesuffix('_csv')
                rows=export_rows(c,rawkind)
            if kind=='samples':
                for r in rows:
                    if 'private_metadata' in r: r['private_metadata']=json.loads(r['private_metadata'])
            if kind.endswith('_csv'):
                buf=io.StringIO()
                keys=SINGLE_EXPORT_COLUMNS
                w=csv.DictWriter(buf,fieldnames=keys,extrasaction='ignore');w.writeheader()
                for row in rows: w.writerow({k:json_dumps(v) if isinstance(v,(list,dict)) else v for k,v in row.items()})
                data=('\ufeff'+buf.getvalue()).encode('utf-8')
                typ='text/csv; charset=utf-8'
                name=kind+'.csv' if not kind.endswith('_csv') else kind[:-4]+'.csv'
            else:
                data=('\n'.join(json_dumps(x) for x in rows)+'\n').encode('utf-8') if rows else b''
                typ='application/x-ndjson; charset=utf-8';name=kind+'.jsonl'
            self.send_bytes(data,typ,extra={'Content-Disposition':f'attachment; filename="{name}"'})
            return
        fail('Không tìm thấy đường dẫn.',404)

    def send_media(self,src):
        size=src.stat().st_size
        mime=AUDIO_MIME[src.suffix.lower()]
        start=0;end=size-1;status=200
        rng=self.headers.get('Range','')
        if rng:
            m=re.fullmatch(r'bytes=(\d*)-(\d*)',rng.strip())
            if m:
                if m.group(1): start=int(m.group(1))
                if m.group(2): end=min(size-1,int(m.group(2)))
                if not m.group(1) and m.group(2): start=max(0,size-int(m.group(2)));end=size-1
                if start>=size or end<start: fail('Range không hợp lệ',416)
                status=206
        self.send_response(status)
        self.send_header('Content-Type',mime)
        self.send_header('Content-Length',str(end-start+1))
        self.send_header('Accept-Ranges','bytes')
        self.send_header('Cache-Control','private,max-age=300')
        self.send_header('X-Content-Type-Options','nosniff')
        if status==206: self.send_header('Content-Range',f'bytes {start}-{end}/{size}')
        self.end_headers()
        with src.open('rb') as f:
            f.seek(start)
            remaining=end-start+1
            while remaining>0:
                chunk=f.read(min(1024*256,remaining))
                if not chunk: break
                self.wfile.write(chunk);remaining-=len(chunk)

    def route_post(self):
        path,qs=self.parsed()
        if path=='/api/login':
            d=body_json(self)
            username=str(d.get('username','')).strip();password=str(d.get('password',''))
            with db() as c:
                row=c.execute('SELECT * FROM users WHERE username=?',(username,)).fetchone()
                if not row or not pw_verify(password,row['password_hash']): fail('Tên đăng nhập hoặc mật khẩu không đúng.',401)
                token=secrets.token_urlsafe(36)
                digest=hashlib.sha256(token.encode()).hexdigest()
                c.execute('DELETE FROM sessions WHERE expires<?',(time.time(),))
                c.execute('INSERT INTO sessions(token_hash,user_id,expires) VALUES(?,?,?)',(digest,row['id'],time.time()+14*24*3600))
            ck=f'tts_session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age={14*24*3600}'
            if self.headers.get('X-Forwarded-Proto')=='https': ck+='; Secure'
            self.send_json({'user':{'id':row['id'],'username':row['username'],'role':row['role']}},extra={'Set-Cookie':ck})
            return
        if path=='/api/logout':
            user=auth(self)
            raw=self.headers.get('Cookie','');cookie=SimpleCookie()
            try: cookie.load(raw)
            except Exception: pass
            if 'tts_session' in cookie:
                digest=hashlib.sha256(cookie['tts_session'].value.encode()).hexdigest()
                with db() as c: c.execute('DELETE FROM sessions WHERE token_hash=?',(digest,))
            self.send_json({'ok':True},extra={'Set-Cookie':'tts_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0'});return
        if path=='/api/draft':
            user=auth(self)
            if user['role']!='evaluator': fail('Chỉ annotator có thể lưu bản nháp.',403)
            d=body_json(self)
            wf=d.get('workflow')
            if wf not in WORKFLOWS: fail('Hiện chỉ hỗ trợ đánh giá Single Audio.',409)
            if not isinstance(wf,str) or wf not in WORKFLOWS: fail('Draft không hợp lệ.')
            content=d.get('content',{})
            if not isinstance(content,dict) or len(json_dumps(content))>20000: fail('Draft content không hợp lệ.')
            table,key='samples','sample_id'
            with LOCK, db() as c:
                item_id=draft_item_for_token(c,user['id'],wf,d.get('item_token'))
                exists=c.execute(f'SELECT 1 FROM {table} WHERE {key}=?',(item_id,)).fetchone()
                if not exists: fail('Item không tồn tại.',404)
                submitted=c.execute('SELECT 1 FROM submissions WHERE user_id=? AND workflow=? AND item_id=?',
                                    (user['id'],wf,item_id)).fetchone()
                if submitted: fail('Phiếu đã được gửi, không thể sửa.',409)
                timestamp=utcnow()
                c.execute('''INSERT INTO drafts(user_id,workflow,item_id,content,started_at,updated_at)
                      VALUES(?,?,?,?,?,?) ON CONFLICT(user_id,workflow,item_id) DO UPDATE SET content=excluded.content,updated_at=excluded.updated_at''',
                      (user['id'],wf,item_id,json_dumps(content),timestamp,timestamp))
            self.send_json({'ok':True});return
        if path=='/api/submit':
            user=auth(self)
            if user['role']!='evaluator': fail('Chỉ annotator có thể gửi phiếu.',403)
            d=body_json(self)
            wf=d.get('workflow')
            if wf not in WORKFLOWS: fail('Hiện chỉ hỗ trợ đánh giá Single Audio.',409)
            if not isinstance(wf,str) or wf not in WORKFLOWS: fail('Workflow không hợp lệ.')
            with LOCK,db() as c:
                item_id=draft_item_for_token(c,user['id'],wf,d.get('item_token'))
                wf,item_id,status,reason,labels=normalize_submission(user,{**d,'item_id':item_id})
                table,key='samples','sample_id'
                row=c.execute(f'SELECT phase FROM {table} WHERE {key}=?',(item_id,)).fetchone()
                if not row: fail('Item không tồn tại.',404)
                old=c.execute('SELECT id FROM submissions WHERE user_id=? AND workflow=? AND item_id=?',
                              (user['id'],wf,item_id)).fetchone()
                if old: fail('Bạn đã gửi phiếu cho item này.',409)
                completed=c.execute('''SELECT COUNT(*) AS n FROM submissions WHERE workflow=? AND item_id=? AND status='completed' ''',
                                    (wf,item_id)).fetchone()['n']
                if status=='completed' and completed>=get_target(c):
                    fail('Item đã đủ phiếu hoàn thành; chưa lưu kết quả mới.',409)
                draft=c.execute('''SELECT started_at FROM drafts WHERE user_id=? AND workflow=? AND item_id=?''',
                                (user['id'],wf,item_id)).fetchone()
                if not draft: fail('Chưa mở item này trong phiên đánh giá.',409)
                started=draft['started_at'];submitted=utcnow()
                try:
                    t1=datetime.fromisoformat(started);t2=datetime.fromisoformat(submitted)
                    duration=max(0,int((t2-t1).total_seconds()))
                except Exception: duration=0
                swap=0
                c.execute('''INSERT INTO submissions(user_id,workflow,item_id,phase,status,labels_json,display_swapped,
                      status_reason,started_at,submitted_at,duration_seconds) VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
                      (user['id'],wf,item_id,row['phase'],status,json_dumps(labels),swap,reason,started,submitted,duration))
                c.execute('DELETE FROM drafts WHERE user_id=? AND workflow=? AND item_id=?',(user['id'],wf,item_id))
            self.send_json({'ok':True,'status':status,'submitted_at':submitted,'duration_seconds':duration});return
        if path=='/api/admin/users':
            auth(self,True);d=body_json(self)
            username=str(d.get('username','')).strip();password=str(d.get('password',''))
            role=str(d.get('role','evaluator'))
            if not USER_RE.fullmatch(username): fail('Username: 3–40 ký tự a-z, A-Z, số, . _ -')
            if len(password)<8: fail('Mật khẩu tối thiểu 8 ký tự.')
            if role not in {'admin','evaluator'}: fail('Role không hợp lệ.')
            with db() as c:
                c.execute('INSERT INTO users(username,password_hash,role,created_at) VALUES(?,?,?,?)',
                          (username,pw_hash(password),role,utcnow()))
            self.send_json({'ok':True,'username':username},201);return
        if path=='/api/admin/target':
            auth(self,True);d=body_json(self)
            n=d.get('target_annotations')
            if type(n) is not int or not (1<=n<=30): fail('Số nhãn mục tiêu phải là số nguyên 1–30.')
            with db() as c: c.execute('UPDATE settings SET value=? WHERE key=?',(str(n),'target_annotations'))
            self.send_json({'ok':True,'target_annotations':n});return
        if path=='/api/admin/upload':
            auth(self,True)
            filename=qs.get('filename',['audio.wav'])[0]
            ext=Path(filename).suffix.lower()
            if ext not in AUDIO_EXT: fail('Chỉ nhận audio: '+', '.join(sorted(AUDIO_EXT)))
            length=int(self.headers.get('Content-Length','0'))
            if not 0<length<=MAX_UPLOAD: fail('File audio vượt giới hạn 60 MB hoặc rỗng.',413)
            content=self.rfile.read(length)
            if not looks_like_audio(content,ext): fail('File không có header audio hợp lệ cho phần mở rộng đã chọn.')
            name=secrets.token_hex(16)+ext
            (MEDIA/name).write_bytes(content)
            self.send_json({'ok':True,'audio_url':'/media/'+name,'bytes':len(content)},201);return
        if path=='/api/admin/sample':
            auth(self,True);d=body_json(self)
            fields=normalize_sample(d)
            with db() as c:
                c.execute('''INSERT INTO samples(sample_id,target_text,audio_url,style_instruction,reference_audio_url,
                             phase,private_metadata,created_at) VALUES(?,?,?,?,?,?,?,?)''', fields)
            self.send_json({'ok':True,'sample_id':fields[0]},201);return
        if path=='/api/admin/pair':
            auth(self,True)
            fail('Hiện chỉ hỗ trợ đánh giá Single Audio; không tạo Pairwise mới.',409)
        if path=='/api/admin/import':
            auth(self,True);d=body_json(self)
            samples=d.get('samples',[])
            if not isinstance(samples,list): fail('samples phải là danh sách.')
            if 'pairs' in d: fail('Hiện chỉ hỗ trợ Single Audio; manifest không nhận pairs.',409)
            if not samples: fail('Manifest không có samples.')
            if len(samples)>10000: fail('Batch quá lớn, chia nhỏ dữ liệu.')
            with LOCK,db() as c:
                for raw in samples:
                    fields=normalize_sample(raw)
                    c.execute('''INSERT INTO samples(sample_id,target_text,audio_url,style_instruction,reference_audio_url,
                                    phase,private_metadata,created_at) VALUES(?,?,?,?,?,?,?,?)''',fields)
            self.send_json({'ok':True,'imported_samples':len(samples)},201);return
        fail('Không tìm thấy đường dẫn.',404)


def main():
    p=argparse.ArgumentParser(description='Vietnamese TTS Annotation web app')
    p.add_argument('--host',default='127.0.0.1')
    p.add_argument('--port',type=int,default=8765)
    args=p.parse_args()
    setup()
    server=ThreadingHTTPServer((args.host,args.port),Handler)
    print(f'Vietnamese TTS Annotation: http://127.0.0.1:{args.port}/',flush=True)
    if args.host not in ('127.0.0.1','localhost'):
        print('LAN mode enabled: trusted network only; use HTTPS for internet exposure.',flush=True)
    print(f'Storage: {DBPATH}',flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: print('\nShutting down…')
    finally: server.server_close()


if __name__=='__main__': main()
