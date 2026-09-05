deploy:
	git pull --ff-only && git fetch --tags && BOT_VERSION=$$(git describe --tags --always) GIT_COMMIT=$$(git rev-parse --short HEAD) DEPLOY_NOTIFICATION=1 docker compose up -d --build bot backup backup-test

restart:
	DEPLOY_NOTIFICATION=0 docker compose up -d --force-recreate bot

stop:
	docker compose stop bot backup backup-test backup-test-db

logs:
	docker compose logs -f bot

status:
	docker compose ps

test:
	python -m pytest -q

lint:
	python -m ruff check .
	python -m compileall -q main.py src tests
