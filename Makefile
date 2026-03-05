# ──────────────────────────────────────────────────────────────────────────────
#  Prosthesis Leg — developer shortcuts
#  Usage:
#    make install      # first-time setup (venv + deps + USB permissions)
#    make wizard       # launch the setup wizard
#    make calibrate    # run calibration directly
#    make sweep        # run gesture sweep directly
#    make sine         # run sine gesture directly
#    make update-deps  # upgrade all Python dependencies
# ──────────────────────────────────────────────────────────────────────────────

PYTHON   := python3
VENV     := venv
PIP      := $(VENV)/bin/pip
PY       := $(VENV)/bin/python

.PHONY: install venv deps usb-perms wizard calibrate sweep sine update-deps clean

# ── setup ─────────────────────────────────────────────────────────────────────

install: venv deps usb-perms
	@echo ""
	@echo "✓  Installation complete."
	@echo "   Run:  make wizard"
	@echo "   Or :  source venv/bin/activate && python scripts/00_wizard.py"

venv:
	@echo "→  Creating virtual environment..."
	$(PYTHON) -m venv $(VENV)
	$(PIP) install --upgrade pip setuptools wheel --quiet

deps: venv
	@echo "→  Installing Python dependencies..."
	$(PIP) install -e ".[dev]" --quiet 2>/dev/null || $(PIP) install -e . --quiet
	@echo "→  Installing setserial (optional, for low-latency USB)..."
	sudo apt-get install -y setserial --quiet 2>/dev/null || true

usb-perms:
	@echo "→  Adding $(USER) to 'dialout' group (USB/serial access)..."
	@sudo usermod -aG dialout $(USER) && \
		echo "   ✓ Added. You must log out and back in (or reboot) for this to take effect." || \
		echo "   ! Could not add to dialout — you may need to run scripts with sudo."

# ── run shortcuts ─────────────────────────────────────────────────────────────

wizard:
	$(PY) scripts/00_wizard.py

calibrate:
	$(PY) scripts/01_calibrate_limits.py

sweep:
	$(PY) scripts/04_gesture_sweep.py --enable

sine:
	$(PY) scripts/05_gesture_sine.py --enable

# ── maintenance ───────────────────────────────────────────────────────────────

update-deps: venv
	$(PIP) install --upgrade -e . --quiet

clean:
	rm -rf $(VENV) src/*.egg-info src/prosthesis_leg/__pycache__ scripts/__pycache__
	@echo "Removed venv and caches. Run 'make install' to start fresh."
