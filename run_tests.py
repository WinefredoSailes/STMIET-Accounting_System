import os
import sys

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.test')

# Add backend to path
sys.path.insert(0, r'D:\ACCOUNTING-SYSTEM\backend')

import pytest

if __name__ == '__main__':
    sys.exit(pytest.main(['-x', '-v']))