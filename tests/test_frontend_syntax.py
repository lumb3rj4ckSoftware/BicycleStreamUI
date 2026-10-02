import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(not shutil.which('node'), reason='Node.js optional for frontend validation')
@pytest.mark.parametrize('name', ['admin', 'event-overlay', 'challenge-overlay', 'dashboard'])
def test_frontend_script_syntax_and_dom_targets(tmp_path, name):
    html = (ROOT/'web'/f'{name}.html').read_text(encoding='utf-8')
    scripts = re.findall(r'<script[^>]*>(.*?)</script>', html, re.S)
    assert scripts
    script = tmp_path/f'{name}.mjs'
    script.write_text('\n'.join(scripts), encoding='utf-8')
    result = subprocess.run(['node','--check',str(script)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    ids = set(re.findall(r'\bid="([^"]+)"', html))
    targets = set(re.findall(r"qs\(['\"]#([\w-]+)['\"]", '\n'.join(scripts)))
    assert targets <= ids, f'Missing DOM elements: {targets-ids}'


@pytest.mark.skipif(not shutil.which('node'), reason='Node.js optional for frontend validation')
def test_admin_module_initializes_and_buttons_execute():
    result = subprocess.run(['node',str(ROOT/'tests'/'frontend_admin_smoke.cjs')], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
