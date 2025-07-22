PROJECT_DIR := $(shell pwd)
VENV_NAME := venv
VENV_ACTIVATE := $(VENV_NAME)/bin/activate
PORT := 5090
PYTHON := /usr/bin/python

install: 
	$(PYTHON) -m venv $(VENV_NAME)
	chmod +x $(VENV_NAME)/bin/activate
	source $(VENV_ACTIVATE); pip install -r requirements.txt

installdev: 
	$(PYTHON) -m venv $(VENV_NAME)
	chmod +x $(VENV_NAME)/bin/activate
	source $(VENV_ACTIVATE); pip install -r requirements-devel.txt
	cd ../tailwind
	npm

run:
	source $(VENV_ACTIVATE); nohup flask run --debug --host=0.0.0.0 --port=$(PORT) > log.txt 2>&1 &

start: install run

save: 
	pip freeze > requirements.txt
	git add .
	git commit -m "fix and updates"

test:
	. $(VENV_ACTIVATE); pytest

format:
	. $(VENV_ACTIVATE); black .

lint:
	. $(VENV_ACTIVATE); flake8

check: format lint test

stop:
	for pid in $(shell lsof -t -i:$(PORT)); do kill -9 $$pid; done
# if [[ $$VIRTUAL_ENV ]]; then deactivate; fi	

clean: stop
	rm -rf $(VENV_NAME)
	rm -rf log.txt
	rm -rf app_errors.log
	find $(PROJECT_DIR) -type d -name '__pycache__' -exec rm -rf {} +

rmcache: 
	rm -rf log.txt
	rm -rf app_errors.log
	find $(PROJECT_DIR) -type d -name '__pycache__' -exec rm -rf {} +

documents: 
	source $(VENV_ACTIVATE); pdoc --docformat google -o ../docs ./app

css: 
	cd ../tailwind && npm run build

deploy: clean install run

# todo docker:
