.PHONY: lint format test test-cov test-integ run serve build macos-app macos-dmg macos-dmg-girlfriend macos-notarize macos-notarize-girlfriend clean install-service start-service uninstall-service

FM2NOTE_GIRLFRIEND_PROFILE_DIR ?= packaging/profiles/girlfriend

lint:
	ruff check src/ tests/
	ruff format --check src/ tests/

format:
	ruff format src/ tests/
	ruff check --fix src/ tests/

test:
	pytest tests/ -v --tb=short -x

test-cov:
	pytest tests/ --cov=src --cov-report=term-missing

test-integ:
	pytest tests/ -v -m integration

run:
	python main.py run-once

serve:
	python main.py serve

build:
	python -m build

macos-app:
	python3.11 scripts/build_macos_app.py

macos-dmg:
	python3.11 scripts/build_macos_app.py --dmg

macos-dmg-girlfriend:
	python3.11 scripts/build_macos_app.py --dmg --profile-dir "$(FM2NOTE_GIRLFRIEND_PROFILE_DIR)" --release-suffix girlfriend

macos-notarize:
	python3.11 scripts/build_macos_app.py --notarize --dmg

macos-notarize-girlfriend:
	python3.11 scripts/build_macos_app.py --notarize --dmg --profile-dir "$(FM2NOTE_GIRLFRIEND_PROFILE_DIR)" --release-suffix girlfriend

clean:
	rm -rf dist/ build/ *.egg-info/

install-service:
	python main.py install-service

start-service:
	python main.py start-service

uninstall-service:
	python main.py uninstall-service

bump-patch:
	@python -c "import re; p='src/version.py'; t=open(p).read(); v=re.search(r'\"(.+)\"',t).group(1); parts=v.split('.'); parts[2]=str(int(parts[2])+1); nv='.'.join(parts); open(p,'w').write(f'VERSION = \"{nv}\"\n'); print(f'{v} -> {nv}')"
	@git add src/version.py

bump-minor:
	@python -c "import re; p='src/version.py'; t=open(p).read(); v=re.search(r'\"(.+)\"',t).group(1); parts=v.split('.'); parts[1]=str(int(parts[1])+1); parts[2]='0'; nv='.'.join(parts); open(p,'w').write(f'VERSION = \"{nv}\"\n'); print(f'{v} -> {nv}')"
	@git add src/version.py
