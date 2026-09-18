"""Exercise startup and authentication in a process isolated from local mission data."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest


class TestApplicationSmoke(unittest.TestCase):
    def test_startup_auth_mission_and_static_app(self):
        project = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="cyberscribe-test-") as directory:
            env = os.environ.copy()
            env.update(DATA_DIR=str(Path(directory) / "data"), OUTPUT_DIR=str(Path(directory) / "output"))
            script = textwrap.dedent('''
                import os
                from pathlib import Path
                from unittest.mock import patch
                from fastapi.testclient import TestClient
                import server

                with TestClient(server.app) as client:
                    assert client.get('/openapi.json').json()['info']['title'] == 'CyberScribe'
                    assert client.get('/api/missions').status_code == 401
                    user = {'username': 'smoke-admin', 'password': 'local-test-password'}
                    response = client.post('/api/auth/bootstrap', json=user)
                    assert response.status_code == 200, response.text
                    assert client.post('/api/auth/bootstrap', json=user).status_code == 403
                    response = client.post('/api/auth/login', json=user)
                    assert response.status_code == 200, response.text
                    assert client.get('/api/auth/me').json()['username'] == user['username']
                    source = Path(os.environ['DATA_DIR']) / 'sources'
                    source.mkdir()
                    response = client.post('/api/missions', json={
                        'name': 'Smoke mission', 'source_path': str(source),
                        'output_path': os.environ['OUTPUT_DIR'],
                    })
                    assert response.status_code == 200, response.text
                    mission = response.json()['id']
                    for kind in ('rmp', 'timeline', 'aar', 'sitrep'):
                        response = client.get(f'/api/missions/{mission}/reports/{kind}')
                        assert response.status_code == 200, response.text
                    response = client.post(f'/api/missions/{mission}/reports/rmp/save', json={
                        'content': '<p>Reviewed smoke-test report.</p>',
                    })
                    assert response.status_code == 200, response.text
                    assert list(Path(os.environ['OUTPUT_DIR']).glob('*.docx'))
                    if (server.WEB_ROOT / 'index.html').is_file():
                        response = client.get('/')
                        assert response.status_code == 200
                        assert '<title>CyberScribe</title>' in response.text
                        assert '/assets/' in response.text
                        assert client.get('/logo.png').status_code == 200
                        assert client.get('/missing-file.js').status_code == 404
                    with patch.object(server, 'WEB_ROOT', source):
                        response = client.get('/')
                        assert response.status_code == 503
                        assert 'npm run build' in response.json()['detail']
                    client.post('/api/auth/logout')
                    assert client.get('/api/missions').status_code == 401
                print('CyberScribe startup, auth, reports, export, and static checks passed.')
            ''')
            result = subprocess.run(
                [sys.executable, "-B", "-c", script], cwd=project, env=env,
                capture_output=True, text=True, timeout=180,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
