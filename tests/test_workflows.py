"""Isolated API checks; all records and media live in a temporary directory."""

import contextlib
import csv
import io
import json
import os
import sqlite3
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import wave
from pathlib import Path

import server


class QuietHandler(server.Handler):
    def log_message(self, _format, *_args):
        pass


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.original = (server.DATA, server.MEDIA, server.DBPATH, server.db, server._SECRET)
        self.temp = tempfile.TemporaryDirectory(prefix='tts_test_')
        server.DATA = Path(self.temp.name)
        server.MEDIA = server.DATA / 'media'
        server.DBPATH = server.DATA / 'annotations.db'
        self.connections = []

        def tracked_db():
            conn = sqlite3.connect(server.DBPATH, timeout=20, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute('PRAGMA foreign_keys=ON')
            conn.execute('PRAGMA busy_timeout=20000')
            self.connections.append(conn)
            return conn

        server.db = tracked_db
        self.old_password = os.environ.get('TTS_ADMIN_PASSWORD')
        os.environ['TTS_ADMIN_PASSWORD'] = 'temporary-test-password'
        with contextlib.redirect_stdout(io.StringIO()):
            server.setup()
        self.http = server.ThreadingHTTPServer(('127.0.0.1', 0), QuietHandler)
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        self.base = f'http://127.0.0.1:{self.http.server_port}'
        status, _, headers = self.request('/api/login', 'POST',
                                          {'username': 'admin', 'password': 'temporary-test-password'})
        self.assertEqual(status, 200)
        self.admin = headers['Set-Cookie'].split(';')[0]

    def tearDown(self):
        self.http.shutdown()
        self.http.server_close()
        self.thread.join(timeout=3)
        for conn in self.connections:
            conn.close()
        server.DATA, server.MEDIA, server.DBPATH, server.db, server._SECRET = self.original
        if self.old_password is None:
            os.environ.pop('TTS_ADMIN_PASSWORD', None)
        else:
            os.environ['TTS_ADMIN_PASSWORD'] = self.old_password
        self.temp.cleanup()

    def request(self, path, method='GET', body=None, cookie=None):
        data = None if body is None else (body if isinstance(body, bytes) else json.dumps(body).encode())
        headers = {}
        if cookie:
            headers['Cookie'] = cookie
        if data is not None and not isinstance(body, bytes):
            headers['Content-Type'] = 'application/json'
        request = urllib.request.Request(self.base + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                content = response.read()
                if response.headers.get('Content-Type', '').startswith('application/json') and content:
                    content = json.loads(content)
                return response.status, content, response.headers
        except urllib.error.HTTPError as error:
            content = error.read()
            return error.code, json.loads(content) if content else {}, error.headers

    def evaluator(self, username):
        status, _, _ = self.request('/api/admin/users', 'POST',
                                    {'username': username, 'password': 'temporary-test-password'}, self.admin)
        self.assertEqual(status, 201)
        status, data, headers = self.request('/api/login', 'POST',
                                             {'username': username, 'password': 'temporary-test-password'})
        self.assertEqual(status, 200)
        return data['user'], headers['Set-Cookie'].split(';')[0]

    def audio_url(self):
        with io.BytesIO() as buffer:
            with wave.open(buffer, 'wb') as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(8000)
                audio.writeframes(b'\0\0' * 800)
            content = buffer.getvalue()
        status, data, _ = self.request('/api/admin/upload?filename=sample.wav', 'POST', content, self.admin)
        self.assertEqual(status, 201)
        return data['audio_url']

    def sample(self, sample_id, audio_url, phase='pilot'):
        return self.request('/api/admin/sample', 'POST',
                            {'sample_id': sample_id, 'target_text': 'Văn bản kiểm tra.',
                             'audio_url': audio_url, 'phase': phase,
                             'private_metadata': {'model_id': 'operator-only'}}, self.admin)

    def test_source_validation_and_media_access(self):
        status, _, _ = self.request('/api/admin/upload?filename=bad.wav', 'POST', b'not audio', self.admin)
        self.assertEqual(status, 400)
        audio_url = self.audio_url()
        self.assertEqual(self.request(audio_url)[0], 401)
        self.assertEqual(self.request(audio_url, cookie=self.admin)[0], 200)
        for payload in (
            {'sample_id': None, 'target_text': 'Text', 'audio_url': audio_url},
            {'sample_id': 'x', 'target_text': None, 'audio_url': audio_url},
            {'sample_id': 'x', 'target_text': 'Text', 'audio_url': '/media/nonexistent.wav'},
        ):
            self.assertEqual(self.request('/api/admin/sample', 'POST', payload, self.admin)[0], 400)
        self.assertEqual(self.sample('valid', audio_url)[0], 201)

    def test_pair_blinding_canonicalization_and_qc(self):
        url = self.audio_url()
        self.assertEqual(self.sample('model_a', url)[0], 201)
        self.assertEqual(self.sample('model_b', url)[0], 201)
        pair_id = 'revealing_pair_id'
        self.assertEqual(self.request('/api/admin/pair', 'POST',
                                      {'pair_id': pair_id, 'sample_a_id': 'model_a',
                                       'sample_b_id': 'model_b', 'phase': 'pilot'}, self.admin)[0], 201)
        chosen = None
        for number in range(1, 9):
            user, cookie = self.evaluator(f'person{number}')
            status, queue, _ = self.request('/api/next?workflow=pair&phase=pilot', cookie=cookie)
            self.assertEqual(status, 200)
            self.assertNotIn('pair_id', queue['item'])
            self.assertNotIn('sample_a_id', queue['item'])
            self.assertNotIn('private_metadata', queue['item'])
            self.assertRegex(queue['task_token'], r'^[a-f0-9]{64}$')
            if server.swapped_for(user['id'], pair_id):
                chosen = cookie, queue['task_token']
                break
        self.assertIsNotNone(chosen)
        cookie, token = chosen
        self.assertEqual(self.request('/api/submit', 'POST',
                                      {'workflow': 'pair', 'item_token': token, 'status': 'completed',
                                       'text_accuracy_a': 'has_error', 'text_accuracy_b': 'no_error',
                                       'preference_display': 3}, cookie)[0], 400)
        self.assertEqual(self.request('/api/submit', 'POST',
                                      {'workflow': 'pair', 'item_token': token, 'status': 'completed',
                                       'text_accuracy_a': 'has_error', 'text_accuracy_b': 'no_error',
                                       'preference_display': 2, 'preference_reasons': [{}]}, cookie)[0], 400)
        status, _, _ = self.request('/api/submit', 'POST',
                                    {'workflow': 'pair', 'item_token': token, 'status': 'completed',
                                     'text_accuracy_a': 'has_error', 'text_accuracy_b': 'no_error',
                                     'preference_display': 2, 'preference_reasons': ['pacing']}, cookie)
        self.assertEqual(status, 200)
        status, raw, _ = self.request('/api/admin/export?kind=pair_annotations', cookie=self.admin)
        self.assertEqual(status, 200)
        record = json.loads(raw.splitlines()[0])
        self.assertEqual((record['sample_a_id'], record['sample_b_id']), ('model_a', 'model_b'))
        self.assertEqual((record['display_swapped'], record['preference_display'], record['preference']),
                         (True, 2, -2))
        self.assertEqual((record['text_accuracy_a'], record['text_accuracy_b']), ('no_error', 'has_error'))
        status, qc, _ = self.request('/api/admin/quality?phase=pilot', cookie=self.admin)
        self.assertEqual(status, 200)
        self.assertEqual(qc['pair']['direction_counts'], {'A': 0, 'B': 1, 'Tie': 0})
        self.assertEqual(qc['pair']['position_by_swap']['1']['display_a_wins'], 1)

    def test_single_validation_statuses_and_drafts(self):
        url = self.audio_url()
        self.assertEqual(self.sample('single', url)[0], 201)
        user, cookie = self.evaluator('personone')
        status, queue, _ = self.request('/api/next?workflow=single&phase=pilot', cookie=cookie)
        self.assertEqual(status, 200)
        self.assertNotIn('sample_id', queue['item'])
        token = queue['task_token']
        self.assertEqual(self.request('/api/admin/export?kind=samples', cookie=cookie)[0], 403)
        self.assertEqual(self.request('/api/draft', 'POST',
                                      {'workflow': 'single', 'item_token': token,
                                       'content': {'text_accuracy': 'has_error', 'note': 'resume'}}, cookie)[0], 200)
        self.assertEqual(self.request('/api/next?workflow=single&phase=pilot', cookie=cookie)[1]['draft']['note'], 'resume')
        scores = {key: 3 for key in server.SCORES}
        base = {'workflow': 'single', 'item_token': token, 'status': 'completed',
                'text_accuracy': 'has_error', **scores}
        self.assertEqual(self.request('/api/submit', 'POST', {**base, 'error_types': []}, cookie)[0], 400)
        self.assertEqual(self.request('/api/submit', 'POST', {**base, 'error_types': [{}]}, cookie)[0], 400)
        self.assertEqual(self.request('/api/submit', 'POST',
                                      {**base, 'error_types': ['omission'], 'confidence': 'high'}, cookie)[0], 200)
        self.assertEqual(self.request('/api/submit', 'POST',
                                      {**base, 'error_types': ['omission']}, cookie)[0], 409)
        for name, status_name in [('persontwo', 'invalid'), ('personthree', 'skipped')]:
            _, other = self.evaluator(name)
            queue = self.request('/api/next?workflow=single&phase=pilot', cookie=other)[1]
            status, _, _ = self.request('/api/submit', 'POST',
                                        {'workflow': 'single', 'item_token': queue['task_token'],
                                         'status': status_name, 'status_reason': 'test reason',
                                         'confidence': 'low'}, other)
            self.assertEqual(status, 200)
        qc = self.request('/api/admin/quality?phase=pilot', cookie=self.admin)[1]
        self.assertEqual(qc['single']['status_counts'], {'completed': 1, 'invalid': 1, 'skipped': 1})
        raw = self.request('/api/admin/export?kind=single_annotations', cookie=self.admin)[1]
        self.assertEqual(len(raw.splitlines()), 3)
        self.assertTrue(all(row['confidence'] == 'low' for row in
                            (json.loads(line) for line in raw.splitlines() if b'"status":"completed"' not in line)))

    def test_three_independent_completed_labels_and_phase_queues(self):
        url = self.audio_url()
        self.assertEqual(self.sample('pilot_item', url, 'pilot')[0], 201)
        self.assertEqual(self.sample('main_item', url, 'main')[0], 201)
        for number in range(1, 4):
            _, cookie = self.evaluator(f'rater{number}')
            pilot = self.request('/api/next?workflow=single&phase=pilot', cookie=cookie)[1]
            main = self.request('/api/next?workflow=single&phase=main', cookie=cookie)[1]
            self.assertNotEqual(pilot['task_token'], main['task_token'])
            self.assertIsNotNone(pilot['item'])
            self.assertIsNotNone(main['item'])
            payload = {'workflow': 'single', 'item_token': pilot['task_token'],
                       'status': 'completed', 'text_accuracy': 'no_error',
                       'error_types': [], **{key: number for key in server.SCORES}}
            self.assertEqual(self.request('/api/submit', 'POST', payload, cookie)[0], 200)
        _, fourth = self.evaluator('raterfour')
        self.assertIsNone(self.request('/api/next?workflow=single&phase=pilot', cookie=fourth)[1]['item'])
        self.assertIsNotNone(self.request('/api/next?workflow=single&phase=main', cookie=fourth)[1]['item'])
        pilot_qc = self.request('/api/admin/quality?phase=pilot', cookie=self.admin)[1]['single']
        main_qc = self.request('/api/admin/quality?phase=main', cookie=self.admin)[1]['single']
        self.assertEqual((pilot_qc['completed_items'], pilot_qc['text_accuracy_full_agreement_at_3']), (1, 1))
        self.assertEqual(main_qc['status_counts']['completed'], 0)

    def test_phase_warning_and_transactional_import(self):
        url = self.audio_url()
        self.assertEqual(self.sample('pilot_source', url, 'pilot')[0], 201)
        self.assertEqual(self.sample('main_source', url, 'main')[0], 201)
        status, result, _ = self.request('/api/admin/pair', 'POST',
                                         {'pair_id': 'mixed', 'sample_a_id': 'pilot_source',
                                          'sample_b_id': 'main_source', 'phase': 'main'}, self.admin)
        self.assertEqual(status, 201)
        self.assertTrue(any('Phase' in warning for warning in result['warnings']))
        qc = self.request('/api/admin/quality?phase=main', cookie=self.admin)[1]
        self.assertEqual(qc['pair']['phase_mismatch_pairs'], ['mixed'])
        status, imported, _ = self.request('/api/admin/import', 'POST',
                                            {'pairs': [{'pair_id': 'mixed_import',
                                                        'sample_a_id': 'pilot_source',
                                                        'sample_b_id': 'main_source',
                                                        'phase': 'main'}]}, self.admin)
        self.assertEqual(status, 201)
        self.assertEqual(len(imported['warnings']), 1)
        status, _, _ = self.request('/api/admin/import', 'POST',
                                    {'samples': [{'sample_id': 'transaction_test', 'target_text': 'Text',
                                                  'audio_url': url}],
                                     'pairs': [{'pair_id': 'bad', 'sample_a_id': 'transaction_test',
                                                'sample_b_id': 'missing'}]}, self.admin)
        self.assertEqual(status, 400)
        samples = self.request('/api/admin/data', cookie=self.admin)[1]['samples']
        self.assertNotIn('transaction_test', {sample['sample_id'] for sample in samples})

    def test_empty_csv_has_stable_columns(self):
        for kind, columns in [('single_annotations_csv', server.SINGLE_EXPORT_COLUMNS),
                              ('pair_annotations_csv', server.PAIR_EXPORT_COLUMNS)]:
            status, raw, _ = self.request('/api/admin/export?kind=' + kind, cookie=self.admin)
            self.assertEqual(status, 200)
            header = next(csv.reader(io.StringIO(raw.decode('utf-8-sig'))))
            self.assertEqual(header, columns)

    def test_existing_database_requires_its_pair_mapping_secret(self):
        (server.DATA / '.server_secret').unlink()
        with self.assertRaisesRegex(SystemExit, r'\.server_secret'):
            server.setup()


if __name__ == '__main__':
    unittest.main()
