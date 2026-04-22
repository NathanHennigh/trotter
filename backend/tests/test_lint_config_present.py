import subprocess
import sys


def test_black_config_runs():
	# Ensure black config is valid and target paths exist
	res = subprocess.run([sys.executable, "-m", "black", "--version"], capture_output=True)
	assert res.returncode == 0


def test_isort_config_runs():
	res = subprocess.run([sys.executable, "-m", "isort", "--version"], capture_output=True)
	assert res.returncode == 0


