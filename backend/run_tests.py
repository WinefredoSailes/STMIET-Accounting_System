import os
import sys

os.chdir(r"D:\ACCOUNTING-SYSTEM\backend")
sys.path.insert(0, ".")

os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings.test"

import django
django.setup()

# List all test modules
import unittest
loader = unittest.TestLoader()
print("Test modules found:")

# Try to discover tests
import subprocess
result = subprocess.run(
    [sys.executable, "-m", "pytest", "--collect-only", "-q"],
    capture_output=True,
    text=True,
    cwd=r"D:\ACCOUNTING-SYSTEM\backend"
)
print("STDOUT:", result.stdout[:500] if result.stdout else "None")
print("STDERR:", result.stderr[:500] if result.stderr else "None")
print("Return code:", result.returncode)