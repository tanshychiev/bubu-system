#!/usr/bin/env python3
"""Safely repair current BUBU config/settings.py without replacing unrelated settings."""
from pathlib import Path
import ast
import re
import shutil
import sys
from datetime import datetime

root = Path(__file__).resolve().parent
# Running inside /var/www/bubu, E:\Bubu_system, or from scripts folder
candidates = [Path.cwd() / 'config' / 'settings.py', root / 'config' / 'settings.py']
settings_path = next((p for p in candidates if p.is_file()), None)
if settings_path is None:
    print('ERROR: Run from BUBU project root (folder containing config/settings.py).')
    sys.exit(1)
raw = settings_path.read_text(encoding='utf-8-sig')
old = raw
# Fix ONLY a known pasted natural-language line that lost its comment prefix.
raw = re.sub(r'(?m)^(\s*)Keep approved employee devices signed in for up to one year \(renewed on activity\)\.\s*$',r'\1# Keep approved employee devices signed in for up to one year (renewed on activity).',raw)

# Modify only the STAFF_* assignments. Preserve pet alerts, PayWay, auth, db and other settings.
# Handles a straightforward one-line assignment; refuses ambiguous/multiline source instead of damaging it.
for key, fallback in [('STAFF_TELEGRAM_BOT_TOKEN', '""'), ('STAFF_TELEGRAM_CHAT_ID', '""')]:
    lines = raw.splitlines(keepends=True)
    pattern = re.compile(rf'^(\s*){key}\s*=\s*(.*)$')
    matches = [(i,pattern.match(line)) for i,line in enumerate(lines) if pattern.match(line)]
    if len(matches) > 1:
        print(f'ERROR: Multiple {key} assignments; no changes written.')
        sys.exit(2)
    repl = f'{key} = os.environ.get("{key}", {fallback})\n'
    if matches:
        i, match = matches[0]
        rhs = match.group(2).strip()
        # Do not replace a multiline expression whose continuation would remain behind
        if rhs.endswith('(') or rhs.endswith('\\') or rhs.count('(') > rhs.count(')'):
            print(f'ERROR: Multiline {key} assignment; no changes written.')
            sys.exit(2)
        lines[i] = repl
    else:
        lines.append('\n' + repl)
    raw = ''.join(lines)

# Make sure the os module is in scope, preserving existing imports.
if not re.search(r'(?m)^\s*import\s+os(?:\s|,|$)', raw):
    raw = 'import os\n' + raw
try:
    ast.parse(raw, filename=str(settings_path))
except SyntaxError as e:
    print(f'ERROR: Remaining syntax error on line {e.lineno}: {e.msg}')
    print('The settings file was NOT changed.')
    sys.exit(3)
if old == raw:
    print('Already repaired; no changes needed.')
    sys.exit(0)
backup = settings_path.with_name('settings.py.bak-' + datetime.now().strftime('%Y%m%d-%H%M%S'))
shutil.copy2(settings_path, backup)
settings_path.write_text(raw, encoding='utf-8')
print('Updated:', settings_path)
print('Backed up original:', backup)
print('Preserved all pet-sales and other settings; no secrets printed.')
print('Next: python manage.py check')
