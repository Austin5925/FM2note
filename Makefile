.PHONY: lint format test test-cov test-integ run serve deploy install-service uninstall-service

lint:
	ruff check src/ tests/

format:
	ruff format src/ tests/

test:
	pytest tests/ -v --tb=short -x

test-cov:
	pytest tests/ --cov=src --cov-report=term-missing

test-integ:
	pytest tests/ -v -m integration

run:
	python3.11 main.py run-once

serve:
	python3.11 main.py serve

# 服务器端：部署 RSSHub + Redis
deploy:
	ssh macroclaw.app "cd /opt/FM2note && git pull && docker compose up -d --build"

# 本地 Mac：安装 launchd 自启服务
install-service:
	cp scripts/com.fm2note.serve.plist ~/Library/LaunchAgents/
	launchctl load ~/Library/LaunchAgents/com.fm2note.serve.plist
	@echo "FM2note 服务已安装，登录时自动启动"

# 本地 Mac：卸载 launchd 服务
uninstall-service:
	launchctl unload ~/Library/LaunchAgents/com.fm2note.serve.plist
	rm ~/Library/LaunchAgents/com.fm2note.serve.plist
	@echo "FM2note 服务已卸载"

bump-patch:
	@python -c "import re; p='src/version.py'; t=open(p).read(); v=re.search(r'\"(.+)\"',t).group(1); parts=v.split('.'); parts[2]=str(int(parts[2])+1); nv='.'.join(parts); open(p,'w').write(f'VERSION = \"{nv}\"\n'); print(f'{v} -> {nv}')"
	@git add src/version.py

bump-minor:
	@python -c "import re; p='src/version.py'; t=open(p).read(); v=re.search(r'\"(.+)\"',t).group(1); parts=v.split('.'); parts[1]=str(int(parts[1])+1); parts[2]='0'; nv='.'.join(parts); open(p,'w').write(f'VERSION = \"{nv}\"\n'); print(f'{v} -> {nv}')"
	@git add src/version.py
